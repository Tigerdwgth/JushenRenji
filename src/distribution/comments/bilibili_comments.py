"""B站评论拉取 + 回帖 (基于 bilibili-api-python).

依赖现有 src.distribution.bilibili._resolve_cookies 加载 cookie.
oid 必须传 aid (av 号), 不能传 BV 号.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Comment:
    comment_id: str
    parent_id: Optional[str]   # 0 / None 表示根评论
    rpid: int                  # 真实 rpid (int)
    content: str
    nick: str
    ctime: int                 # 评论 unix 时间戳
    aid: int

    @property
    def is_root(self) -> bool:
        return not self.parent_id or self.parent_id in ("0", "None")


def _build_credential():
    """从项目现有 _resolve_cookies 拿 cookie 构造 bilibili_api Credential."""
    try:
        from src.distribution.bilibili import _resolve_cookies
    except ImportError:  # pragma: no cover
        from distribution.bilibili import _resolve_cookies  # type: ignore
    cookies = _resolve_cookies()
    if not cookies:
        return None
    try:
        from bilibili_api import Credential  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("bilibili-api-python 未安装") from exc
    return Credential(
        sessdata=cookies.get("SESSDATA", ""),
        bili_jct=cookies.get("bili_jct", ""),
        buvid3=cookies.get("buvid3", ""),
        dedeuserid=cookies.get("DedeUserID", ""),
    )


async def _aid_from_bvid(bv_id: str) -> int:
    from bilibili_api import video  # type: ignore
    v = video.Video(bvid=bv_id)
    aid = await v.get_aid()
    return int(aid)


async def _pull_async(bv_id: str, since_ts: int,
                      max_pages: int = 5) -> List[Comment]:
    from bilibili_api import comment  # type: ignore
    cred = _build_credential()
    aid = await _aid_from_bvid(bv_id)
    out: List[Comment] = []
    offset = ""
    for _ in range(max_pages):
        page = await comment.get_comments_lazy(
            oid=aid,
            type_=comment.CommentResourceType.VIDEO,
            offset=offset,
            credential=cred,
        )
        replies = (page or {}).get("replies") or []
        if not replies:
            break
        stop = False
        for r in replies:
            ctime = int(r.get("ctime", 0))
            if ctime < since_ts:
                stop = True
                continue
            out.append(Comment(
                comment_id=str(r.get("rpid", "")),
                parent_id=str(r.get("parent", 0)) or None,
                rpid=int(r.get("rpid", 0)),
                content=(r.get("content") or {}).get("message", ""),
                nick=(r.get("member") or {}).get("uname", ""),
                ctime=ctime,
                aid=aid,
            ))
        cursor = (page or {}).get("cursor") or {}
        is_end = cursor.get("is_end") or cursor.get("paginationReply", {}).get("nextOffset") in (None, "")
        offset = cursor.get("paginationReply", {}).get("nextOffset", "") or ""
        if stop or is_end or not offset:
            break
    return out


def pull_recent_comments(bv_id: str, since: datetime,
                         max_pages: int = 5,
                         _runner: Optional[Callable[..., Any]] = None
                         ) -> List[Comment]:
    """拉取 since 之后的评论 (B站 ctime 是秒级 unix ts)."""
    since_ts = int(since.timestamp()) if isinstance(since, datetime) else int(since)
    runner = _runner or asyncio.run
    return runner(_pull_async(bv_id, since_ts, max_pages=max_pages))


async def _reply_async(bv_id: str, parent_rpid: int, content: str) -> bool:
    from bilibili_api import comment  # type: ignore
    cred = _build_credential()
    if cred is None:
        logger.error("[bilibili_comments] 无可用 credential")
        return False
    aid = await _aid_from_bvid(bv_id)
    try:
        resp = await comment.send_comment(
            text=content,
            oid=aid,
            type_=comment.CommentResourceType.VIDEO,
            root=int(parent_rpid) if parent_rpid else None,
            parent=int(parent_rpid) if parent_rpid else None,
            credential=cred,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[bilibili_comments] send_comment 失败: %s", exc)
        return False
    if not isinstance(resp, dict):
        return False
    return resp.get("success_action") == 0 or "rpid" in resp


def reply_to_comment(bv_id: str, parent_id: str, content: str,
                     _runner: Optional[Callable[..., Any]] = None) -> bool:
    """回复某条评论. parent_id 是 rpid 字符串."""
    runner = _runner or asyncio.run
    try:
        rpid = int(parent_id)
    except (TypeError, ValueError):
        logger.error("[bilibili_comments] parent_id 非数字: %r", parent_id)
        return False
    return runner(_reply_async(bv_id, rpid, content))
