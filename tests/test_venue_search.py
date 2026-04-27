"""Unit tests for src.discovery_sources.venue_search.

mock feedparser + arxiv API，不依赖网络。
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------
# 1. _build_venue_query 形态
# ---------------------------------------------------------------------

def test_build_query_accepted_default():
    """默认 accepted_only=True → query 含 4 个 OR co: 子句 + cat 子句。"""
    from src.discovery_sources.venue_search import _build_venue_query
    q = _build_venue_query("RSS", 2025)
    # 4 个 co: 子句
    assert q.count("co:%22") == 4, q
    # 有 OR
    assert "+OR+" in q
    # 有 cat 部分
    assert "cat:cs.RO" in q
    assert "cat:cs.CV" in q
    assert "cat:cs.LG" in q
    assert "cat:cs.AI" in q
    # 4 条变体的关键词都在
    assert "accepted+to+RSS+2025" in q
    assert "RSS+2025" in q
    assert "RSS%2725" in q  # quote_plus("RSS'25") = RSS%2725
    assert "to+appear+at+RSS+2025" in q


def test_build_query_include_submitted():
    """accepted_only=False → 加第 5 个子句 submitted to。"""
    from src.discovery_sources.venue_search import _build_venue_query
    q = _build_venue_query("NeurIPS", 2025, accepted_only=False)
    assert q.count("co:%22") == 5
    assert "submitted+to+NeurIPS+2025" in q


def test_year_short_format():
    """2025 → "'25", 2009 → "'09" 都要补 0。"""
    from src.discovery_sources.venue_search import _year_short
    assert _year_short(2025) == "'25"
    assert _year_short(2009) == "'09"
    assert _year_short(2026) == "'26"


def test_build_query_custom_categories():
    """传 categories=["cs.RO"] 时只输出该 cat。"""
    from src.discovery_sources.venue_search import _build_venue_query
    q = _build_venue_query("ICRA", 2025, categories=["cs.RO"])
    assert "cat:cs.RO" in q
    # 不应含其他默认 cat（精确比对避免 cs.RO 匹配 cs.RO 自己）
    assert "cat:cs.CV" not in q
    assert "cat:cs.LG" not in q
    assert "cat:cs.AI" not in q


# ---------------------------------------------------------------------
# 2. _venue_co_clauses 子句数
# ---------------------------------------------------------------------

def test_venue_co_clauses_count_accepted():
    from src.discovery_sources.venue_search import _venue_co_clauses
    cs = _venue_co_clauses("RSS", 2025, accepted_only=True)
    assert len(cs) == 4


def test_venue_co_clauses_count_with_submitted():
    from src.discovery_sources.venue_search import _venue_co_clauses
    cs = _venue_co_clauses("RSS", 2025, accepted_only=False)
    assert len(cs) == 5


def test_venue_co_clauses_empty_venue_raises():
    from src.discovery_sources.venue_search import _venue_co_clauses
    with pytest.raises(ValueError):
        _venue_co_clauses("", 2025, accepted_only=True)


# ---------------------------------------------------------------------
# 3. fetch_arxiv_by_venue mock arxiv API
# ---------------------------------------------------------------------

def _make_fake_entry(link, title, summary, updated="2025-04-01T00:00:00Z"):
    """构造一个像 feedparser 返回的 entry（attribute access）。"""
    e = MagicMock()
    e.link = link
    e.title = title
    e.summary = summary
    e.published = updated
    e.updated = updated
    # mock dict-style 不支持，让 .get 抛出走 attribute 路径
    return e


def test_fetch_arxiv_by_venue_mock_feed():
    """mock _fetch_via_arxiv_api → 返回固定 atom entries → 断言 Candidate 列表。"""
    from src.discovery_sources import venue_search
    fake_entries = [
        _make_fake_entry(
            link="https://arxiv.org/abs/2504.12345",
            title="Foo VLA Robot for RSS 2025",
            summary="An interesting paper accepted to RSS 2025.",
            updated="2025-04-01T12:00:00Z",
        ),
        _make_fake_entry(
            link="https://arxiv.org/abs/2504.67890v2",
            title="Bar Imitation Learning",
            summary="To appear at RSS 2025.",
            updated="2025-04-15T09:00:00Z",
        ),
        # 不能解析 arxiv_id（无 arxiv 链接）→ 应被跳过
        _make_fake_entry(
            link="https://example.com/foo",
            title="Should be skipped",
            summary="No arxiv id",
        ),
    ]
    with patch.object(venue_search, "_fetch_via_arxiv_api",
                      return_value=fake_entries) as m:
        cands = venue_search.fetch_arxiv_by_venue(
            venue="RSS", year=2025, limit=10, accepted_only=True,
        )
    assert m.called, "应调用 _fetch_via_arxiv_api"
    assert len(cands) == 2, "无 arxiv id 的应被跳过"
    assert cands[0].arxiv_id == "2504.12345"
    assert cands[0].source == "arxiv_venue"
    assert cands[0].url == "https://arxiv.org/abs/2504.12345"
    assert cands[0].submitted_date == "2025-04-01"
    assert cands[1].arxiv_id == "2504.67890"  # vN 后缀剥掉


def test_fetch_arxiv_by_venue_dedup_arxiv_id():
    """同 arxiv_id 重复 → 只保留 1 条（按出现顺序首个）。"""
    from src.discovery_sources import venue_search
    fake_entries = [
        _make_fake_entry(
            link="https://arxiv.org/abs/2504.00001",
            title="First", summary="A",
        ),
        _make_fake_entry(
            link="https://arxiv.org/abs/2504.00001v2",
            title="Same id v2", summary="B",
        ),
    ]
    with patch.object(venue_search, "_fetch_via_arxiv_api",
                      return_value=fake_entries):
        cands = venue_search.fetch_arxiv_by_venue("RSS", 2025, limit=10)
    assert len(cands) == 1
    assert cands[0].title == "First"


def test_fetch_arxiv_by_venue_invalid_year_returns_empty():
    """year 非数字 → 警告并返回空列表（不抛）。"""
    from src.discovery_sources.venue_search import fetch_arxiv_by_venue
    cands = fetch_arxiv_by_venue("RSS", "not-a-year", limit=10)
    assert cands == []


def test_fetch_arxiv_by_venue_empty_venue_returns_empty():
    """venue 空 → 警告并返回空列表（不抛）。"""
    from src.discovery_sources.venue_search import fetch_arxiv_by_venue
    cands = fetch_arxiv_by_venue("", 2025, limit=10)
    assert cands == []


def test_fetch_arxiv_by_venue_network_failure_returns_empty():
    """_fetch_via_arxiv_api 抛异常 → 返回空列表（不抛）。"""
    from src.discovery_sources import venue_search
    with patch.object(venue_search, "_fetch_via_arxiv_api",
                      side_effect=RuntimeError("simulated network down")):
        cands = venue_search.fetch_arxiv_by_venue("RSS", 2025, limit=10)
    assert cands == []
