"""小红书评论拉取 + 回帖 (cross-env subprocess via SAU venv).

调用 src.distribution.sau_helpers.xhs_comments_helper 在 SAU venv 内执行
xhs.XhsClient.get_note_all_comments / comment_user.

stdout 单行 JSON 契约同 upload_douyin.py: {"ok": bool, "data": ..., "error": ...}.
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

logger = logging.getLogger(__name__)

DEFAULT_SAU_DIR = os.environ.get(
    "SAU_DIR",
    "/home/jdh/Projects/VlogCutter/third_party/social-auto-upload",
)
DEFAULT_TIMEOUT = int(os.environ.get("XHS_COMMENTS_TIMEOUT", "180"))


@dataclass
class XhsComment:
    comment_id: str
    parent_id: Optional[str]
    content: str
    nick: str
    ctime: int   # 秒级 unix ts
    note_id: str


class XhsCommentsError(RuntimeError):
    pass


def _resolve_sau_python(sau_dir: str) -> str:
    candidates = [
        os.path.join(sau_dir, ".venv/bin/python"),
        os.path.join(sau_dir, ".venv/bin/python3"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "python3"


def _run_helper(args: list, timeout: int = DEFAULT_TIMEOUT,
                _runner=None) -> dict:
    sau_dir = os.environ.get("SAU_DIR", DEFAULT_SAU_DIR)
    py = _resolve_sau_python(sau_dir)
    repo_root = str(Path(__file__).resolve().parents[3])
    full_args = [py, "-m", "src.distribution.sau_helpers.xhs_comments_helper"] + args
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    logger.info("[xhs_comments] run helper: %s",
                " ".join(shlex.quote(a) for a in full_args))
    runner = _runner or subprocess.run
    try:
        proc = runner(full_args, cwd=repo_root, env=env,
                      capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise XhsCommentsError(f"helper 超时: {exc}") from exc

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
        raise XhsCommentsError(
            f"helper stdout 无 JSON, rc={proc.returncode}, "
            f"stderr_tail={(proc.stderr or '')[-300:]}"
        )
    return payload


def pull_recent_comments(note_id: str, xsec_token: str,
                         since: datetime,
                         _runner=None) -> List[XhsComment]:
    """拉 since 之后的评论."""
    since_ts = int(since.timestamp()) if isinstance(since, datetime) else int(since)
    payload = _run_helper(
        ["pull", "--note-id", note_id, "--xsec-token", xsec_token,
         "--since-ts", str(since_ts)],
        _runner=_runner,
    )
    if not payload.get("ok"):
        logger.error("[xhs_comments] pull 失败: %s", payload.get("error"))
        return []
    out: List[XhsComment] = []
    for item in payload.get("data") or []:
        out.append(XhsComment(
            comment_id=str(item.get("id", "")),
            parent_id=item.get("parent_id"),
            content=item.get("content", ""),
            nick=item.get("nick", ""),
            ctime=int(item.get("ctime", 0)),
            note_id=note_id,
        ))
    return out


def reply_to_comment(note_id: str, comment_id: str, content: str,
                     _runner=None) -> bool:
    payload = _run_helper(
        ["reply", "--note-id", note_id, "--comment-id", comment_id,
         "--content", content],
        _runner=_runner,
    )
    return bool(payload.get("ok"))
