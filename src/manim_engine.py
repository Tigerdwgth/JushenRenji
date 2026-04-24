"""Manim 演示视频生成引擎。

从现有流水线的 structured_plan 和论文原文中提取公式、模型架构等内容，
由 LLM 自动生成 ManimCE 代码并渲染为动画视频。

固定 4 场景结构:
  Scene 1: TitleScene    -> opening script -> 标题动画
  Scene 2: IntroScene    -> intro script   -> 背景动画
  Scene 3: MethodScene   -> method script  -> 架构/公式动画
  Scene 4: ResultsScene  -> results script -> 结果表格动画
"""

import os
import json
import re
import subprocess
import logging
import glob
import yaml
import shutil

from moviepy import VideoFileClip, concatenate_videoclips, AudioFileClip

from src.llm_tools.prompts import prompts_dict
from src.figure_analyzer import analyze_and_prepare, analysis_to_manim_context, check_consistency_with_vision_llm, extract_frame_from_video

logger = logging.getLogger(__name__)

# 渲染质量映射
QUALITY_MAP = {
    "low": "-ql",       # 480p
    "medium": "-qm",    # 720p
    "high": "-qh",      # 1080p
}

# 布局常量
TEXT_WRAP_THRESHOLD = 25      # 文本超过此字符数自动换行
MAX_FRAME_WIDTH = 12          # 画框最大宽度（安全区域）
MAX_FRAME_HEIGHT = 7          # 画框最大高度
SAFE_FRAME_WIDTH = 11         # 缩放目标宽度
SAFE_FRAME_HEIGHT = 6.5       # 缩放目标高度



class ManimEngine:
    """Manim 动画生成引擎（固定 4 场景结构）。"""

    def __init__(self, paper_text, structured_plan=None, output_dir="./output/manim"):
        self.paper_text = paper_text
        self.structured_plan = structured_plan or {}
        self.output_dir = output_dir
        self.temp_dir = os.path.join(output_dir, "temp")
        os.makedirs(self.output_dir, exist_ok=True)
        # 清空旧的临时文件，避免残留影响新 pipeline
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        self._config_cache = None

    # ------------------------------------------------------------------
    # 代码安全: 注入边界检查
    # ------------------------------------------------------------------

    def _wrap_long_texts(self, code):
        """自动给长 Text 字符串插入换行，支持 CJK 字符。"""
        def _has_cjk(text):
            return any('\u4e00' <= c <= '\u9fff' for c in text)

        def _wrap_long_text(match):
            full = match.group(0)
            text_match = re.search(r'Text\(\s*["\'](.*?)["\']', full, re.DOTALL)
            if not text_match:
                return full
            text = text_match.group(1)
            if "\\n" in text or "\n" in text:
                return full
            # 中英文使用不同的换行阈值
            if _has_cjk(text):
                threshold = 15  # 中文字符宽度约为英文 2 倍
                if len(text) <= threshold:
                    return full
                lines = [text[i:i+threshold] for i in range(0, len(text), threshold)]
            else:
                threshold = 40  # 英文用更宽的阈值
                if len(text) <= threshold:
                    return full
                words = text.split(" ")
                lines = []
                current = ""
                for w in words:
                    if current and len(current) + 1 + len(w) > threshold:
                        lines.append(current)
                        current = w
                    else:
                        current = (current + " " + w).strip()
                if current:
                    lines.append(current)
            new_text = "\\n".join(lines)
            return full.replace(text, new_text)

        pattern = r'Text\(\s*["\'][^"\']{' + str(TEXT_WRAP_THRESHOLD) + r',}["\'][^)]*\)'
        code = re.sub(pattern, _wrap_long_text, code)
        return code

    def _remove_trailing_fadeout(self, code):
        """移除末尾的 FadeOut，替换为 wait（防止最后一帧变黑）。
        只删除 construct 方法最后 5 行内的 FadeOut，避免误删中间的分页 FadeOut。"""
        lines = code.split('\n')
        # 找到最后一个非空非注释行的位置
        last_content_idx = len(lines) - 1
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].strip()
            if stripped and not stripped.startswith('#') and not stripped.startswith('_all_mobs'):
                last_content_idx = i
                break
        # 只在最后 5 行范围内查找 FadeOut
        search_start = max(0, last_content_idx - 5)
        for i in range(last_content_idx, search_start - 1, -1):
            if 'FadeOut' in lines[i] and 'self.play' in lines[i]:
                indent = len(lines[i]) - len(lines[i].lstrip())
                lines[i] = ' ' * indent + 'self.wait(2)  # 保持内容显示'
                break
        return '\n'.join(lines)


    def _ensure_page_fadeouts(self, code):
        """检测多个 FadeIn(pageN) 之间缺少 FadeOut 的情况并自动插入。"""
        import re as _re
        lines = code.split('\n')
        result = []
        # 跟踪当前活跃的 page 变量名
        active_pages = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            # 检测 FadeIn(someVar) 调用
            fadein_match = _re.search(r'self\.play\(\s*FadeIn\(\s*(\w+)', stripped)
            if fadein_match:
                var_name = fadein_match.group(1)
                # 如果有活跃的 page 且当前 FadeIn 的不是同一个，插入 FadeOut
                for active in active_pages:
                    if active != var_name:
                        indent = len(line) - len(line.lstrip())
                        result.append(' ' * indent + f'self.play(FadeOut({active}))')
                        result.append(' ' * indent + 'self.wait(0.3)')
                active_pages = [var_name]
            # 检测 FadeOut 调用，从 active 列表移除
            fadeout_match = _re.search(r'FadeOut\(\s*(\w+)', stripped)
            if fadeout_match and not fadein_match:
                var_name = fadeout_match.group(1)
                active_pages = [p for p in active_pages if p != var_name]
            result.append(line)
        return '\n'.join(result)

    def _inject_scale_safety(self, code):
        """注入 VGroup 缩放安全网，防止内容超出画框。"""
        lines = code.split('\n')
        safety = [
            '        # === Auto-scale safety net ===',
            '        _all_mobs = VGroup(*[m for m in self.mobjects if isinstance(m, VMobject)])',
            '        if len(_all_mobs) > 0:',
            '            if _all_mobs.width > ' + str(MAX_FRAME_WIDTH) + ':',
            '                _all_mobs.scale_to_fit_width(' + str(SAFE_FRAME_WIDTH) + ')',
            '            if _all_mobs.height > ' + str(MAX_FRAME_HEIGHT) + ':',
            '                _all_mobs.scale_to_fit_height(' + str(SAFE_FRAME_HEIGHT) + ')',
        ]
        # 找到 construct 方法体的最后一行（8 空格缩进的语句），但避免插入到
        # 函数调用括号内部。向上搜索第一个完整语句（不以 ) 结尾且非空）
        insert_idx = len(lines) - 1
        paren_depth = 0
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].strip()
            if not stripped or stripped.startswith('#'):
                continue
            # 跟踪括号深度，确保不在未闭合的括号内插入
            paren_depth += stripped.count(')') - stripped.count('(')
            if paren_depth <= 0 and lines[i].startswith('        '):
                insert_idx = i + 1
                break
        lines = lines[:insert_idx] + safety + lines[insert_idx:]
        return '\n'.join(lines)

    def _enforce_reading_time(self, code):
        """防闪屏：把 self.wait() 短于阅读需要的都抬升。

        规则：
        - 上一行是 self.play(... Write|FadeIn ...) → 后续 self.wait(<2.0) 抬到 2.0
        - 上一行是 self.play(... FadeOut ...) → 后续 self.wait(<0.8) 抬到 0.8
        - 其他情况 self.wait(<0.6) 抬到 0.8（消除闪烁）
        """
        import re as _re
        text_re = _re.compile(r"\bself\.play\([^)]*(?:Write|FadeIn|GrowArrow|Create|Indicate)[^)]*\)")
        fadeout_re = _re.compile(r"\bself\.play\([^)]*FadeOut[^)]*\)")
        wait_re = _re.compile(r"\bself\.wait\(\s*([0-9]*\.?[0-9]+)\s*\)")
        lines = code.split("\n")
        last = None  # "text" | "fadeout" | "other" | None
        out = []
        for line in lines:
            m = wait_re.search(line)
            if m:
                val = float(m.group(1))
                if last == "text" and val < 2.0:
                    new = 2.0
                elif last == "fadeout" and val < 0.8:
                    new = 0.8
                elif val < 0.6:
                    new = 0.8
                else:
                    new = val
                if new != val:
                    old = m.group(0)
                    repl = "self.wait(%s)" % ("%g" % new)
                    line = line.replace(old, repl, 1)
            elif text_re.search(line):
                last = "text"
            elif fadeout_re.search(line):
                last = "fadeout"
            elif "self.play(" in line:
                last = "other"
            out.append(line)
        return "\n".join(out)

    def inject_bounds_check(self, code):
        """注入自动缩放安全网、移除末尾 FadeOut、自动给长文本换行、确保分页 FadeOut、抬升 wait 时长。"""
        code = self._wrap_long_texts(code)
        code = self._ensure_page_fadeouts(code)
        code = self._remove_trailing_fadeout(code)
        code = self._inject_scale_safety(code)
        code = self._enforce_reading_time(code)
        return code


    def _opencode_generate(self, prompt_text):
        """通过 opencode headless 模式调用 DeepSeek-R1 生成代码。
        opencode 会自动加载 manim_skill 最佳实践。"""


        # 写 prompt 到临时文件避免 shell 转义问题
        prompt_file = os.path.join(os.path.abspath(self.temp_dir), "_opencode_prompt.txt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)

        env = os.environ.copy()
        env["DEEPSEEK_API_KEY"] = self._get_deepseek_key()
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        env["CUDA_VISIBLE_DEVICES"] = "0"
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # 写 wrapper 脚本避免 shell 参数展开问题
        wrapper_script = os.path.join(os.path.abspath(self.temp_dir), "_opencode_run.sh")
        with open(wrapper_script, "w") as wf:
            wf.write("#!/bin/bash\n")
            wf.write("export PATH=/usr/local/bin:$PATH\n")
            # 用变量读取 prompt，避免 $(cat) 在命令行展开时卡死
            wf.write(f'PROMPT_FILE="{prompt_file}"\n')
            wf.write('PROMPT=$(cat "$PROMPT_FILE")\n')
            wf.write('opencode run "$PROMPT"\n')
        os.chmod(wrapper_script, 0o755)
        cmd = f'bash {wrapper_script}' 
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                env=env, cwd=project_root
            )
            output = result.stdout
            if not output:
                output = result.stderr or ""

            # 1. 去掉 ANSI 转义码
            output = re.sub(r'\x1b\[[0-9;]*m', '', output)
            output = re.sub(r'\033\[[0-9;]*m', '', output)
            # 真正的 ANSI 字节
            output = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output)

            # 2. 提取 ```python ... ``` 代码块
            code_match = re.search(r'```python\s*\n(.*?)\n```', output, re.DOTALL)
            if code_match:
                code = code_match.group(1).strip()
                logger.info("opencode 返回代码 (%d 行)", code.count("\n") + 1)
                return code

            # 3. fallback: 提取 from manim import * 开始的内容
            manim_match = re.search(r'(from manim import \*.*)', output, re.DOTALL)
            if manim_match:
                code = manim_match.group(1).strip()
                # 去掉尾部的 ``` 标记
                code = re.sub(r'\n```\s*$', '', code)
                logger.info("opencode fallback 提取代码 (%d 行)", code.count("\n") + 1)
                return code

            logger.warning("opencode 未返回有效代码，输出前 500 字: %s", output[:500])
            return ""
        except subprocess.TimeoutExpired:
            logger.error("opencode 调用超时")
            return ""
        except Exception as e:
            logger.error("opencode 调用失败: %s", e)
            return ""

    def _opencode_generate_with_retry(self, prompt_text, attempts=3):
        """连续调用 opencode，直到拿到非空代码或次数用尽。"""
        for i in range(attempts):
            raw = self._opencode_generate(prompt_text)
            if raw:
                return raw
            logger.warning("opencode 返回空 (第 %d/%d 次)", i + 1, attempts)
        logger.error("opencode 连续 %d 次失败，放弃", attempts)
        return ""

    def _get_config(self):
        """读取并缓存 config.yaml 配置。"""
        if self._config_cache is None:
            config_path = "config.yaml"
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self._config_cache = yaml.safe_load(f) or {}
            else:
                self._config_cache = {}
        return self._config_cache

    def _get_deepseek_key(self):
        config = self._get_config()
        return config.get("llm_api_key", "") or os.environ.get("LLM_API_KEY", "")

    # ------------------------------------------------------------------
    # Manim 代码生成
    # ------------------------------------------------------------------

    def generate_manim_code(self, scene_info):
        """根据场景信息调用 LLM 生成 ManimCE 代码。支持图像分析增强。

        策略：
        - MethodScene (有图像分析) -> opencode headless (利用 manim_skill)
        - 其他场景 -> 直接 DeepSeek API (更快更稳定)
        """
        scene_type = scene_info.get("type", "formula")
        figure_analysis = scene_info.get("figure_analysis")

        # 选择 prompt
        if figure_analysis and scene_type == "architecture":
            prompt_key = "manim_generate_architecture_from_figure"
        else:
            prompt_key = f"manim_generate_{scene_type}"
        prompt = prompts_dict.get(prompt_key, prompts_dict.get("manim_generate_formula", ""))

        sname = scene_info.get("scene_name", "CustomScene")
        sdesc = scene_info.get("description", "")
        user_content = f"scene_name: {sname}\n"
        user_content += f"描述: {sdesc}\n"
        if scene_info.get("latex"):
            user_content += f"LaTeX 公式: {scene_info['latex']}\n"
        if scene_info.get("script_excerpt"):
            user_content += f"脚本原文: {scene_info['script_excerpt']}\n"

        # 注入图像分析上下文
        if figure_analysis:
            manim_ctx = figure_analysis.get("manim_context", "")
            if manim_ctx:
                user_content += f"\n{manim_ctx}\n"
            # 注入 Edit Banana 精确元素数据（包含 Manim 坐标）
            eb_elements = figure_analysis.get("eb_manim_elements", "")
            if eb_elements:
                user_content += f"\n## 论文方法图精确元素数据（SAM3 分割，坐标已转为 Manim 坐标系）\n"
                user_content += f"## 请严格按照这些坐标和颜色生成 Manim 代码！\n"
                user_content += eb_elements + "\n"
                logger.info("已注入 EB 精确元素数据 (%d 字符)", len(eb_elements))
            logger.info("已注入图像分析上下文 (类型: %s, %d 个组件)",
                       figure_analysis.get("figure_type", "unknown"),
                       len(figure_analysis.get("analysis", {}).get("components", [])))

        if not figure_analysis:
            # abstract+intro 的前 2000 字对 architecture scene 是噪声,
            # 有 figure_analysis 时依赖它与 eb_manim_elements 即可
            user_content += f"\n论文原文参考（前2000字）:\n{self.paper_text[:2000]}\n"
        user_content += "\n重要：生成的动画内容必须忠实于这篇论文的具体方法，不要用通用的示例。\n"

        full_prompt = prompt + "\n\n" + user_content

        # 所有场景统一走 opencode（禁止直连 API 生成 manim 代码）
        logger.info("使用 opencode 生成代码 (prompt_key=%s)...", prompt_key)
        raw = self._opencode_generate_with_retry(full_prompt, attempts=3)

        # 清理 markdown 代码块标记
        code = (raw or "").strip()
        if code.startswith("```"):
            code = re.sub(r"^```\w*\n?", "", code)
            code = re.sub(r"\n?```$", "", code)
            code = code.strip()

        return code
    # 渲染
    # ------------------------------------------------------------------

    def render_scene(self, code, scene_name, quality="medium", fmt="mp4", max_retries=3):
        """渲染单个 Manim 场景。"""
        quality_flag = QUALITY_MAP.get(quality, "-qm")
        fmt_flag = "--format=gif" if fmt == "gif" else ""

        for attempt in range(max_retries):
            script_path = os.path.join(self.temp_dir, f"{scene_name}.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            cmd = f"manim render {quality_flag} {fmt_flag} --media_dir {self.output_dir}/media {script_path} {scene_name}"
            logger.info("渲染场景 %s (第 %d 次): %s", scene_name, attempt + 1, cmd)

            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=86400
                )

                ext = "gif" if fmt == "gif" else "mp4"
                media_dir = os.path.join(self.output_dir, "media", "videos")
                found = glob.glob(os.path.join(media_dir, "**", f"{scene_name}.{ext}"), recursive=True)
                found = [f for f in found if "partial_movie_files" not in f]
                if found:
                    logger.info("场景 %s 渲染成功: %s", scene_name, found[0])
                    return found[0]

                if result.returncode == 0:
                    all_files = glob.glob(os.path.join(self.output_dir, "**", f"*.{ext}"), recursive=True)
                    all_files = [f for f in all_files if "partial_movie_files" not in f]
                    if all_files:
                        latest = max(all_files, key=os.path.getmtime)
                        logger.info("使用最新输出文件: %s", latest)
                        return latest

                error_msg = result.stderr or result.stdout
                logger.warning("场景 %s 渲染失败 (第 %d 次):\n%s", scene_name, attempt + 1, error_msg[:2000])

                if attempt < max_retries - 1:
                    fix_prompt = prompts_dict.get("manim_fix_code", "")
                    fix_content = f"原始代码:\n```python\n{code}\n```\n\n错误信息:\n```\n{error_msg[:3000]}\n```"
                    code = self._opencode_generate_with_retry(fix_prompt + "\n\n" + fix_content, attempts=2)
                    code = (code or "").strip()
                    if code.startswith("```"):
                        code = re.sub(r"^```\w*\n?", "", code)
                        code = re.sub(r"\n?```$", "", code)
                        code = code.strip()
                    if code:
                        logger.info("opencode 已修复代码，准备重试")
                    else:
                        logger.warning("opencode 修复失败，无法重试")

            except subprocess.TimeoutExpired:
                logger.error("场景 %s 渲染超时", scene_name)
            except Exception as e:
                logger.error("场景 %s 渲染异常: %s", scene_name, e)

        logger.error("场景 %s 渲染最终失败，已达最大重试次数", scene_name)
        return None

    # ------------------------------------------------------------------
    # Pipeline 图片加载（caption-based matching）
    # ------------------------------------------------------------------

    def load_pipeline_images(self):
        """从 pipeline 的 script.json 和 image_explanations 加载图片，按场景类型分配。"""
        pic_files = sorted(glob.glob("./pic/*.png"),
                          key=lambda x: int(re.findall(r"\d+", os.path.basename(x))[0])
                          if re.findall(r"\d+", os.path.basename(x)) else 0)

        if not pic_files:
            return {"opening": [], "intro": [], "method": [], "results": []}

        # 1. 优先从 script.json 读取（有最准确的 context/transition 信息）
        script_json = None
        for f in glob.glob("./src/output/*_script.json") + glob.glob("./output/*_script.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    script_json = json.load(fh)
                break
            except Exception:
                continue

        # 2. 或从 image_explanations.json 读取
        captions = {}
        expl_path = "./cache/image_explanations.json"
        if os.path.exists(expl_path):
            with open(expl_path, "r", encoding="utf-8") as f:
                explanations = json.load(f)
            for i, expl in enumerate(explanations):
                if i < len(pic_files):
                    captions[pic_files[i]] = {
                        "caption": expl.get("caption", ""),
                        "context": expl.get("context", ""),
                        "role": expl.get("figure_role", ""),
                        "section": expl.get("recommended_section", "method"),
                    }

        # 如果有 script.json，用它的 images 字段更新 captions
        if script_json and "images" in script_json:
            for img_info in script_json["images"]:
                idx = int(img_info.get("image_index", 0))
                if idx < len(pic_files):
                    captions[pic_files[idx]] = {
                        "caption": img_info.get("caption", ""),
                        "context": img_info.get("context", ""),
                        "role": "",
                        "section": "results" if "result" in img_info.get("context", "").lower() else "method",
                    }

        img_map = {"opening": [], "intro": [], "method": [], "results": []}

        # 按 caption/context 关键词匹配
        result_kws = ["table", "表", "result", "实验", "experiment", "performance", "ablation", "success"]
        method_kws = ["architecture", "架构", "pipeline", "framework", "模块", "method", "设计", "结构"]
        # 公式类图片关键词 - 这类图片不适合做视频主画面
        formula_kws = ["formula", "equation", "公式", "目标函数", "损失函数",
                       "约束条件", "constraint", "objective", "loss function",
                       "optimization", "数学", "derivation", "推导"]

        for path in pic_files:
            info = captions.get(path, {})
            text = (info.get("caption", "") + " " + info.get("context", "") + " " + info.get("section", "")).lower()

            # 公式类图片直接跳过，不放入任何 bucket
            if any(kw in text for kw in formula_kws) and not any(kw in text for kw in method_kws):
                logger.info("跳过公式类图片: %s", os.path.basename(path))
                continue
            if any(kw in text for kw in result_kws):
                img_map["results"].append(path)
            elif any(kw in text for kw in method_kws):
                img_map["method"].append(path)
            elif "intro" in text or "opening" in text:
                img_map["intro"].append(path)
            else:
                img_map["method"].append(path)

        # 确保 opening 有图片（用第一张 method 图或整体第一张）
        if not img_map["opening"]:
            if img_map["method"]:
                img_map["opening"] = [img_map["method"][0]]
            elif pic_files:
                img_map["opening"] = [pic_files[0]]
        if not img_map["intro"]:
            if len(img_map["method"]) > 1:
                img_map["intro"] = [img_map["method"][1]]
            elif img_map["method"]:
                img_map["intro"] = [img_map["method"][0]]

        logger.info("Pipeline 图片匹配: %s",
                    {k: [os.path.basename(p) for p in v] for k, v in img_map.items()})
        return img_map


    def generate_tts(self, scenes, narrations):
        """为场景生成 TTS 音频。

        Args:
            scenes: 场景列表。
            narrations: 与场景一一对应的讲解词列表。
        """
        try:
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer

            config = self._get_config()
            ds_key = config.get("dashscope_api_key", "")
            if ds_key:
                dashscope.api_key = ds_key

            audio_parts = []
            for i, text in enumerate(narrations):
                if not text or not text.strip():
                    continue

                audio_path = os.path.join(self.temp_dir, f"tts_{i}.mp3")
                synthesizer = SpeechSynthesizer(model="cosyvoice-v1", voice="longxiaochun")
                audio_data = synthesizer.call(text)

                if audio_data:
                    with open(audio_path, "wb") as f:
                        f.write(audio_data)
                    audio_parts.append(audio_path)
                    logger.info("TTS 第 %d 段生成成功: %s", i, text[:30])

            if not audio_parts:
                return None

            audio_clips = [AudioFileClip(p) for p in audio_parts]
            from moviepy import concatenate_audioclips
            combined = concatenate_audioclips(audio_clips)
            output_audio = os.path.join(self.temp_dir, "tts_combined.mp3")
            combined.write_audiofile(output_audio)

            for clip in audio_clips:
                clip.close()

            self._audio_parts = audio_parts  # 保存各段音频路径
            return output_audio

        except Exception as e:
            logger.warning("TTS 生成失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 拼接
    # ------------------------------------------------------------------

    def compose(self, scene_videos, tts_audio=None, fmt="mp4", scene_image_paths=None, narration_audios=None):
        """拼接所有场景视频为完整演示。"""
        import numpy as np
        from PIL import Image as PILImage

        if not scene_videos:
            logger.error("没有可拼接的视频片段")
            return None

        ext = "gif" if fmt == "gif" else "mp4"
        output_path = os.path.join(self.output_dir, f"manim_presentation.{ext}")

        final_clips = []

        for idx, vpath in enumerate(scene_videos):
            try:
                video = VideoFileClip(vpath)
            except Exception as e:
                logger.warning("加载视频片段失败 %s: %s", vpath, e)
                continue

            # 获取对应的音频
            audio = None
            if narration_audios and idx < len(narration_audios) and narration_audios[idx]:
                try:
                    audio = AudioFileClip(narration_audios[idx])
                except Exception:
                    pass

            # 如果音频比动画长，用 pipeline 图片填充
            if audio and audio.duration > video.duration:
                gap = audio.duration - video.duration + 1.0
                img_path = scene_image_paths[idx] if scene_image_paths and idx < len(scene_image_paths) else None

                if img_path and os.path.exists(img_path):
                    # 将 pipeline 图片做成视频片段
                    img = PILImage.open(img_path).convert("RGB")
                    w, h = video.w, video.h
                    max_w, max_h = int(w * 0.95), int(h * 0.95)
                    img_w, img_h = img.size
                    scale = min(max_w / img_w, max_h / img_h)
                    new_w, new_h = int(img_w * scale), int(img_h * scale)
                    img = img.resize((new_w, new_h), PILImage.LANCZOS)
                    bg = PILImage.new("RGB", (w, h), (0, 0, 0))
                    bg.paste(img, ((w - new_w) // 2, (h - new_h) // 2))
                    from moviepy import ImageClip
                    img_clip = ImageClip(np.array(bg), duration=gap)
                    video = concatenate_videoclips([video, img_clip])
                    logger.info("场景 %d: 动画后接 pipeline 图片 %s (%.1fs)", idx, img_path, gap)
                else:
                    # fallback: 冻结非黑帧
                    from moviepy import ImageClip
                    frame = video.get_frame(video.duration - 0.01)
                    if np.mean(frame) < 10:  # 全黑，回退找有内容的帧
                        for t in [video.duration*0.7, video.duration*0.5, video.duration*0.3, 1.0]:
                            f2 = video.get_frame(min(t, video.duration-0.01))
                            if np.mean(f2) > 10:
                                frame = f2
                                break
                    freeze = ImageClip(frame, duration=gap)
                    video = concatenate_videoclips([video, freeze])

            if audio:
                video = video.with_audio(audio)

            final_clips.append(video)

        if not final_clips:
            logger.error("所有视频片段加载失败")
            return None

        try:
            final = concatenate_videoclips(final_clips, method="compose")

            if fmt == "gif":
                final.write_gif(output_path, fps=15)
            else:
                final.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac")

            logger.info("演示视频已生成: %s", output_path)
            return output_path

        except Exception as e:
            logger.error("视频拼接失败: %s", e)
            return None
        finally:
            for clip in final_clips:
                try:
                    clip.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 主流程: 固定 4 场景结构
    # ------------------------------------------------------------------


    def _assign_images_to_scenes(self, pipeline_images, scene_defs, rendered_indices):
        """为渲染成功的场景分配不重复的 pipeline 图片。"""
        scene_image_paths = []
        used_images = set()
        for i in rendered_indices:
            sec = scene_defs[i]["section"]
            # 按优先级找：本 section > method > 任意
            candidates = (pipeline_images.get(sec, []) +
                         pipeline_images.get("method", []))
            img = None
            for c in candidates:
                if c not in used_images:
                    img = c
                    used_images.add(c)
                    break
            # fallback: 任意未用过的图
            if not img:
                for imgs in pipeline_images.values():
                    for c in imgs:
                        if c not in used_images:
                            img = c
                            used_images.add(c)
                            break
                    if img:
                        break
            scene_image_paths.append(img)
            logger.info("场景 %s 分配图片: %s", scene_defs[i]["scene_name"],
                       os.path.basename(img) if img else "None")
        return scene_image_paths


    def _consistency_check_and_fix(self, video_path, code, sdef, quality, fmt,
                                    figure_analysis, method_images, max_fix_rounds=2):
        """对 MethodScene 做 Qwen-VL 一致性检查，不通过则让 opencode 修正。"""
        if not method_images:
            return video_path

        original_image = method_images[0]
        for round_idx in range(max_fix_rounds):
            # 从渲染视频提取帧
            frame_path = extract_frame_from_video(video_path)
            if not frame_path:
                logger.warning("无法提取渲染帧，跳过一致性检查")
                return video_path

            # Qwen-VL 对比
            check = check_consistency_with_vision_llm(original_image, frame_path)
            if not check:
                logger.warning("一致性检查调用失败，跳过")
                return video_path

            overall = check.get("overall_score", 0)
            passed = check.get("pass", overall >= 6)
            missing = check.get("missing_components", [])
            suggestions = check.get("suggestions", [])

            logger.info("一致性检查 (第 %d 轮): overall=%s, pass=%s, missing=%s",
                       round_idx + 1, overall, passed, missing)

            if passed:
                logger.info("MethodScene 通过一致性检查 (score=%s)", overall)
                return video_path

            # 不通过: 用反馈让 opencode 修正
            logger.warning("MethodScene 未通过一致性检查 (score=%s), 尝试修正...", overall)

            fix_prompt = (
                "你是 ManimCE 专家。以下 Manim 代码渲染后与论文原图不够一致，请修正。\n\n"
                "【一致性检查反馈】:\n"
                "- 总分: %s/10\n"
                "- 缺失组件: %s\n"
                "- 改进建议: %s\n\n"
                "【原始代码】:\n```python\n%s\n```\n\n"
                "请修正代码，补充缺失的组件，调整位置使其与原图更一致。\n"
                "仅输出完整修正后的 Python 代码。"
            ) % (overall, ", ".join(missing), "; ".join(suggestions), code)

            # 用 opencode 或直接 API 修正
            if figure_analysis:
                eb_elements = figure_analysis.get("eb_manim_elements", "")
                if eb_elements:
                    fix_prompt += "\n\n【图表精确规格（请参照）】:\n" + eb_elements

            raw = self._opencode_generate_with_retry(fix_prompt, attempts=2)

            fixed_code = (raw or "").strip()
            if fixed_code.startswith("```"):
                import re as _re
                fixed_code = _re.sub(r"^```\w*\n?", "", fixed_code)
                fixed_code = _re.sub(r"\n?```$", "", fixed_code)
                fixed_code = fixed_code.strip()

            if not fixed_code:
                logger.warning("修正代码为空，保留原版")
                return video_path

            fixed_code = self.inject_bounds_check(fixed_code)
            new_video = self.render_scene(fixed_code, sdef["scene_name"], quality=quality, fmt=fmt)
            if new_video:
                video_path = new_video
                code = fixed_code
                logger.info("修正后重新渲染成功: %s", new_video)
            else:
                logger.warning("修正后渲染失败，保留原版")
                return video_path

        return video_path

    def run(self, tts=False, quality="medium", fmt="mp4"):
        """完整流程：固定 4 场景 -> 生成代码 -> 渲染 -> 拼接。"""
        logger.info("=== Manim 演示生成开始 ===")

        # 1. Extract scripts from structured_plan
        sections = ["opening", "intro", "method", "results"]
        plan_scripts = {}
        for sec in sections:
            sec_data = self.structured_plan.get(sec, {})
            script = sec_data.get("script", sec_data) if isinstance(sec_data, dict) else sec_data
            plan_scripts[sec] = str(script) if script else ""

        # 2. Define fixed 4 scenes
        scene_defs = [
            {
                "scene_name": "TitleScene",
                "type": "title",
                "section": "opening",
                "description": f"论文标题和开场。脚本: {plan_scripts.get('opening', '')[:800]}",
            },
            {
                "scene_name": "IntroScene",
                "type": "flow",
                "section": "intro",
                "description": f"背景介绍和问题引出。脚本: {plan_scripts.get('intro', '')[:800]}",
            },
            {
                "scene_name": "MethodScene",
                "type": "architecture",
                "section": "method",
                "description": f"核心方法展示。脚本: {plan_scripts.get('method', '')[:800]}",
            },
            {
                "scene_name": "ResultsScene",
                "type": "results",
                "section": "results",
                "description": f"实验结果展示。脚本: {plan_scripts.get('results', '')[:800]}",
            },
        ]

        # 3. Narrations = plan scripts directly
        narrations = [plan_scripts.get(s["section"], "") for s in scene_defs]

        # 3.5 分析方法图（用于 MethodScene 增强）
        figure_analysis_result = None
        pipeline_images = self.load_pipeline_images()
        method_images = pipeline_images.get("method", [])
        if method_images:
            main_figure = method_images[0]
            logger.info("分析方法主图: %s", main_figure)
            try:
                paper_ctx = self.paper_text[:1500] if self.paper_text else ""
                figure_analysis_result = analyze_and_prepare(main_figure, paper_ctx)
                if figure_analysis_result and figure_analysis_result.get("analysis"):
                    logger.info("方法图分析成功: 类型=%s, %d 组件, %d 连接",
                               figure_analysis_result.get("figure_type", "?"),
                               len(figure_analysis_result["analysis"].get("components", [])),
                               len(figure_analysis_result["analysis"].get("connections", [])))
                else:
                    logger.warning("方法图分析返回空结果")
            except Exception as e:
                logger.warning("方法图分析失败，将使用默认生成: %s", e)

        # 4. Generate + render each scene
        scene_videos = []
        rendered_indices = []
        for i, sdef in enumerate(scene_defs):
            logger.info("生成场景 %d/4: %s (%s)", i + 1, sdef["scene_name"], sdef["type"])

            # MethodScene 注入图像分析结果
            if sdef["type"] == "architecture" and figure_analysis_result:
                sdef["figure_analysis"] = figure_analysis_result

            code = self.generate_manim_code(sdef)
            if not code:
                logger.warning("场景 %s 代码生成失败，跳过", sdef["scene_name"])
                continue
            # Inject bounds check
            code = self.inject_bounds_check(code)
            video_path = self.render_scene(code, sdef["scene_name"], quality=quality, fmt=fmt)
            if video_path:
                # MethodScene: Qwen-VL 一致性检查
                if sdef["type"] == "architecture" and figure_analysis_result:
                    video_path = self._consistency_check_and_fix(
                        video_path, code, sdef, quality, fmt,
                        figure_analysis_result, pipeline_images.get("method", [])
                    )
                scene_videos.append(video_path)
                rendered_indices.append(i)
            else:
                logger.warning("场景 %s 渲染失败，跳过", sdef["scene_name"])

        if not scene_videos:
            logger.error("所有场景渲染失败")
            return None

        # 5. TTS for rendered scenes
        audio_paths = []
        if tts:
            rendered_narrations = [narrations[i] for i in rendered_indices]
            self.generate_tts(scene_defs, rendered_narrations)
            audio_paths = getattr(self, "_audio_parts", [])

        # 6. Compose (pipeline_images already loaded in step 3.5)
        scene_image_paths = self._assign_images_to_scenes(
            pipeline_images, scene_defs, rendered_indices
        )

        output = self.compose(
            scene_videos,
            fmt=fmt,
            scene_image_paths=scene_image_paths,
            narration_audios=audio_paths,
        )

        if output:
            logger.info("=== Manim 演示生成完成: %s ===", output)
        return output
