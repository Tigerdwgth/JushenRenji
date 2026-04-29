"""抖音上传适配器。

跑在 paperagent venv, 通过 subprocess 调用 SAU venv 里的
src.distribution.sau_helpers.upload_douyin 完成实际上传。

依赖:
- 抖音 cookie: 默认 ~/Projects/VlogCutter/JushenRenji/cache/douyin_cookies.json
  (首次需要在 macair 上跑 SAU 的 headed login script 扫码登录)
- SAU venv: 默认 ~/Projects/VlogCutter/third_party/social-auto-upload/.venv
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Union

logger = logging.getLogger(__name__)

DEFAULT_SAU_DIR = os.environ.get(
    "SAU_DIR",
    "/home/jdh/Projects/VlogCutter/third_party/social-auto-upload",
)
DEFAULT_ACCOUNT_FILE = os.environ.get(
    "DOUYIN_ACCOUNT_FILE",
    "/home/jdh/Projects/VlogCutter/JushenRenji/cache/douyin_cookies.json",
)
# 单个上传超时: 大视频 + 风控等待 + scheduled 流程, 默认 15 分钟
DEFAULT_TIMEOUT = int(os.environ.get("DOUYIN_UPLOAD_TIMEOUT", "900"))


class DouyinUploadError(RuntimeError):
    pass


def _normalize_tags(tags: Union[str, Sequence[str], None]) -> str:
    """把 list/str/None 统一成 helper 期望的逗号分隔字符串。"""
    if tags is None:
        return ""
    if isinstance(tags, str):
        return tags
    return ",".join(str(t).strip() for t in tags if str(t).strip())


def _resolve_sau_python(sau_dir: str) -> str:
    """优先用 SAU 项目下的 venv python, 退回到系统 python3。"""
    candidates = [
        os.path.join(sau_dir, ".venv/bin/python"),
        os.path.join(sau_dir, ".venv/bin/python3"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "python3"


def _ensure_xvfb_running(display: str = ":99") -> bool:
    """确保 Xvfb 虚拟显示器在跑(仅 Linux + 找得到 Xvfb 时启用)."""
    import platform, shutil, time
    if platform.system() != "Linux":
        return False
    if not shutil.which("Xvfb"):
        return False
    rc = subprocess.run(["pgrep", "-f", f"Xvfb {display}"],
                         capture_output=True)
    if rc.returncode == 0:
        return True
    logger.info("[douyin] 启动 Xvfb 虚拟显示器: %s", display)
    subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1920x1080x24", "-ac",
         "+extension", "RANDR"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    return True


def upload(
    video_path: str,
    title: str,
    tags: Union[str, Sequence[str], None] = None,
    cover_path: Optional[str] = None,
    desc: Optional[str] = None,
    account_file: Optional[str] = None,
    sau_dir: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[str]:
    """上传单条视频到抖音。

    Args:
        video_path: 本地 mp4 路径
        title: 视频标题 (抖音上限 30 字符, 内部不裁剪, 由调用方控制)
        tags: 关键词, 可传 list[str] 或逗号分隔 str. None 即不打标签.
        cover_path: 封面 (横竖共用同一张, 可选)
        desc: 描述文字 (抖音 PC 创作者中心目前没有独立 desc 字段, 留作未来扩展; 此版本忽略)
        account_file: cookie storage_state JSON 路径, 默认 DEFAULT_ACCOUNT_FILE
        sau_dir: social-auto-upload 仓库根, 默认 DEFAULT_SAU_DIR
        timeout: 子进程整体超时(秒)

    Returns:
        "douyin" (str) 表示成功, None 表示失败. 抖音 PC 不暴露 aweme_id, 故返回固定占位.

    Raises:
        DouyinUploadError: 子进程异常退出且 stdout 没有合法 JSON 时.
    """
    sau_dir = sau_dir or DEFAULT_SAU_DIR
    account_file = account_file or DEFAULT_ACCOUNT_FILE

    if not os.path.exists(video_path):
        logger.error("[douyin] 视频文件不存在: %s", video_path)
        return None
    if not os.path.exists(account_file):
        logger.error("[douyin] cookie 文件不存在: %s "
                     "(请在 macair 上跑 SAU 登录脚本)", account_file)
        return None
    if not os.path.isdir(sau_dir):
        logger.error("[douyin] SAU 目录不存在: %s", sau_dir)
        return None

    py = _resolve_sau_python(sau_dir)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))  # JushenRenji 根目录
    helper_args = [
        py, "-m", "src.distribution.sau_helpers.upload_douyin",
        "--video", os.path.abspath(video_path),
        "--title", title,
        "--tags", _normalize_tags(tags),
        "--account-file", os.path.abspath(account_file),
        "--immediate",
        "--sau-dir", sau_dir,
    ]
    if cover_path and os.path.exists(cover_path):
        helper_args += ["--thumb", os.path.abspath(cover_path)]

    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    # Xvfb headed 模式: 抖音对 headless 风控很严, 走虚拟显示器更稳
    xvfb_display = os.environ.get("XVFB_DISPLAY", ":99")
    if _ensure_xvfb_running(xvfb_display):
        env["DISPLAY"] = xvfb_display
        logger.info("[douyin] subprocess 使用 DISPLAY=%s", xvfb_display)

    logger.info("[douyin] 调用 SAU helper: %s",
                " ".join(shlex.quote(a) for a in helper_args))
    try:
        proc = subprocess.run(
            helper_args,
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("[douyin] 子进程超时(%ds): %s", timeout, exc)
        return None
    except Exception as exc:
        logger.exception("[douyin] 子进程启动失败")
        raise DouyinUploadError(f"SAU helper 启动失败: {exc}") from exc

    if proc.stderr:
        # SAU 的 logging 会写到 stderr, 转发到我们的 logger 方便排查
        for line in proc.stderr.strip().splitlines()[-30:]:
            logger.info("[douyin/sau] %s", line)

    raw = proc.stdout.strip().splitlines()
    payload: Optional[dict] = None
    for line in reversed(raw):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue

    if payload is None:
        logger.error("[douyin] helper stdout 无合法 JSON, rc=%d, raw=%r",
                     proc.returncode, proc.stdout[-500:])
        return None

    if payload.get("ok"):
        return payload.get("id") or "douyin"

    logger.error("[douyin] 上传失败: %s", payload.get("error") or payload)
    return None
