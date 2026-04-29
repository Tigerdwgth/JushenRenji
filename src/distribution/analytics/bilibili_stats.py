"""B站视频统计数据抓取.

直接走 ``bilibili_api`` (官方协议封装), 不需要 Playwright. 走与
``src/distribution/bilibili.py`` 相同的 cookie 解析路径(config.yaml >
pkl 文件), 但只读视频统计字段, 不依赖登录态(可登录可不登录,
登录态下能拿到更多字段, 比如收藏夹数等).

公开 API:
    fetch_video_stats(bv_id, *, credential=None, timeout=30) -> dict

返回字段(全部 int, 缺失字段补 0):
    {
        "views": 播放量,
        "likes": 点赞,
        "coins": 投币,
        "favorites": 收藏,
        "shares": 分享,
        "comments": 评论数(reply),
        "danmaku": 弹幕数,
        "replies": 评论数别名(== comments, 兼容),
        "raw": 原始 stat dict (用于 raw_json 落库),
    }
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 字段映射: bilibili stat key -> 我们的标准 key
_STAT_FIELD_MAP = {
    "view": "views",
    "like": "likes",
    "coin": "coins",
    "favorite": "favorites",
    "share": "shares",
    "reply": "comments",
    "danmaku": "danmaku",
}


def _build_credential():
    """复用 ``src/distribution/bilibili.py`` 的 cookie 解析, 返回 ``Credential``.

    没 cookie 时返回 None, 仍可调 get_info(部分字段缺失). 不抛.
    """
    try:
        from bilibili_api import Credential  # type: ignore
    except Exception:
        logger.warning("bilibili_api 未安装, 无法构造 Credential")
        return None

    try:
        from src.distribution.bilibili import _resolve_cookies  # type: ignore
    except Exception:
        try:
            from distribution.bilibili import _resolve_cookies  # type: ignore
        except Exception:
            return None

    try:
        cookies = _resolve_cookies()
    except Exception as exc:
        logger.warning("解析 bilibili cookie 失败: %s", exc)
        return None

    if not cookies:
        return None

    return Credential(
        sessdata=cookies.get("SESSDATA") or cookies.get("sessdata"),
        bili_jct=cookies.get("bili_jct"),
        dedeuserid=cookies.get("DedeUserID") or cookies.get("dedeuserid"),
    )


def _normalize_stat(stat: Dict[str, Any]) -> Dict[str, Any]:
    """把 bilibili 原始 stat dict 映射成我们的标准字段."""
    out: Dict[str, Any] = {}
    for raw_key, std_key in _STAT_FIELD_MAP.items():
        try:
            out[std_key] = int(stat.get(raw_key, 0) or 0)
        except (TypeError, ValueError):
            out[std_key] = 0
    # comments / replies 同义
    out["replies"] = out.get("comments", 0)
    return out


async def _fetch_async(bv_id: str, credential=None) -> Dict[str, Any]:
    from bilibili_api import video as bv_module  # type: ignore

    v = bv_module.Video(bvid=bv_id, credential=credential)
    info = await v.get_info()
    if not isinstance(info, dict):
        raise RuntimeError(f"get_info 返回非 dict: {type(info)}")
    stat = info.get("stat") or {}
    if not isinstance(stat, dict):
        raise RuntimeError(f"info.stat 非 dict: {type(stat)}")
    return stat


def fetch_video_stats(
    bv_id: str,
    *,
    credential=None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """同步包装. 在已有 event loop 时(jupyter)请改用 async 版本.

    Args:
        bv_id: BV 号(以 BV 开头).
        credential: 可选的 ``bilibili_api.Credential``, 不传则从 config 读.
        timeout: 抓取超时(秒).

    Returns:
        见模块 docstring. 失败时抛 RuntimeError, 调用方需 try.
    """
    if not bv_id or not isinstance(bv_id, str):
        raise ValueError(f"bv_id 非法: {bv_id!r}")
    if not bv_id.startswith("BV"):
        # 容忍带空白
        bv_id = bv_id.strip()
        if not bv_id.startswith("BV"):
            raise ValueError(f"bv_id 必须以 BV 开头: {bv_id!r}")

    if credential is None:
        credential = _build_credential()

    async def _runner():
        return await asyncio.wait_for(
            _fetch_async(bv_id, credential=credential), timeout=timeout
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 罕见: 测试环境一般不会触发, 但避免 nested run 崩
            raise RuntimeError(
                "fetch_video_stats 在 running loop 中被调用; "
                "请改用 await _fetch_async(...) 或 nest_asyncio"
            )
    except RuntimeError as exc:
        if "no current event loop" not in str(exc) and "no running" not in str(exc):
            # 其他类型 RuntimeError 透传
            if "running loop" in str(exc):
                raise
        # 没有 loop 是预期, 走 asyncio.run
        loop = None

    stat = asyncio.run(_runner())
    out = _normalize_stat(stat)
    out["raw"] = stat
    return out
