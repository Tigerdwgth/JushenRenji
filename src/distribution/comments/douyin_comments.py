"""抖音评论拉取 + 回帖 (Playwright headed via Xvfb, SAU venv subprocess).

抖音 PC 创作者中心评论入口的 selector 易变, 此处采用基于关键词的 locator
(get_by_text) 兜底方案. 真实跑时通过 _ensure_xvfb_running 开 :99.
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

# 复用 douyin.py 的 Xvfb util
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
    comment_id: str           # text hash 兜底, 无真实 cid
    content: str
    nick: str
    ctime: int                # 0 表示未知
    aweme_url: str


class DouyinCommentsError(RuntimeError):
    pass


def _run_helper(args: list, timeout: int = DEFAULT_TIMEOUT,
                _runner=None) -> dict:
    sau_dir = os.environ.get("SAU_DIR", DEFAULT_SAU_DIR)
    py = _resolve_sau_python(sau_dir)
    repo_root = str(Path(__file__).resolve().parents[3])
    full_args = [py, "-m", "src.distribution.sau_helpers.douyin_comments_helper"] + args
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    xvfb_display = os.environ.get("XVFB_DISPLAY", ":99")
    if _ensure_xvfb_running(xvfb_display):
        env["DISPLAY"] = xvfb_display
    logger.info("[douyin_comments] run helper: %s",
                " ".join(shlex.quote(a) for a in full_args))
    runner = _runner or subprocess.run
    try:
        proc = runner(full_args, cwd=repo_root, env=env,
                      capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DouyinCommentsError(f"helper 超时: {exc}") from exc

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
            f"helper stdout 无 JSON, rc={proc.returncode}, "
            f"stderr_tail={(proc.stderr or '')[-300:]}"
        )
    return payload


def pull_recent_comments(aweme_url: str, since: datetime,
                         account_file: Optional[str] = None,
                         _runner=None) -> List[DouyinComment]:
    since_ts = int(since.timestamp()) if isinstance(since, datetime) else int(since)
    args = ["pull", "--aweme-url", aweme_url, "--since-ts", str(since_ts)]
    if account_file:
        args += ["--account-file", account_file]
    payload = _run_helper(args, _runner=_runner)
    if not payload.get("ok"):
        logger.error("[douyin_comments] pull 失败: %s", payload.get("error"))
        return []
    out: List[DouyinComment] = []
    for item in payload.get("data") or []:
        out.append(DouyinComment(
            comment_id=str(item.get("id", "")),
            content=item.get("content", ""),
            nick=item.get("nick", ""),
            ctime=int(item.get("ctime", 0)),
            aweme_url=aweme_url,
        ))
    return out


def reply_to_comment(aweme_url: str, parent_text: str, content: str,
                     account_file: Optional[str] = None,
                     _runner=None) -> bool:
    """抖音 PC 评论回复: helper 用 parent_text 文本定位评论行后点 "回复"."""
    args = ["reply", "--aweme-url", aweme_url,
            "--parent-text", parent_text,
            "--content", content]
    if account_file:
        args += ["--account-file", account_file]
    payload = _run_helper(args, _runner=_runner)
    return bool(payload.get("ok"))
