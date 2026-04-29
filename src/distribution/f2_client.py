"""抖音 f2 客户端封装 (paperagent venv).

替代原本基于 Playwright + SAU venv 的拉取/统计实现, 仅做读路径:
    - fetch_user_videos: 拉自己最近作品 (含 statistics)
    - fetch_video_stats: 拉单个视频的最新统计
    - fetch_comments:    拉单视频评论列表

写路径 (评论回复 / 视频上传) 不在此模块, 仍走 SAU 子进程
(见 ``src/distribution/sau_helpers/douyin_comments_helper.py``).

Cookie 处理:
    项目里的 ``cache/douyin_cookies.json`` 是 Playwright ``storage_state``
    格式, f2 需要 ``name=value; ...`` 拼接字符串. 本模块自动转换,
    取 ``.douyin.com`` / ``creator.douyin.com`` / ``.tiktokv.com`` 域下的
    cookie. cookie 缺失/失效抛 ``F2CookieError``, 调用方处理.

并发模型:
    f2 全异步, 这里所有 public API 同步包装. 上层 (analytics/comments cli)
    本身就是同步流水线, 不需要再开事件循环.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


DEFAULT_ACCOUNT_FILE = os.environ.get(
    "DOUYIN_ACCOUNT_FILE",
    str(Path(__file__).resolve().parents[2] / "cache" / "douyin_cookies.json"),
)

# 默认 UA / Referer (f2 内部也读 conf.yaml, 这里显式塞一份兜底)
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
    ),
    "Referer": "https://www.douyin.com/",
}

_DOUYIN_COOKIE_DOMAINS = (
    ".douyin.com",
    "douyin.com",
    "creator.douyin.com",
    ".bytedance.com",
    "bytedance.com",
    ".tiktokv.com",
)

_AWEME_URL_PATTERNS = (
    re.compile(r"/video/(\d+)"),
    re.compile(r"/note/(\d+)"),
    re.compile(r"modal_id=(\d+)"),
)


class F2CookieError(RuntimeError):
    """cookie 文件缺失 / 解析失败 / 关键 cookie 未找到."""


# --------------------------------------------------------------------------- #
# Cookie 转换
# --------------------------------------------------------------------------- #

def _format_cookie_string(cookies: Iterable[Dict[str, Any]]) -> str:
    """从 Playwright storage_state.cookies 列表生成 ``name=value; ...`` 字符串.

    只保留 douyin / bytedance / tiktokv 域下的 cookie. 同名 cookie 多次出现
    时取最后一个 (与浏览器行为一致, 便于 SAU 写入后覆盖).
    """
    pairs: Dict[str, str] = {}
    for c in cookies:
        domain = (c.get("domain") or "").lower()
        if not any(domain.endswith(d) or domain == d.lstrip(".")
                   for d in _DOUYIN_COOKIE_DOMAINS):
            continue
        name = c.get("name")
        value = c.get("value")
        if not name or value is None:
            continue
        pairs[name] = str(value)
    if not pairs:
        return ""
    return "; ".join(f"{k}={v}" for k, v in pairs.items())


def load_cookie_string(account_file: Optional[str] = None) -> str:
    """读 storage_state JSON 并转成 cookie 字符串.

    Raises:
        F2CookieError: 文件不存在 / JSON 损坏 / 没有 douyin 域 cookie
                       / 缺关键 cookie (sessionid 之一).
    """
    path = Path(account_file or DEFAULT_ACCOUNT_FILE).expanduser()
    if not path.exists():
        raise F2CookieError(f"cookie 文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise F2CookieError(f"cookie 文件解析失败: {path} ({exc})") from exc

    cookies = data.get("cookies") if isinstance(data, dict) else None
    if not isinstance(cookies, list):
        raise F2CookieError(
            f"cookie 文件缺少 cookies 数组(非 storage_state 格式): {path}"
        )
    s = _format_cookie_string(cookies)
    if not s:
        raise F2CookieError(f"cookie 文件中未找到 douyin 域 cookie: {path}")
    # 抖音 web 鉴权关键: sessionid / sessionid_ss / sid_tt 至少一个
    if not re.search(r"\b(sessionid|sessionid_ss|sid_tt)=", s):
        raise F2CookieError(
            f"cookie 缺少 sessionid* / sid_tt (登录态可能已过期): {path}"
        )
    return s


# --------------------------------------------------------------------------- #
# Handler / Crawler kwargs
# --------------------------------------------------------------------------- #

def _build_handler_kwargs(account_file: Optional[str] = None) -> Dict[str, Any]:
    cookie = load_cookie_string(account_file)
    return {
        "cookie": cookie,
        "headers": dict(_DEFAULT_HEADERS),
        "proxies": {"http://": None, "https://": None},
        "timeout": int(os.environ.get("F2_TIMEOUT", "10")),
        "max_retries": int(os.environ.get("F2_MAX_RETRIES", "3")),
        "max_connections": 5,
        "max_tasks": 5,
        "page_counts": 20,
    }


# --------------------------------------------------------------------------- #
# 工具: aweme_id / sec_user_id 解析
# --------------------------------------------------------------------------- #

def _looks_like_id(s: str) -> bool:
    return bool(s) and s.isdigit() and len(s) >= 10


def _try_extract_aweme_id_from_url(url: str) -> Optional[str]:
    for pat in _AWEME_URL_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


async def _resolve_aweme_id_async(aweme_id_or_url: str) -> str:
    """接受纯数字 aweme_id, 也接受抖音 web / v.douyin.com 短链."""
    s = (aweme_id_or_url or "").strip()
    if not s:
        raise ValueError("aweme_id 不能为空")
    if _looks_like_id(s):
        return s
    direct = _try_extract_aweme_id_from_url(s)
    if direct:
        return direct
    # 短链 / 包含跳转 → 走 f2 AwemeIdFetcher 拿真实 id
    from f2.apps.douyin.utils import AwemeIdFetcher  # type: ignore
    return await AwemeIdFetcher.get_aweme_id(s)


async def _resolve_sec_user_id_async(handler, sec_user_or_url: Optional[str]) -> str:
    """sec_user_id 可以传纯 sec_uid, 也可以传主页 URL.

    None 时通过 ``query_user`` 拿当前登录账号. f2 提供
    ``DouyinHandler.fetch_query_user()``, 但这要求 cookie 完整.
    """
    if sec_user_or_url:
        s = sec_user_or_url.strip()
        if "://" in s or "douyin.com" in s:
            from f2.apps.douyin.utils import SecUserIdFetcher  # type: ignore
            return await SecUserIdFetcher.get_sec_user_id(s)
        return s
    # 取登录账号自身
    user = await handler.fetch_query_user()
    sec_uid = getattr(user, "sec_uid", None) or getattr(user, "sec_user_id", None)
    if not sec_uid:
        raise F2CookieError(
            "无法从当前 cookie 解析 sec_user_id, 可能登录态失效"
        )
    return sec_uid


# --------------------------------------------------------------------------- #
# Async impl (内部)
# --------------------------------------------------------------------------- #

def _stats_from_aweme(aweme: Dict[str, Any]) -> Dict[str, int]:
    """抖音 aweme 单条 raw dict → 标准 stats 字段."""
    stats = aweme.get("statistics") or {}
    if not isinstance(stats, dict):
        stats = {}
    return {
        "play_count": int(stats.get("play_count") or 0),
        "digg_count": int(stats.get("digg_count") or 0),
        "comment_count": int(stats.get("comment_count") or 0),
        "share_count": int(stats.get("share_count") or 0),
        "collect_count": int(stats.get("collect_count") or 0),
    }


async def _fetch_user_videos_async(
    sec_user_id: Optional[str],
    limit: int,
    account_file: Optional[str],
) -> List[Dict[str, Any]]:
    from f2.apps.douyin.handler import DouyinHandler  # type: ignore

    kwargs = _build_handler_kwargs(account_file)
    handler = DouyinHandler(kwargs)
    sec_uid = await _resolve_sec_user_id_async(handler, sec_user_id)

    out: List[Dict[str, Any]] = []
    page_counts = min(20, max(limit, 1))
    async for page in handler.fetch_user_post_videos(
        sec_user_id=sec_uid,
        min_cursor=0,
        max_cursor=0,
        page_counts=page_counts,
        max_counts=limit,
    ):
        raw = page._to_raw() or {}
        for aweme in raw.get("aweme_list", []) or []:
            stats = _stats_from_aweme(aweme)
            out.append({
                "aweme_id": str(aweme.get("aweme_id") or ""),
                "desc": aweme.get("desc") or "",
                "create_time": int(aweme.get("create_time") or 0),
                **stats,
                "raw": aweme,
            })
            if len(out) >= limit:
                return out
    return out


async def _fetch_video_stats_async(
    aweme_id_or_url: str,
    account_file: Optional[str],
) -> Dict[str, Any]:
    from f2.apps.douyin.handler import DouyinHandler  # type: ignore

    kwargs = _build_handler_kwargs(account_file)
    handler = DouyinHandler(kwargs)
    aweme_id = await _resolve_aweme_id_async(aweme_id_or_url)
    video = await handler.fetch_one_video(aweme_id=aweme_id)
    raw = video._to_raw() or {}
    detail = raw.get("aweme_detail") or {}
    stats = detail.get("statistics") or {}
    # PostDetailFilter 注释里说不从此接口取 play_count, 但 raw JSON 里通常有
    # (比如有的版本字段名是 ``play_count`` / 有的是 0). 直接读 raw, 缺失补 0.
    return {
        "aweme_id": str(detail.get("aweme_id") or aweme_id),
        "desc": detail.get("desc") or "",
        "create_time": int(detail.get("create_time") or 0),
        "play_count": int(stats.get("play_count") or 0),
        "digg_count": int(stats.get("digg_count") or 0),
        "comment_count": int(stats.get("comment_count") or 0),
        "share_count": int(stats.get("share_count") or 0),
        "collect_count": int(stats.get("collect_count") or 0),
        "raw": detail,
    }


async def _fetch_comments_async(
    aweme_id_or_url: str,
    limit: int,
    account_file: Optional[str],
) -> List[Dict[str, Any]]:
    from f2.apps.douyin.crawler import DouyinCrawler  # type: ignore
    from f2.apps.douyin.model import PostComment  # type: ignore

    kwargs = _build_handler_kwargs(account_file)
    aweme_id = await _resolve_aweme_id_async(aweme_id_or_url)

    out: List[Dict[str, Any]] = []
    cursor = 0
    page_size = 20
    seen_cids: set = set()

    async with DouyinCrawler(kwargs) as crawler:
        while len(out) < limit:
            params = PostComment(
                aweme_id=aweme_id,
                cursor=cursor,
                count=page_size,
                item_type=0,
                insert_ids="",
                whale_cut_token="",
                cut_version=1,
                rcFT="",
            )
            try:
                payload = await crawler.fetch_post_comment(params)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[f2_client] fetch_post_comment 失败 cursor=%s: %s",
                    cursor, exc,
                )
                break
            if not isinstance(payload, dict):
                break
            comments = payload.get("comments") or []
            if not comments:
                break
            for c in comments:
                if not isinstance(c, dict):
                    continue
                cid = str(c.get("cid") or "")
                if not cid or cid in seen_cids:
                    continue
                seen_cids.add(cid)
                user = c.get("user") or {}
                out.append({
                    "cid": cid,
                    "text": c.get("text") or "",
                    "nickname": user.get("nickname") or "",
                    "user_id": str(user.get("uid") or user.get("sec_uid") or ""),
                    "create_time": int(c.get("create_time") or 0),
                    "digg_count": int(c.get("digg_count") or 0),
                    "reply_comment_total": int(
                        c.get("reply_comment_total") or 0
                    ),
                    "raw": c,
                })
                if len(out) >= limit:
                    break
            has_more = bool(payload.get("has_more"))
            next_cursor = payload.get("cursor")
            if next_cursor in (None, cursor):
                break
            if not has_more:
                break
            cursor = int(next_cursor)
    return out


# --------------------------------------------------------------------------- #
# 同步包装 (public API)
# --------------------------------------------------------------------------- #

def _run_sync(coro):
    """同步运行协程. 不在事件循环内, 否则报错让上层处理."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "f2_client 不能在已运行的 asyncio 事件循环里调用; "
        "请改用 _fetch_*_async 协程"
    )


def fetch_user_videos(
    sec_user_id: Optional[str] = None,
    limit: int = 20,
    *,
    account_file: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """拉自己 (或指定 sec_user_id) 最近 ``limit`` 条作品.

    Returns:
        list[dict], 每项包含: aweme_id / desc / create_time /
        play_count / digg_count / comment_count / share_count /
        collect_count / raw.
    """
    if limit <= 0:
        return []
    return _run_sync(_fetch_user_videos_async(sec_user_id, limit, account_file))


def fetch_video_stats(
    aweme_id: str,
    *,
    account_file: Optional[str] = None,
) -> Dict[str, Any]:
    """拉单个视频的最新统计 (aweme_id 也可传 web URL)."""
    return _run_sync(_fetch_video_stats_async(aweme_id, account_file))


def fetch_comments(
    aweme_id: str,
    limit: int = 200,
    *,
    account_file: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """拉单视频评论列表 (按 cursor 分页, 最多 ``limit`` 条).

    Returns:
        list[dict], 每项包含: cid / text / nickname / user_id /
        create_time / digg_count / reply_comment_total / raw.
    """
    if limit <= 0:
        return []
    return _run_sync(_fetch_comments_async(aweme_id, limit, account_file))


__all__ = [
    "F2CookieError",
    "load_cookie_string",
    "fetch_user_videos",
    "fetch_video_stats",
    "fetch_comments",
    "DEFAULT_ACCOUNT_FILE",
]
