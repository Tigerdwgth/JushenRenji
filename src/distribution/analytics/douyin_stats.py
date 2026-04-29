"""抖音创作者中心数据抓取(Playwright Xvfb headed).

跑在 paperagent venv, 通过 subprocess 调用 SAU venv 里的
``src.distribution.analytics.douyin_stats_helper``. 复用
``src/distribution/douyin.py`` 的 ``_ensure_xvfb_running()`` 工具.

公开 API:
    fetch_creator_stats(account_file=None, *, max_posts=20,
                        sau_dir=None, timeout=300) -> list[dict]

返回每条作品的统计:
    [
        {
            "post_id": "<aweme_id 或标题 hash>",
            "title": "...",
            "views": 播放,
            "likes": 点赞,
            "comments": 评论,
            "shares": 分享,
            "favorites": 收藏,
            "completion_rate": 完播率(%, float, 缺失补 0),
            "raw": 原始 XHR/DOM dict,
        },
        ...
    ]

策略:
    1. 优先在 ``creator-micro/data`` (作品分析页) 拦截 XHR JSON
       (``aweme/v1/creator/data/...`` 系列).
    2. 退一步: 直接读 "作品管理" 页 (``creator-micro/content/manage``)
       的 DOM 列表卡片 hover 数据.

帮助 helper 决定走哪一路通过 ``--mode auto|xhr|dom`` 控制, 默认 auto.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SAU_DIR = os.environ.get(
    "SAU_DIR",
    "/home/jdh/Projects/VlogCutter/third_party/social-auto-upload",
)
DEFAULT_ACCOUNT_FILE = os.environ.get(
    "DOUYIN_ACCOUNT_FILE",
    "/home/jdh/Projects/VlogCutter/JushenRenji/cache/douyin_cookies.json",
)
DEFAULT_TIMEOUT = int(os.environ.get("DOUYIN_STATS_TIMEOUT", "300"))


class DouyinStatsError(RuntimeError):
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


def fetch_creator_stats(
    account_file: Optional[str] = None,
    *,
    max_posts: int = 20,
    mode: str = "auto",
    sau_dir: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    """抓取抖音创作者中心数据, 返回最近 ``max_posts`` 条作品统计.

    Args:
        account_file: cookie storage_state JSON 路径, 缺省走 DEFAULT_ACCOUNT_FILE.
        max_posts: 最多抓多少条作品.
        mode: ``auto`` (默认, 先 XHR 再 DOM 兜底) / ``xhr`` / ``dom``.
        sau_dir: SAU 仓库根.
        timeout: 子进程整体超时(秒). Playwright + Xvfb 启动慢, 默认 300s.

    Returns:
        见模块 docstring. 失败时抛 DouyinStatsError.
    """
    sau_dir = sau_dir or DEFAULT_SAU_DIR
    account_file = account_file or DEFAULT_ACCOUNT_FILE

    if not os.path.isdir(sau_dir):
        raise DouyinStatsError(f"SAU 目录不存在: {sau_dir}")
    if not os.path.exists(account_file):
        raise DouyinStatsError(
            f"cookie 文件不存在: {account_file} "
            "(请在 macair 上跑 SAU 登录脚本)"
        )

    py = _resolve_sau_python(sau_dir)
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

    helper_args = [
        py, "-m", "src.distribution.analytics.douyin_stats_helper",
        "--account-file", os.path.abspath(account_file),
        "--max-posts", str(int(max_posts)),
        "--mode", mode,
        "--sau-dir", sau_dir,
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

    # Xvfb headed: 复用 douyin.py 的工具
    xvfb_display = os.environ.get("XVFB_DISPLAY", ":99")
    try:
        from src.distribution.douyin import _ensure_xvfb_running  # type: ignore
        if _ensure_xvfb_running(xvfb_display):
            env["DISPLAY"] = xvfb_display
            logger.info("[douyin_stats] DISPLAY=%s", xvfb_display)
    except Exception as exc:
        logger.warning("[douyin_stats] xvfb 启动失败, 继续 (可能 macOS): %s", exc)

    logger.info(
        "[douyin_stats] %s", " ".join(shlex.quote(a) for a in helper_args)
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
        raise DouyinStatsError(f"SAU helper 超时({timeout}s): {exc}") from exc
    except Exception as exc:
        raise DouyinStatsError(f"SAU helper 启动失败: {exc}") from exc

    if proc.stderr:
        for line in proc.stderr.strip().splitlines()[-20:]:
            logger.debug("[douyin_stats/sau] %s", line)

    payload = _parse_helper_output(proc.stdout)
    if payload is None:
        raise DouyinStatsError(
            f"helper stdout 无合法 JSON, rc={proc.returncode}, "
            f"raw={proc.stdout[-500:]!r}"
        )

    if not payload.get("ok"):
        raise DouyinStatsError(payload.get("error") or str(payload))

    items = payload.get("items")
    if not isinstance(items, list):
        raise DouyinStatsError(f"helper 返回 items 非 list: {type(items)}")
    return items
