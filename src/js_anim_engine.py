"""JS/Web 动画渲染底座。

论文转视频 pipeline 的平行管线: 由 opencode(DeepSeek) 生成自包含 HTML 动画,
再用 headless 浏览器(标准 Playwright)逐帧录屏为 PNG 序列, 最后 ffmpeg 合成 mp4。

本模块只负责"渲染底座"两件事, 不负责编排(编排在后续任务):
  1. ``_opencode_generate_html`` —— 调 opencode 生成符合契约的自包含 HTML。
  2. ``render_html_to_mp4``      —— 把 HTML 逐帧渲染并合成精确时长的 mp4。

HTML 契约(opencode 生成的 HTML 必须遵守):
  - 自包含单 HTML, 内联 JS/CSS, 1280x720 的 canvas 或 svg。
  - 必须定义全局: ``window.TOTAL_FRAMES``(整数总帧数)、``window.FPS``、
    ``window.renderFrame(frameIndex)``。
  - ``renderFrame`` 必须是纯函数式: 给定第 n 帧渲染同样画面, 不依赖真实时间、
    不依赖 setTimeout / requestAnimationFrame。

设计约束(工业级降级语义):
  - opencode 失败一律 fallback / 返回 None, 绝不抛(对齐 manim_engine 的处理)。
  - 渲染任何环节出错(Playwright 启动失败 / evaluate 报错 / ffmpeg 失败)
    都捕获后返回 None, 不抛, 以便上层平稳降级回 manim 管线。
"""

import os
import re
import glob
import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Playwright 缓存里复用已有的 chromium, 禁止触发下载(下载在本机会失败)。
_CHROMIUM_GLOB = os.path.expanduser(
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome"
)

# 渲染视口固定 1280x720, 与 HTML 契约一致。
_VIEWPORT = {"width": 1280, "height": 720}

# opencode 子进程超时(秒), 与 manim_engine 同量级(生成可能较慢)。
_OPENCODE_TIMEOUT = 86400


def _find_chromium_executable():
    """返回缓存中最新的 chromium 可执行文件路径; 找不到返回 None。"""
    matches = sorted(glob.glob(_CHROMIUM_GLOB), reverse=True)
    if not matches:
        return None
    return matches[0]


def _get_llm_api_key():
    """获取 DeepSeek/LLM API key。

    优先环境变量, fallback 到工程 config(与 manim_engine 一致的取值来源)。
    取不到返回空串(交由 opencode 自身报错, 本模块不抛)。
    """
    key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    try:
        from src.config import LLM_API_KEY as _CFG_KEY  # 延迟导入避免循环依赖
        return _CFG_KEY or ""
    except Exception:
        try:
            from config import LLM_API_KEY as _CFG_KEY  # 兼容直接在 src 下运行
            return _CFG_KEY or ""
        except Exception:
            return ""


def _strip_ansi(text):
    """去掉终端 ANSI 转义码(对齐 manim_engine 的清洗)。"""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"\033\[[0-9;]*m", "", text)
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    return text


def _validate_anim_html(html):
    """校验 HTML 是否满足渲染契约。

    要求: 含 ``<canvas`` 或 ``<svg``, 且含 ``renderFrame``, 且含 ``TOTAL_FRAMES``。
    校验不过返回 False。
    """
    if not html:
        return False
    low = html.lower()
    has_visual = ("<canvas" in low) or ("<svg" in low)
    has_render = "renderframe" in low
    has_total = "total_frames" in low
    return has_visual and has_render and has_total


def _extract_html_from_output(output):
    """从 opencode stdout/stderr 中提取 HTML 文本。

    顺序: ① ```html ... ``` 代码块; ② 以 <!doctype 或 <html 起始的文本。
    提取不到返回 None。
    """
    output = _strip_ansi(output or "")

    # ① ```html ... ``` 代码块
    block = re.search(r"```html\s*\n(.*?)\n```", output, re.DOTALL | re.IGNORECASE)
    if block:
        return block.group(1).strip()

    # ② 从 <!doctype 或 <html 起始的文本(到结尾, 去掉可能尾随的 ``` )
    start = re.search(r"(<!doctype html.*|<html[ >].*)", output,
                      re.DOTALL | re.IGNORECASE)
    if start:
        html = start.group(1).strip()
        html = re.sub(r"\n```\s*$", "", html)
        return html.strip()

    return None


def _opencode_generate_html(prompt_text, scene_name, temp_dir):
    """通过 opencode headless 模式调用 DeepSeek 生成自包含 HTML 动画。

    复用 manim_engine._opencode_generate 的 subprocess 框架:
      - prompt 写临时文件, 经 stdin 注入(避免 ARG_MAX 超限)。
      - wrapper bash 里 ``cd "{temp_dir}"`` 做 CWD 隔离
        (opencode 默认扫 cwd 找历史产物, 必须隔离)。
      - 处理 conda env PATH(同款 wrapper bash 规避 node 版本问题)。
      - 去 ANSI、超时捕获、任何异常一律返回 None(不抛, 配合 retry)。

    产物提取顺序(与 manim 的 .py 路径同构, 改成 .html):
      ① 优先读 ``temp_dir/{scene_name}.html``(调用前先删旧的同名文件,
         跑完存在即本次新产物);
      ② fallback 从 stdout 抽 ```html ... ``` 代码块;
      ③ fallback 抽以 <!doctype / <html 起始的文本。

    提取后校验(含 canvas/svg + renderFrame + TOTAL_FRAMES), 不过当失败。

    落盘语义(供 render_html_to_mp4 当文件路径用):
      - 主路径产物已是 ``temp_dir/{scene_name}.html`` 文件, 校验内容通过后
        直接返回其路径。
      - fallback 抽到的是内容字符串, 校验通过后写入
        ``temp_dir/{scene_name}.html`` 再返回该路径。

    Args:
        prompt_text: 完整 prompt(含 HTML 契约说明与场景描述)。
        scene_name: 场景名, 决定产物文件名 ``{scene_name}.html``。
        temp_dir: 隔离工作目录(opencode 的 cwd, prompt/wrapper/产物都在此)。

    Returns:
        成功返回 HTML 文件路径(``temp_dir/{scene_name}.html``);
        失败返回 None(交由上层 retry/降级)。
    """
    abs_temp = os.path.abspath(temp_dir)
    os.makedirs(abs_temp, exist_ok=True)

    # prompt 写临时文件, 避免 shell 转义与 ARG_MAX 问题
    prompt_file = os.path.join(abs_temp, "_opencode_html_prompt.txt")
    try:
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)
    except Exception as e:
        logger.error("写 opencode prompt 文件失败: %s", e)
        return None

    # 调用前清理上次的 <scene_name>.html: 跑完若存在 = 本次 Write 新产物
    scene_html_path = os.path.join(abs_temp, f"{scene_name}.html")
    try:
        if os.path.exists(scene_html_path):
            os.remove(scene_html_path)
    except Exception as _e:
        logger.warning("清理旧 %s 失败: %s", scene_html_path, _e)

    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = _get_llm_api_key()
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)

    # wrapper 脚本规避 shell 参数展开与 node 版本问题(同 manim_engine)
    wrapper_script = os.path.join(abs_temp, "_opencode_html_run.sh")
    try:
        with open(wrapper_script, "w") as wf:
            wf.write("#!/bin/bash\n")
            wf.write("export PATH=/usr/local/bin:$PATH\n")
            # CWD 隔离: cd 到 temp_dir, 让 opencode 看不到项目根历史产物
            wf.write(f'cd "{abs_temp}"\n')
            # 经 stdin 注入 prompt, 避免命令行超 ARG_MAX
            wf.write(f'opencode run < "{prompt_file}"\n')
        os.chmod(wrapper_script, 0o755)
    except Exception as e:
        logger.error("写 opencode wrapper 失败: %s", e)
        return None

    cmd = f"bash {wrapper_script}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            env=env, cwd=abs_temp, timeout=_OPENCODE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error("opencode(html) 调用超时")
        return None
    except Exception as e:
        logger.error("opencode(html) 调用失败: %s", e)
        return None

    logger.info(
        "opencode(html) subprocess: returncode=%s stdout_len=%d stderr_len=%d",
        result.returncode, len(result.stdout or ""), len(result.stderr or ""),
    )

    output = result.stdout or ""
    if not output:
        output = result.stderr or ""

    html = None
    from_write_file = False  # 标记内容是否已落在 scene_html_path 文件里

    # ① 优先路径: opencode 用 Write 工具写到 cwd/<scene_name>.html
    if os.path.exists(scene_html_path):
        try:
            html = open(scene_html_path, "r", encoding="utf-8").read()
            from_write_file = True
            logger.info("opencode 通过 Write 写入 %s", scene_html_path)
        except Exception as _e:
            logger.warning("读取 %s 失败: %s", scene_html_path, _e)
            html = None

    # ②③ fallback: 从 stdout 抽代码块 / 抽 <!doctype|<html 起始文本
    if not html:
        html = _extract_html_from_output(output)
        if html:
            logger.info("opencode(html) 从 stdout 提取到 HTML (%d 字符)", len(html))

    if not html:
        logger.warning(
            "opencode(html) 未返回可提取的 HTML (rc=%s): head 1000 字: %r",
            result.returncode, _strip_ansi(output)[:1000],
        )
        return None

    # 校验契约(在写盘前对内容做)
    if not _validate_anim_html(html):
        logger.warning(
            "opencode(html) 产物未通过契约校验"
            "(需含 canvas/svg + renderFrame + TOTAL_FRAMES), 当作失败"
        )
        return None

    # 落盘返回路径: 主路径文件已在, 直接返回; fallback 内容写入再返回。
    if not from_write_file:
        try:
            with open(scene_html_path, "w", encoding="utf-8") as f:
                f.write(html.strip())
            logger.info("opencode(html) fallback 内容已写入 %s", scene_html_path)
        except Exception as e:
            logger.error("写入 fallback HTML 到 %s 失败: %s", scene_html_path, e)
            return None

    return scene_html_path


def render_html_to_mp4(html_path, out_mp4_path, fallback_fps=24,
                       fallback_seconds=6.0, soft_max_seconds=12.0):
    """把自包含 HTML 动画逐帧录屏并 ffmpeg 合成为精确时长的 mp4。

    流程(标准 Playwright, evaluate 跑在 main world 才能访问 window.renderFrame):
      1. 取缓存中的 chromium, headless 启动, page.goto ``file://{abspath}``。
      2. 读 ``window.TOTAL_FRAMES`` / ``window.FPS``; 读不到或非法则用 fallback。
      3. 防爆 clamp: ``total_frames = min(total_frames, int(soft_max_seconds*fps))``,
         被截断时 warning。
      4. 逐帧 ``evaluate(renderFrame(f))`` + screenshot 存临时 PNG 序列。
      5. ffmpeg 合成 ``-framerate {fps} ... -r {fps}``, 时长 = total_frames/fps。

    Args:
        html_path: 输入 HTML 文件路径。
        out_mp4_path: 输出 mp4 路径。
        fallback_fps: 读不到 FPS 时的回退帧率。
        fallback_seconds: 读不到 TOTAL_FRAMES 时的回退时长(秒)。
        soft_max_seconds: 防爆上限(秒), 超出则截断帧数。

    Returns:
        成功(out 文件存在且 ffmpeg rc==0)返回 ``out_mp4_path``; 否则 None。
        任何异常都捕获后返回 None(降级语义, 不抛)。
    """
    # 延迟 import: 让 ``import js_anim_engine`` 本身不依赖 playwright,
    # 无 playwright 环境时只在真正渲染时降级返回 None, 不影响上层 import。
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        logger.error("playwright 未安装, 无法渲染 HTML->mp4: %s", e)
        return None

    exe = _find_chromium_executable()
    if not exe:
        logger.error("未找到缓存的 chromium 可执行文件 (%s), 无法渲染", _CHROMIUM_GLOB)
        return None

    abs_html = os.path.abspath(html_path)
    if not os.path.exists(abs_html):
        logger.error("HTML 文件不存在: %s", abs_html)
        return None

    out_dir = os.path.dirname(os.path.abspath(out_mp4_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory() as frame_dir:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=exe)
                try:
                    page = browser.new_page(viewport=_VIEWPORT)
                    page.goto(f"file://{abs_html}", wait_until="load")

                    # 读 FPS
                    try:
                        fps = page.evaluate("window.FPS")
                    except Exception:
                        fps = None
                    if not isinstance(fps, (int, float)) or fps <= 0:
                        logger.warning("HTML 未提供合法 FPS, 回退 %s", fallback_fps)
                        fps = fallback_fps
                    fps = int(round(fps))

                    # 读 TOTAL_FRAMES
                    try:
                        total_frames = page.evaluate("window.TOTAL_FRAMES")
                    except Exception:
                        total_frames = None
                    if not isinstance(total_frames, (int, float)) or total_frames <= 0:
                        logger.warning(
                            "HTML 未提供合法 TOTAL_FRAMES, 回退 %.2fs",
                            fallback_seconds,
                        )
                        total_frames = round(fallback_seconds * fps)
                    total_frames = int(total_frames)

                    # 防爆 clamp
                    hard_cap = int(soft_max_seconds * fps)
                    if total_frames > hard_cap:
                        logger.warning(
                            "总帧数 %d 超过 soft_max(%.2fs @ %dfps = %d 帧), 截断",
                            total_frames, soft_max_seconds, fps, hard_cap,
                        )
                        total_frames = hard_cap

                    if total_frames <= 0:
                        logger.error("有效帧数为 0, 放弃渲染")
                        return None

                    # 逐帧渲染 + 截图
                    for f in range(total_frames):
                        page.evaluate("window.renderFrame(%d)" % f)
                        page.screenshot(
                            path=os.path.join(frame_dir, "f%05d.png" % f)
                        )
                finally:
                    browser.close()

            # ffmpeg 合成
            ff_cmd = [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", os.path.join(frame_dir, "f%05d.png"),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
                os.path.abspath(out_mp4_path),
            ]
            try:
                ff = subprocess.run(
                    ff_cmd, capture_output=True, text=True, timeout=600,
                )
            except subprocess.TimeoutExpired:
                logger.error("ffmpeg 合成超时")
                return None

            if ff.returncode != 0:
                logger.error(
                    "ffmpeg 合成失败 rc=%s: %s",
                    ff.returncode, (ff.stderr or "")[-1000:],
                )
                return None

        if not os.path.exists(out_mp4_path):
            logger.error("ffmpeg 返回成功但输出文件不存在: %s", out_mp4_path)
            return None

        logger.info(
            "渲染完成: %s (%d 帧 @ %dfps = %.3fs)",
            out_mp4_path, total_frames, fps, total_frames / fps,
        )
        return out_mp4_path

    except Exception as e:
        logger.error("render_html_to_mp4 失败(降级): %s", e)
        return None
