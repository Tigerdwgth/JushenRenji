"""小红书笔记统计抓取.

跑在 paperagent venv, 通过 subprocess 调用 SAU venv 里的
``src.distribution.analytics.xhs_stats_helper`` (xhs 库只在 SAU venv 装).

公开 API:
    fetch_note_stats(note_id, xsec_token, *, account_file=None,
                      sau_dir=None, timeout=60) -> dict

返回字段:
    {
        "views": 浏览量(view_count / impression_count, 取大者),
        "likes": 点赞(liked_count),
        "collects": 收藏(collected_count),
        "comments": 评论数(comment_count),
        "shares": 分享数(share_count),
        "raw": 原始 note dict,
    }

XHR 不返回的字段补 0. xhs 库不同版本字段名略有差异, 由 helper 兼容.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_SAU_DIR = os.environ.get(
    "SAU_DIR",
    "/home/jdh/Projects/VlogCutter/third_party/social-auto-upload",
)
DEFAULT_ACCOUNT_FILE = os.environ.get(
    "XHS_ACCOUNT_FILE",
    "/home/jdh/Projects/VlogCutter/JushenRenji/cache/xhs_cookies.json",
)
DEFAULT_TIMEOUT = int(os.environ.get("XHS_STATS_TIMEOUT", "60"))


class XhsStatsError(RuntimeError):
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


def _parse_helper_output(stdout: str) -> Optional[Dict[str, Any]]:
    """从 stdout 行序列中找最后一行合法 JSON."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def fetch_note_stats(
    note_id: str,
    xsec_token: str,
    *,
    account_file: Optional[str] = None,
    sau_dir: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """抓取单条小红书笔记统计.

    Args:
        note_id: 笔记 ID(URL 路径上的 hash, e.g. ``68f1234567890abcdef``).
        xsec_token: URL 上 ``xsec_token`` 参数 (xhs 接口风控必传).
        account_file: cookie 文件 (json), 缺省走 DEFAULT_ACCOUNT_FILE.
        sau_dir: SAU 仓库根. 用于定位 .venv/bin/python.
        timeout: 子进程整体超时(秒).

    Returns:
        见模块 docstring. 失败时抛 XhsStatsError.
    """
    if not note_id or not isinstance(note_id, str):
        raise ValueError(f"note_id 非法: {note_id!r}")
    if not xsec_token or not isinstance(xsec_token, str):
        raise ValueError(f"xsec_token 非法: {xsec_token!r}")

    sau_dir = sau_dir or DEFAULT_SAU_DIR
    account_file = account_file or DEFAULT_ACCOUNT_FILE

    if not os.path.isdir(sau_dir):
        raise XhsStatsError(f"SAU 目录不存在: {sau_dir}")

    py = _resolve_sau_python(sau_dir)
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

    helper_args = [
        py, "-m", "src.distribution.analytics.xhs_stats_helper",
        "--note-id", note_id,
        "--xsec-token", xsec_token,
        "--account-file", os.path.abspath(account_file),
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

    logger.info(
        "[xhs_stats] %s", " ".join(shlex.quote(a) for a in helper_args)
    )

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
        raise XhsStatsError(f"SAU helper 超时({timeout}s): {exc}") from exc
    except Exception as exc:
        raise XhsStatsError(f"SAU helper 启动失败: {exc}") from exc

    if proc.stderr:
        for line in proc.stderr.strip().splitlines()[-10:]:
            logger.debug("[xhs_stats/sau] %s", line)

    payload = _parse_helper_output(proc.stdout)
    if payload is None:
        raise XhsStatsError(
            f"helper stdout 无合法 JSON, rc={proc.returncode}, "
            f"raw={proc.stdout[-500:]!r}"
        )

    if not payload.get("ok"):
        raise XhsStatsError(payload.get("error") or str(payload))

    stats = payload.get("stats")
    if not isinstance(stats, dict):
        raise XhsStatsError(f"helper 返回 stats 非 dict: {type(stats)}")
    return stats
