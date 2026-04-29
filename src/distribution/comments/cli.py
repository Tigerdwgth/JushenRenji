"""三平台评论自动回复 CLI 入口.

Usage:
    python -m src.distribution.comments.cli \\
        --platforms bilibili,xiaohongshu,douyin \\
        [--max-posts 10] [--dry-run] [--published-json PATH] [--max-age-hours 168]

流程:
1. 读取 published_papers.json (默认 cache/published_papers.json),
   筛选最近 max_age_hours 小时内的视频, 取前 max_posts 条
2. 对每条视频 → 每个目标平台调 pull_recent_comments
3. 对每条新评论, reply_engine.generate_reply → 节流 sleep 1-60s →
   reply_to_comment(若非 dry-run) → mark_replied
4. 单平台触发日上限即停

目前 published_papers.json 只记录视频路径, 不记录平台 post_id, 因此实际跑评论
回复需要外部 mapping 文件 (cache/post_ids.json) 提供 BV/note_id/aweme_url.
mapping 格式:
{
    "<video_path_or_arxiv_id>": {
        "bilibili": {"bv": "BV1xx", "title": "..."},
        "xiaohongshu": {"note_id": "abc", "xsec_token": "...", "title": "..."},
        "douyin": {"aweme_url": "https://...", "title": "..."}
    }
}
没有 mapping 时该 (post, platform) 自动跳过, 不报错.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import replied_db
from .reply_engine import generate_reply

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_published_json() -> str:
    return str(_project_root() / "cache" / "published_papers.json")


def _default_post_ids_json() -> str:
    return str(_project_root() / "cache" / "post_ids.json")


def _load_recent_posts(published_json: str, max_posts: int,
                       max_age_hours: int) -> List[dict]:
    """读 published_papers.json, 取最近 max_age_hours 内 max_posts 条."""
    if not os.path.exists(published_json):
        logger.warning("[cli] published_papers.json 不存在: %s", published_json)
        return []
    try:
        with open(published_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        logger.error("[cli] 解析 published_papers.json 失败: %s", exc)
        return []
    if not isinstance(data, list):
        return []
    cutoff = datetime.now() - timedelta(hours=max_age_hours)

    def _post_dt(p: dict) -> datetime:
        ds = p.get("date") or ""
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ds, fmt)
            except ValueError:
                continue
        return datetime.fromtimestamp(0)

    recent = [p for p in data if _post_dt(p) >= cutoff]
    recent.sort(key=_post_dt, reverse=True)
    return recent[:max_posts]


def _load_post_ids(post_ids_json: str) -> Dict[str, dict]:
    if not os.path.exists(post_ids_json):
        return {}
    try:
        with open(post_ids_json, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as exc:  # noqa: BLE001
        logger.error("[cli] post_ids.json 解析失败: %s", exc)
        return {}


def _post_key(post: dict) -> str:
    return post.get("arxiv_id") or post.get("video_path") or post.get("title") or ""


def _process_bilibili(post: dict, mapping: dict, since: datetime,
                      dry_run: bool, sleep_min: int, sleep_max: int) -> int:
    if "bv" not in mapping:
        logger.info("[cli] bilibili: 无 BV 映射, skip post=%s", post.get("title"))
        return 0
    from . import bilibili_comments
    bv = mapping["bv"]
    title = mapping.get("title") or post.get("title", "")
    summary = mapping.get("summary", "")
    op_nick = mapping.get("op_nick")
    try:
        comments = bilibili_comments.pull_recent_comments(bv, since)
    except Exception as exc:  # noqa: BLE001
        logger.error("[cli] bilibili pull 失败 bv=%s: %s", bv, exc)
        return 0
    n = 0
    for c in comments:
        if replied_db.is_replied("bilibili", c.comment_id):
            continue
        if replied_db.reached_daily_limit("bilibili"):
            logger.info("[cli] bilibili 日上限已到, 提前停止")
            break
        reply = generate_reply(title, summary, c.content, c.nick,
                               platform="bilibili", op_nick=op_nick)
        if reply is None:
            continue
        if dry_run:
            logger.info("[cli][dry-run] bilibili reply -> %s: %s",
                        c.comment_id, reply)
            replied_db.mark_replied("bilibili", c.comment_id, bv)
            n += 1
            continue
        ok = bilibili_comments.reply_to_comment(bv, c.comment_id, reply)
        if ok:
            replied_db.mark_replied("bilibili", c.comment_id, bv)
            n += 1
        time.sleep(random.randint(sleep_min, sleep_max))
    return n


def _process_xhs(post: dict, mapping: dict, since: datetime,
                 dry_run: bool, sleep_min: int, sleep_max: int) -> int:
    if "note_id" not in mapping:
        logger.info("[cli] xiaohongshu: 无 note_id 映射, skip")
        return 0
    from . import xhs_comments
    note_id = mapping["note_id"]
    xsec = mapping.get("xsec_token", "")
    title = mapping.get("title") or post.get("title", "")
    summary = mapping.get("summary", "")
    op_nick = mapping.get("op_nick")
    try:
        comments = xhs_comments.pull_recent_comments(note_id, xsec, since)
    except Exception as exc:  # noqa: BLE001
        logger.error("[cli] xhs pull 失败 note=%s: %s", note_id, exc)
        return 0
    n = 0
    for c in comments:
        if replied_db.is_replied("xiaohongshu", c.comment_id):
            continue
        if replied_db.reached_daily_limit("xiaohongshu"):
            logger.info("[cli] xiaohongshu 日上限已到, 提前停止")
            break
        reply = generate_reply(title, summary, c.content, c.nick,
                               platform="xiaohongshu", op_nick=op_nick)
        if reply is None:
            continue
        if dry_run:
            logger.info("[cli][dry-run] xiaohongshu reply -> %s: %s",
                        c.comment_id, reply)
            replied_db.mark_replied("xiaohongshu", c.comment_id, note_id)
            n += 1
            continue
        ok = xhs_comments.reply_to_comment(note_id, c.comment_id, reply)
        if ok:
            replied_db.mark_replied("xiaohongshu", c.comment_id, note_id)
            n += 1
        time.sleep(random.randint(sleep_min, sleep_max))
    return n


def _process_douyin(post: dict, mapping: dict, since: datetime,
                    dry_run: bool, sleep_min: int, sleep_max: int) -> int:
    if "aweme_url" not in mapping:
        logger.info("[cli] douyin: 无 aweme_url 映射, skip")
        return 0
    from . import douyin_comments
    aweme_url = mapping["aweme_url"]
    title = mapping.get("title") or post.get("title", "")
    summary = mapping.get("summary", "")
    op_nick = mapping.get("op_nick")
    try:
        comments = douyin_comments.pull_recent_comments(aweme_url, since)
    except Exception as exc:  # noqa: BLE001
        logger.error("[cli] douyin pull 失败 url=%s: %s", aweme_url, exc)
        return 0
    n = 0
    for c in comments:
        if replied_db.is_replied("douyin", c.comment_id):
            continue
        if replied_db.reached_daily_limit("douyin"):
            logger.info("[cli] douyin 日上限已到, 提前停止")
            break
        reply = generate_reply(title, summary, c.content, c.nick,
                               platform="douyin", op_nick=op_nick)
        if reply is None:
            continue
        if dry_run:
            logger.info("[cli][dry-run] douyin reply -> %s: %s",
                        c.comment_id, reply)
            replied_db.mark_replied("douyin", c.comment_id, aweme_url)
            n += 1
            continue
        ok = douyin_comments.reply_to_comment(aweme_url, c.content, reply)
        if ok:
            replied_db.mark_replied("douyin", c.comment_id, aweme_url)
            n += 1
        time.sleep(random.randint(sleep_min, sleep_max))
    return n


PLATFORM_HANDLERS = {
    "bilibili": _process_bilibili,
    "xiaohongshu": _process_xhs,
    "douyin": _process_douyin,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="三平台评论自动拉取+LLM 回复模块"
    )
    parser.add_argument("--platforms", default="bilibili,xiaohongshu,douyin",
                        help="逗号分隔: bilibili,xiaohongshu,douyin")
    parser.add_argument("--max-posts", type=int, default=10)
    parser.add_argument("--max-age-hours", type=int, default=168)
    parser.add_argument("--published-json", default=None)
    parser.add_argument("--post-ids-json", default=None)
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="(默认开启) 不真发回复")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                        help="关闭 dry-run, 真实发布")
    parser.add_argument("--sleep-min", type=int, default=1)
    parser.add_argument("--sleep-max", type=int, default=60)
    parser.add_argument("--since-hours", type=int, default=72,
                        help="只看 since-hours 小时内的评论")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    unknown = [p for p in platforms if p not in PLATFORM_HANDLERS]
    if unknown:
        logger.error("[cli] 未知平台: %s", unknown)
        return 2

    published_json = args.published_json or _default_published_json()
    post_ids_json = args.post_ids_json or _default_post_ids_json()
    posts = _load_recent_posts(published_json, args.max_posts,
                               args.max_age_hours)
    if not posts:
        logger.warning("[cli] 没有候选 post (published_json=%s)", published_json)
        return 0
    post_ids = _load_post_ids(post_ids_json)
    since = datetime.now() - timedelta(hours=args.since_hours)
    logger.info("[cli] 处理 %d 条 post, dry_run=%s", len(posts), args.dry_run)
    total = 0
    for post in posts:
        key = _post_key(post)
        mapping_all = post_ids.get(key, {})
        for plat in platforms:
            mapping = mapping_all.get(plat) or {}
            handler = PLATFORM_HANDLERS[plat]
            try:
                n = handler(post, mapping, since,
                            args.dry_run, args.sleep_min, args.sleep_max)
                total += n
            except Exception as exc:  # noqa: BLE001
                logger.exception("[cli] %s 处理 %s 异常: %s", plat, key, exc)
    logger.info("[cli] 完成, 共处理(或 dry-run) %d 条评论", total)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
