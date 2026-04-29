"""抖音评论拉取 (f2 SDK) + 回复 (SAU 子进程).

读路径 (拉评论) 走 f2 web API: 直接用 cookie 调
``aweme/v1/web/comment/list/``, 速度从 30s+ 降到 1s 内.

写路径 (回复评论) 暂时仍走 SAU 子进程, 因为:
    - 抖音 web ``comment/publish`` 接口对鉴权 (a_bogus / msToken / verifyFp)
      要求严格, f2 当前未提供写封装; 直接 POST 容易被风控
    - 评论回复频次极低 (每天 < 20 条), 用 SAU headed 走得通
后续 task B (chromium daemon / SAU CDP 改造) 会重写这条路径.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.distribution import f2_client
from src.distribution.f2_client import F2CookieError

# 复用 douyin.py 的 Xvfb util / SAU venv 解析 (仅 reply 路径还需要)
try:
    from src.distribution.douyin import (
        _ensure_xvfb_running,
        _resolve_sau_python,
        DEFAULT_SAU_DIR,
        DEFAULT_ACCOUNT_FILE,
    )
except ImportError:  # pragma: no cover
    from distribution.douyin import (  # type: ignore
        _ensure_xvfb_running,
        _resolve_sau_python,
        DEFAULT_SAU_DIR,
        DEFAULT_ACCOUNT_FILE,
    )

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = int(os.environ.get("DOUYIN_COMMENTS_TIMEOUT", "300"))


@dataclass
class DouyinComment:
    comment_id: str           # f2 真实 cid
    content: str
    nick: str
    ctime: int                # 评论 create_time, 单位秒
    aweme_url: str


class DouyinCommentsError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Pull (f2 read path)
# --------------------------------------------------------------------------- #

def pull_recent_comments(
    aweme_url: str,
    since: datetime,
    account_file: Optional[str] = None,
    limit: int = 200,
    _runner=None,  # 兼容旧测试签名, 在 f2 路径下被忽略
) -> List[DouyinComment]:
    """拉单视频的评论, 过滤 ``ctime >= since`` 的.

    Args:
        aweme_url: 抖音视频链接 (https://www.douyin.com/video/<id>) 或纯 aweme_id.
        since: 只保留这个时间点之后的评论 (datetime / int unix-ts).
        account_file: storage_state cookie JSON.
        limit: 单次最多拉取多少条 (在 since 过滤前).

    Returns:
        list[DouyinComment].
    """
    since_ts = int(since.timestamp()) if isinstance(since, datetime) else int(since)
    try:
        items = f2_client.fetch_comments(
            aweme_url, limit=limit, account_file=account_file,
        )
    except F2CookieError as exc:
        logger.error("[douyin_comments] cookie 失效: %s", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("[douyin_comments] f2 拉评论失败 url=%s: %s",
                     aweme_url, exc)
        return []

    out: List[DouyinComment] = []
    for it in items:
        ctime = int(it.get("create_time") or 0)
        if since_ts > 0 and ctime > 0 and ctime < since_ts:
            continue
        out.append(DouyinComment(
            comment_id=str(it.get("cid") or ""),
            content=it.get("text") or "",
            nick=it.get("nickname") or "",
            ctime=ctime,
            aweme_url=aweme_url,
        ))
    return out


# --------------------------------------------------------------------------- #
# Reply (SAU subprocess write path) — 留待 task B (CDP daemon) 改造
# --------------------------------------------------------------------------- #

def _run_reply_helper(args: list, timeout: int = DEFAULT_TIMEOUT,
                      _runner=None) -> dict:
    """仅用于 reply 子命令: 调 SAU venv headed 浏览器写评论."""
    sau_dir = os.environ.get("SAU_DIR", DEFAULT_SAU_DIR)
    py = _resolve_sau_python(sau_dir)
    repo_root = str(Path(__file__).resolve().parents[3])
    full_args = [py, "-m", "src.distribution.sau_helpers.douyin_comments_helper"] + args
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    xvfb_display = os.environ.get("XVFB_DISPLAY", ":99")
    if _ensure_xvfb_running(xvfb_display):
        env["DISPLAY"] = xvfb_display
    logger.info("[douyin_comments] run reply helper: %s",
                " ".join(shlex.quote(a) for a in full_args))
    runner = _runner or subprocess.run
    try:
        proc = runner(full_args, cwd=repo_root, env=env,
                      capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DouyinCommentsError(f"reply helper 超时: {exc}") from exc

    raw_lines = (proc.stdout or "").strip().splitlines()
    payload = None
    for line in reversed(raw_lines):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if payload is None:
        raise DouyinCommentsError(
            f"reply helper stdout 无 JSON, rc={proc.returncode}, "
            f"stderr_tail={(proc.stderr or '')[-300:]}"
        )
    return payload


def reply_to_comment(aweme_url: str, parent_text: str, content: str,
                     account_file: Optional[str] = None,
                     _runner=None) -> bool:
    """抖音 PC 评论回复: helper 用 parent_text 文本定位评论行后点 "回复".

    NOTE: 写路径 f2 暂未支持, 仍走 SAU CDP. 见 task B 计划.
    """
    args = ["reply", "--aweme-url", aweme_url,
            "--parent-text", parent_text,
            "--content", content]
    if account_file:
        args += ["--account-file", account_file]
    payload = _run_reply_helper(args, _runner=_runner)
    return bool(payload.get("ok"))
