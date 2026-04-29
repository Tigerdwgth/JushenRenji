"""已回复评论的 sqlite 去重存储.

schema:
    CREATE TABLE replied_comments (
        platform   TEXT NOT NULL,
        comment_id TEXT NOT NULL,
        post_id    TEXT NOT NULL,
        replied_at INTEGER NOT NULL,
        PRIMARY KEY (platform, comment_id)
    );
    CREATE INDEX idx_platform_date ON replied_comments(platform, replied_at);

文件路径默认: <project_root>/cache/comments_replied.db
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get(
    "JSR_COMMENTS_DB",
    str(Path(__file__).resolve().parents[3] / "cache" / "comments_replied.db"),
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS replied_comments (
    platform   TEXT NOT NULL,
    comment_id TEXT NOT NULL,
    post_id    TEXT NOT NULL,
    replied_at INTEGER NOT NULL,
    PRIMARY KEY (platform, comment_id)
);
CREATE INDEX IF NOT EXISTS idx_platform_date
    ON replied_comments(platform, replied_at);
"""


def _ensure_dir(db_path: str) -> None:
    parent = Path(db_path).parent
    parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _conn(db_path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """打开 sqlite 连接并保证 schema 存在; 退出时 commit + close."""
    _ensure_dir(db_path)
    cn = sqlite3.connect(db_path, timeout=10.0)
    try:
        cn.executescript(_SCHEMA_SQL)
        yield cn
        cn.commit()
    finally:
        cn.close()


def is_replied(platform: str, comment_id: str,
               db_path: str = DEFAULT_DB_PATH) -> bool:
    """该 (platform, comment_id) 是否已回复过."""
    if not platform or not comment_id:
        return False
    with _conn(db_path) as cn:
        cur = cn.execute(
            "SELECT 1 FROM replied_comments WHERE platform=? AND comment_id=? LIMIT 1",
            (platform, str(comment_id)),
        )
        return cur.fetchone() is not None


def mark_replied(platform: str, comment_id: str, post_id: str,
                 db_path: str = DEFAULT_DB_PATH,
                 ts: Optional[int] = None) -> None:
    """记录一次成功回复."""
    if not platform or not comment_id:
        return
    ts = ts if ts is not None else int(time.time())
    with _conn(db_path) as cn:
        cn.execute(
            "INSERT OR REPLACE INTO replied_comments "
            "(platform, comment_id, post_id, replied_at) VALUES (?,?,?,?)",
            (platform, str(comment_id), str(post_id or ""), ts),
        )
    logger.debug("[replied_db] marked %s/%s @ %s", platform, comment_id, ts)


def count_today(platform: str,
                db_path: str = DEFAULT_DB_PATH,
                now_ts: Optional[int] = None) -> int:
    """返回今天 (UTC+8 自然日) 该平台已回复条数, 用于节流."""
    now_ts = now_ts if now_ts is not None else int(time.time())
    # UTC+8 自然日的 0 点
    bj_offset = 8 * 3600
    bj_now = now_ts + bj_offset
    bj_day_start = bj_now - (bj_now % 86400)
    day_start_utc = bj_day_start - bj_offset
    with _conn(db_path) as cn:
        cur = cn.execute(
            "SELECT COUNT(*) FROM replied_comments "
            "WHERE platform=? AND replied_at>=?",
            (platform, day_start_utc),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


# 平台日上限 (CLAUDE.md task spec)
DAILY_LIMITS = {
    "bilibili": 50,
    "xiaohongshu": 15,
    "douyin": 20,
}


def reached_daily_limit(platform: str,
                        db_path: str = DEFAULT_DB_PATH) -> bool:
    """是否触发当日上限."""
    limit = DAILY_LIMITS.get(platform, 0)
    if limit <= 0:
        return False
    return count_today(platform, db_path=db_path) >= limit
