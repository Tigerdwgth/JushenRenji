"""sqlite 持久化与汇总输出.

存储 schema:
    CREATE TABLE creator_stats(
        platform   TEXT,
        post_id    TEXT,
        fetch_date TEXT,           -- YYYY-MM-DD
        views      INTEGER DEFAULT 0,
        likes      INTEGER DEFAULT 0,
        comments   INTEGER DEFAULT 0,
        shares     INTEGER DEFAULT 0,
        favorites  INTEGER DEFAULT 0,
        title      TEXT DEFAULT '',
        raw_json   TEXT DEFAULT '',
        PRIMARY KEY(platform, post_id, fetch_date)
    )

公开 API:
    init_db(db_path=None) -> Path
    upsert_stats(platform, post_id, fetch_date=None, *, raw_json=None,
                  db_path=None, **stats) -> None
    get_recent(platform=None, days=7, db_path=None) -> list[dict]
    summary_table(platform=None, days=7, db_path=None) -> str
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(
    os.environ.get(
        "JSR_STATS_DB",
        os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            ),
            "data",
            "creator_stats.db",
        ),
    )
)

_NUMERIC_FIELDS = ("views", "likes", "comments", "shares", "favorites")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS creator_stats (
    platform   TEXT NOT NULL,
    post_id    TEXT NOT NULL,
    fetch_date TEXT NOT NULL,
    views      INTEGER DEFAULT 0,
    likes      INTEGER DEFAULT 0,
    comments   INTEGER DEFAULT 0,
    shares     INTEGER DEFAULT 0,
    favorites  INTEGER DEFAULT 0,
    title      TEXT DEFAULT '',
    raw_json   TEXT DEFAULT '',
    PRIMARY KEY(platform, post_id, fetch_date)
);
CREATE INDEX IF NOT EXISTS idx_creator_stats_date
    ON creator_stats(fetch_date);
CREATE INDEX IF NOT EXISTS idx_creator_stats_platform
    ON creator_stats(platform);
"""


def _resolve_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
    p = Path(db_path) if db_path else DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def init_db(db_path: Optional[Union[str, Path]] = None) -> Path:
    """初始化数据库, 返回 db 路径. 幂等."""
    p = _resolve_db_path(db_path)
    with sqlite3.connect(p) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    return p


def _today_str() -> str:
    return date.today().isoformat()


def upsert_stats(
    platform: str,
    post_id: str,
    fetch_date: Optional[str] = None,
    *,
    raw_json: Optional[Union[str, dict]] = None,
    title: str = "",
    db_path: Optional[Union[str, Path]] = None,
    **stats: Any,
) -> None:
    """插入或覆盖一条统计.

    PK = (platform, post_id, fetch_date), 同 PK 重复 upsert 会覆盖.

    Args:
        platform: ``bilibili`` / ``xhs`` / ``douyin``.
        post_id: BV 号 / xhs note_id / aweme_id.
        fetch_date: ``YYYY-MM-DD``, 默认当天.
        raw_json: 原始 dict 或 JSON 字符串(用于回溯).
        title: 视频/笔记标题, 便于 CLI 表格阅读.
        **stats: views/likes/comments/shares/favorites 等数字字段, 缺省补 0.
                 也允许传 ``coins`` / ``danmaku`` 等 B站特有字段(忽略).
    """
    if not platform or not isinstance(platform, str):
        raise ValueError(f"platform 非法: {platform!r}")
    if not post_id or not isinstance(post_id, str):
        raise ValueError(f"post_id 非法: {post_id!r}")
    fetch_date = fetch_date or _today_str()
    if not isinstance(fetch_date, str) or len(fetch_date) != 10:
        raise ValueError(f"fetch_date 应为 YYYY-MM-DD: {fetch_date!r}")

    if isinstance(raw_json, dict):
        try:
            raw_str = json.dumps(raw_json, ensure_ascii=False, default=str)
        except Exception:
            raw_str = json.dumps({"_raw_repr": repr(raw_json)[:2000]})
    elif raw_json is None:
        raw_str = ""
    else:
        raw_str = str(raw_json)

    row: Dict[str, Any] = {
        "platform": platform,
        "post_id": post_id,
        "fetch_date": fetch_date,
        "title": str(title or ""),
        "raw_json": raw_str,
    }
    for key in _NUMERIC_FIELDS:
        v = stats.get(key, 0)
        try:
            row[key] = int(v or 0)
        except (TypeError, ValueError):
            row[key] = 0

    p = init_db(db_path)
    with sqlite3.connect(p) as conn:
        conn.execute(
            """
            INSERT INTO creator_stats
                (platform, post_id, fetch_date, views, likes, comments,
                 shares, favorites, title, raw_json)
            VALUES (:platform, :post_id, :fetch_date, :views, :likes,
                    :comments, :shares, :favorites, :title, :raw_json)
            ON CONFLICT(platform, post_id, fetch_date) DO UPDATE SET
                views=excluded.views,
                likes=excluded.likes,
                comments=excluded.comments,
                shares=excluded.shares,
                favorites=excluded.favorites,
                title=CASE WHEN excluded.title <> '' THEN excluded.title
                           ELSE creator_stats.title END,
                raw_json=CASE WHEN excluded.raw_json <> '' THEN excluded.raw_json
                              ELSE creator_stats.raw_json END
            """,
            row,
        )
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def get_recent(
    platform: Optional[str] = None,
    days: int = 7,
    *,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """返回最近 ``days`` 天 (含今天) 的所有记录, 倒序.

    Args:
        platform: 可选过滤. 不传则三平台全返回.
        days: 含当天回溯天数(>=1).
    """
    if days < 1:
        raise ValueError(f"days 必须 >= 1, got {days}")
    p = init_db(db_path)
    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    with sqlite3.connect(p) as conn:
        conn.row_factory = sqlite3.Row
        if platform:
            cur = conn.execute(
                """
                SELECT * FROM creator_stats
                WHERE platform = ? AND fetch_date >= ?
                ORDER BY fetch_date DESC, platform, post_id
                """,
                (platform, cutoff),
            )
        else:
            cur = conn.execute(
                """
                SELECT * FROM creator_stats
                WHERE fetch_date >= ?
                ORDER BY fetch_date DESC, platform, post_id
                """,
                (cutoff,),
            )
        return [_row_to_dict(r) for r in cur.fetchall()]


def _truncate(s: str, max_len: int) -> str:
    if not s:
        return ""
    s = str(s).replace("\n", " ").replace("\r", " ")
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def summary_table(
    platform: Optional[str] = None,
    days: int = 7,
    *,
    db_path: Optional[Union[str, Path]] = None,
    rows: Optional[Iterable[Dict[str, Any]]] = None,
) -> str:
    """生成 ASCII 表格摘要, 适合直接 print 给人看.

    优先使用传入的 ``rows`` (用于测试); 否则从 db 拉.
    """
    if rows is None:
        rows = get_recent(platform=platform, days=days, db_path=db_path)
    rows = list(rows)
    headers = [
        "date", "platform", "post_id", "title",
        "views", "likes", "comments", "shares", "favs",
    ]
    if not rows:
        return f"(no data for platform={platform or 'ALL'} in last {days}d)\n"

    table_rows = []
    totals = {k: 0 for k in ("views", "likes", "comments", "shares", "favs")}
    for r in rows:
        table_rows.append([
            str(r.get("fetch_date", "")),
            str(r.get("platform", "")),
            _truncate(str(r.get("post_id", "")), 16),
            _truncate(str(r.get("title", "")), 24),
            str(r.get("views", 0)),
            str(r.get("likes", 0)),
            str(r.get("comments", 0)),
            str(r.get("shares", 0)),
            str(r.get("favorites", 0)),
        ])
        totals["views"] += int(r.get("views", 0) or 0)
        totals["likes"] += int(r.get("likes", 0) or 0)
        totals["comments"] += int(r.get("comments", 0) or 0)
        totals["shares"] += int(r.get("shares", 0) or 0)
        totals["favs"] += int(r.get("favorites", 0) or 0)

    # 列宽
    widths = [len(h) for h in headers]
    for row in table_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def _fmt_row(cells):
        return " | ".join(
            cell.ljust(widths[i]) for i, cell in enumerate(cells)
        )

    sep = "-+-".join("-" * w for w in widths)
    lines = [_fmt_row(headers), sep]
    for row in table_rows:
        lines.append(_fmt_row(row))
    lines.append(sep)
    lines.append(_fmt_row([
        "TOTAL", "", "", "",
        str(totals["views"]), str(totals["likes"]),
        str(totals["comments"]), str(totals["shares"]),
        str(totals["favs"]),
    ]))
    lines.append(
        f"\n{len(table_rows)} record(s), platform={platform or 'ALL'}, "
        f"window={days}d"
    )
    return "\n".join(lines) + "\n"
