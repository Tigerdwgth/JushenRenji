"""f2 真实抖音 API smoke test.

默认 skip (CI 不跑). 本地手动验证用:
    pytest tests/test_f2_smoke.py -m smoke -v -s

前置:
    cache/douyin_cookies.json 必须是有效的登录态 storage_state.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# 默认 skip; 需要 ``-m smoke`` 才会跑
pytestmark = pytest.mark.smoke


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_COOKIE = _PROJECT_ROOT / "cache" / "douyin_cookies.json"


def _have_cookie() -> bool:
    return _DEFAULT_COOKIE.exists() and _DEFAULT_COOKIE.stat().st_size > 100


def test_cookie_string_load():
    """cookie 文件能读出非空 cookie 字符串, 且包含 sessionid*."""
    if not _have_cookie():
        pytest.skip(f"cookie 不存在: {_DEFAULT_COOKIE}")
    from src.distribution.f2_client import load_cookie_string
    s = load_cookie_string(str(_DEFAULT_COOKIE))
    assert s
    assert "=" in s
    assert any(k in s for k in ("sessionid=", "sessionid_ss=", "sid_tt="))


def test_fetch_user_videos_self():
    """拉自己最近 5 条作品, 至少能拿到 1 条且字段齐全."""
    if not _have_cookie():
        pytest.skip(f"cookie 不存在: {_DEFAULT_COOKIE}")
    from src.distribution.f2_client import fetch_user_videos
    items = fetch_user_videos(limit=5, account_file=str(_DEFAULT_COOKIE))
    assert isinstance(items, list)
    if not items:
        pytest.skip("当前账号暂无作品")
    assert len(items) <= 5
    a = items[0]
    assert a["aweme_id"]
    assert "play_count" in a
    assert "digg_count" in a
    assert "comment_count" in a


def test_fetch_video_stats_self_first():
    """先拿用户作品列表第一条, 再用 fetch_video_stats 取详情."""
    if not _have_cookie():
        pytest.skip(f"cookie 不存在: {_DEFAULT_COOKIE}")
    from src.distribution.f2_client import (
        fetch_user_videos, fetch_video_stats,
    )
    items = fetch_user_videos(limit=1, account_file=str(_DEFAULT_COOKIE))
    if not items:
        pytest.skip("当前账号暂无作品")
    aweme_id = items[0]["aweme_id"]
    stats = fetch_video_stats(aweme_id, account_file=str(_DEFAULT_COOKIE))
    assert stats["aweme_id"] == aweme_id
    assert "digg_count" in stats
    assert "comment_count" in stats


def test_fetch_comments_self_first():
    """拉自己第一条作品的评论 (可能为 0 条, 只验证不报错)."""
    if not _have_cookie():
        pytest.skip(f"cookie 不存在: {_DEFAULT_COOKIE}")
    from src.distribution.f2_client import fetch_user_videos, fetch_comments
    items = fetch_user_videos(limit=1, account_file=str(_DEFAULT_COOKIE))
    if not items:
        pytest.skip("当前账号暂无作品")
    aweme_id = items[0]["aweme_id"]
    comments = fetch_comments(aweme_id, limit=20, account_file=str(_DEFAULT_COOKIE))
    assert isinstance(comments, list)
    for c in comments:
        assert c["cid"]
        assert "text" in c
        assert "nickname" in c
