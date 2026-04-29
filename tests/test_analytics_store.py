"""测试 src/distribution/analytics/stats_store.py"""
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "creator_stats.db"


def test_init_db_creates_schema(tmp_db):
    from src.distribution.analytics.stats_store import init_db
    p = init_db(tmp_db)
    assert Path(p).exists()
    with sqlite3.connect(p) as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='creator_stats'"
        )
        assert cur.fetchone() is not None
        cur = conn.execute("PRAGMA table_info(creator_stats)")
        cols = {row[1] for row in cur.fetchall()}
        assert {"platform", "post_id", "fetch_date", "views", "likes",
                "comments", "shares", "favorites", "title", "raw_json"} <= cols


def test_upsert_and_get_recent(tmp_db):
    from src.distribution.analytics.stats_store import (get_recent,
                                                        upsert_stats)
    today = date.today().isoformat()
    upsert_stats(
        "bilibili", "BV1xx", today,
        views=100, likes=10, comments=2, shares=1, favorites=3,
        title="hello", raw_json={"k": "v"}, db_path=tmp_db,
    )
    rows = get_recent(platform="bilibili", days=7, db_path=tmp_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["platform"] == "bilibili"
    assert r["post_id"] == "BV1xx"
    assert r["views"] == 100
    assert r["title"] == "hello"
    assert json.loads(r["raw_json"]) == {"k": "v"}


def test_upsert_overwrites_same_pk(tmp_db):
    from src.distribution.analytics.stats_store import (get_recent,
                                                        upsert_stats)
    today = date.today().isoformat()
    upsert_stats("bilibili", "BV1xx", today, views=100, db_path=tmp_db)
    upsert_stats("bilibili", "BV1xx", today, views=200, likes=5, db_path=tmp_db)
    rows = get_recent(platform="bilibili", days=1, db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["views"] == 200
    assert rows[0]["likes"] == 5


def test_get_recent_filters_by_days(tmp_db):
    from src.distribution.analytics.stats_store import (get_recent,
                                                        upsert_stats)
    today = date.today()
    upsert_stats("bilibili", "BV_today", today.isoformat(),
                 views=1, db_path=tmp_db)
    upsert_stats("bilibili", "BV_2d", (today - timedelta(days=2)).isoformat(),
                 views=2, db_path=tmp_db)
    upsert_stats("bilibili", "BV_10d", (today - timedelta(days=10)).isoformat(),
                 views=3, db_path=tmp_db)
    rows = get_recent(days=3, db_path=tmp_db)  # 含今天回溯 3 天 -> 包含 today, today-2
    post_ids = sorted(r["post_id"] for r in rows)
    assert post_ids == ["BV_2d", "BV_today"]


def test_get_recent_platform_filter(tmp_db):
    from src.distribution.analytics.stats_store import (get_recent,
                                                        upsert_stats)
    today = date.today().isoformat()
    upsert_stats("bilibili", "BV1", today, views=10, db_path=tmp_db)
    upsert_stats("xhs", "note1", today, views=20, db_path=tmp_db)
    upsert_stats("douyin", "7100", today, views=30, db_path=tmp_db)
    assert len(get_recent(platform="bilibili", days=1, db_path=tmp_db)) == 1
    assert len(get_recent(platform="xhs", days=1, db_path=tmp_db)) == 1
    assert len(get_recent(days=1, db_path=tmp_db)) == 3


def test_summary_table_basic(tmp_db):
    from src.distribution.analytics.stats_store import (summary_table,
                                                        upsert_stats)
    today = date.today().isoformat()
    upsert_stats("bilibili", "BV1", today, views=100, likes=10, comments=2,
                 shares=1, favorites=3, title="标题", db_path=tmp_db)
    upsert_stats("bilibili", "BV2", today, views=200, likes=30, db_path=tmp_db)
    out = summary_table(platform="bilibili", days=1, db_path=tmp_db)
    assert "bilibili" in out
    assert "BV1" in out
    assert "BV2" in out
    assert "100" in out
    assert "TOTAL" in out
    # 总和 = 100 + 200 = 300
    assert "300" in out


def test_summary_table_empty(tmp_db):
    from src.distribution.analytics.stats_store import summary_table
    out = summary_table(platform="douyin", days=1, db_path=tmp_db)
    assert "no data" in out.lower()


def test_summary_table_uses_supplied_rows():
    """rows 参数应让我们绕开 db, 方便 LLM 自定义 group/sort 后再渲染."""
    from src.distribution.analytics.stats_store import summary_table
    rows = [
        {"fetch_date": "2026-04-28", "platform": "bilibili",
         "post_id": "BVx", "title": "T", "views": 5, "likes": 1,
         "comments": 0, "shares": 0, "favorites": 0},
    ]
    out = summary_table(rows=rows)
    assert "BVx" in out
    assert "5" in out


def test_upsert_validates_args(tmp_db):
    from src.distribution.analytics.stats_store import upsert_stats
    with pytest.raises(ValueError):
        upsert_stats("", "BVx", "2026-04-28", db_path=tmp_db)
    with pytest.raises(ValueError):
        upsert_stats("bilibili", "", "2026-04-28", db_path=tmp_db)
    with pytest.raises(ValueError):
        upsert_stats("bilibili", "BVx", "bad-date", db_path=tmp_db)


def test_upsert_coerces_invalid_numeric(tmp_db):
    from src.distribution.analytics.stats_store import (get_recent,
                                                        upsert_stats)
    upsert_stats("bilibili", "BV1", date.today().isoformat(),
                 views="not a number", likes=None, db_path=tmp_db)
    rows = get_recent(days=1, db_path=tmp_db)
    assert rows[0]["views"] == 0
    assert rows[0]["likes"] == 0
