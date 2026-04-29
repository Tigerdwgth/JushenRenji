"""replied_db sqlite 去重/节流计数测试."""
from __future__ import annotations

import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_replied.db")


def test_is_replied_false_initially(db_path):
    from src.distribution.comments import replied_db as r
    assert r.is_replied("bilibili", "abc", db_path=db_path) is False


def test_mark_then_is_replied(db_path):
    from src.distribution.comments import replied_db as r
    r.mark_replied("bilibili", "rpid_1", "BV1xx", db_path=db_path)
    assert r.is_replied("bilibili", "rpid_1", db_path=db_path) is True
    assert r.is_replied("bilibili", "rpid_2", db_path=db_path) is False
    # 不同平台不互通
    assert r.is_replied("douyin", "rpid_1", db_path=db_path) is False


def test_count_today_only_today(db_path):
    from src.distribution.comments import replied_db as r
    now = int(time.time())
    r.mark_replied("bilibili", "c1", "BV1", db_path=db_path, ts=now)
    r.mark_replied("bilibili", "c2", "BV1", db_path=db_path, ts=now - 86400 * 3)
    assert r.count_today("bilibili", db_path=db_path, now_ts=now) == 1


def test_reached_daily_limit(db_path, monkeypatch):
    from src.distribution.comments import replied_db as r
    monkeypatch.setitem(r.DAILY_LIMITS, "test_plat", 2)
    now = int(time.time())
    assert r.reached_daily_limit("test_plat", db_path=db_path) is False
    r.mark_replied("test_plat", "x1", "p", db_path=db_path, ts=now)
    r.mark_replied("test_plat", "x2", "p", db_path=db_path, ts=now)
    assert r.reached_daily_limit("test_plat", db_path=db_path) is True


def test_idempotent_mark(db_path):
    from src.distribution.comments import replied_db as r
    r.mark_replied("douyin", "x", "u", db_path=db_path)
    r.mark_replied("douyin", "x", "u", db_path=db_path)  # 不应抛错
    assert r.is_replied("douyin", "x", db_path=db_path)
