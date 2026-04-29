"""抖音创作者数据抓取 (基于 f2 SDK).

替代原本的 Playwright + SAU 子进程方案. 直接走 f2 douyin web API,
速度从 60s+ 降到 1-3s, 也不再依赖 Xvfb/headed Chromium.

公开 API (保持原签名兼容):
    fetch_creator_stats(account_file=None, *, max_posts=20, ...) -> list[dict]
        拉自己最近 N 条作品的统计.

新增:
    fetch_note_stats(aweme_id, *, account_file=None) -> dict
        单视频最新统计 (与 xhs_stats / bilibili_stats 风格统一).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.distribution import f2_client
from src.distribution.f2_client import F2CookieError

logger = logging.getLogger(__name__)

# 兼容旧调用: 老代码 ``from src.distribution.analytics.douyin_stats import
# DEFAULT_ACCOUNT_FILE`` 仍然能用.
DEFAULT_ACCOUNT_FILE = f2_client.DEFAULT_ACCOUNT_FILE


class DouyinStatsError(RuntimeError):
    pass


def _aweme_to_stats_item(aweme: Dict[str, Any]) -> Dict[str, Any]:
    """f2_client.fetch_user_videos 的项 → analytics 标准字段."""
    return {
        "post_id": str(aweme.get("aweme_id") or ""),
        "title": aweme.get("desc") or "",
        "views": int(aweme.get("play_count") or 0),
        "likes": int(aweme.get("digg_count") or 0),
        "comments": int(aweme.get("comment_count") or 0),
        "shares": int(aweme.get("share_count") or 0),
        "favorites": int(aweme.get("collect_count") or 0),
        # f2 web API 不返回完播率 (这是创作者中心独有指标), 留 0.
        "completion_rate": 0.0,
        "raw": aweme.get("raw") or {},
    }


def fetch_creator_stats(
    account_file: Optional[str] = None,
    *,
    max_posts: int = 20,
    sec_user_id: Optional[str] = None,
    # 兼容老 API 的占位参数 (helper / mode / sau_dir / timeout 现已无意义)
    mode: Optional[str] = None,
    sau_dir: Optional[str] = None,
    timeout: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """抓取抖音创作者最近 ``max_posts`` 条作品统计.

    Args:
        account_file: storage_state JSON 路径, 缺省读 DEFAULT_ACCOUNT_FILE.
        max_posts: 最多抓多少条.
        sec_user_id: 显式指定 sec_uid (默认读当前 cookie 对应账号).
        mode/sau_dir/timeout: 兼容老接口, 现已无作用.

    Returns:
        list[dict] 字段: post_id / title / views / likes / comments /
        shares / favorites / completion_rate / raw.

    Raises:
        DouyinStatsError: cookie 失效 / 接口报错 / 抓不到任何作品.
    """
    if mode is not None:
        logger.debug("[douyin_stats] mode=%s 在 f2 路径下已忽略", mode)
    if sau_dir is not None:
        logger.debug("[douyin_stats] sau_dir 已不再使用 (f2 路径)")

    try:
        videos = f2_client.fetch_user_videos(
            sec_user_id=sec_user_id,
            limit=max_posts,
            account_file=account_file,
        )
    except F2CookieError as exc:
        raise DouyinStatsError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise DouyinStatsError(f"f2 抓取失败: {exc}") from exc

    items = [_aweme_to_stats_item(v) for v in videos]
    items = [it for it in items if it["post_id"]]
    if not items:
        raise DouyinStatsError(
            "未抓到任何作品 (可能 cookie 过期或账号无作品)"
        )
    return items[:max_posts]


def fetch_note_stats(
    post_id: str,
    *,
    account_file: Optional[str] = None,
) -> Dict[str, Any]:
    """单视频最新统计.

    Args:
        post_id: aweme_id 字符串, 也可以传 douyin web URL (内部用 f2
                 AwemeIdFetcher 解析).
        account_file: storage_state JSON.

    Returns:
        dict: post_id / title / views / likes / comments / shares /
              favorites / completion_rate / raw.

    Raises:
        DouyinStatsError: cookie 失效 / 接口报错 / aweme_id 解析失败.
    """
    if not post_id:
        raise DouyinStatsError("post_id 不能为空")
    try:
        v = f2_client.fetch_video_stats(post_id, account_file=account_file)
    except F2CookieError as exc:
        raise DouyinStatsError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise DouyinStatsError(f"f2 抓取失败: {exc}") from exc
    return {
        "post_id": str(v.get("aweme_id") or post_id),
        "title": v.get("desc") or "",
        "views": int(v.get("play_count") or 0),
        "likes": int(v.get("digg_count") or 0),
        "comments": int(v.get("comment_count") or 0),
        "shares": int(v.get("share_count") or 0),
        "favorites": int(v.get("collect_count") or 0),
        "completion_rate": 0.0,
        "raw": v.get("raw") or {},
    }


__all__ = [
    "DouyinStatsError",
    "fetch_creator_stats",
    "fetch_note_stats",
    "DEFAULT_ACCOUNT_FILE",
]
