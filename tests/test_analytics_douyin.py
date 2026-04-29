"""测试 src/distribution/analytics/douyin_stats.py (f2 实现).

mock 的是 ``src.distribution.f2_client`` 的方法 (业务 API 边界), 不是 f2 SDK
本身. 这样既能验证字段映射, 又不依赖网络.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _sample_videos():
    return [
        {
            "aweme_id": "7100",
            "desc": "VLA 论文解读",
            "create_time": 1714400000,
            "play_count": 1234,
            "digg_count": 88,
            "comment_count": 9,
            "share_count": 3,
            "collect_count": 5,
            "raw": {"aweme_id": "7100"},
        },
        {
            "aweme_id": "7101",
            "desc": "另一篇",
            "create_time": 1714410000,
            "play_count": 200,
            "digg_count": 12,
            "comment_count": 1,
            "share_count": 0,
            "collect_count": 0,
            "raw": {"aweme_id": "7101"},
        },
    ]


def test_fetch_creator_stats_returns_items():
    with patch("src.distribution.analytics.douyin_stats.f2_client.fetch_user_videos",
               return_value=_sample_videos()) as mock_fetch:
        from src.distribution.analytics.douyin_stats import fetch_creator_stats
        out = fetch_creator_stats(max_posts=5)
    mock_fetch.assert_called_once()
    kwargs = mock_fetch.call_args.kwargs
    assert kwargs["limit"] == 5
    assert len(out) == 2
    a, b = out
    assert a["post_id"] == "7100"
    assert a["title"] == "VLA 论文解读"
    assert a["views"] == 1234
    assert a["likes"] == 88
    assert a["comments"] == 9
    assert a["shares"] == 3
    assert a["favorites"] == 5
    assert a["completion_rate"] == 0.0
    assert b["post_id"] == "7101"
    assert b["views"] == 200


def test_fetch_creator_stats_passes_through_account_file_and_sec_user_id(tmp_path):
    cookie = tmp_path / "cookies.json"
    cookie.write_text("{}", encoding="utf-8")
    with patch("src.distribution.analytics.douyin_stats.f2_client.fetch_user_videos",
               return_value=_sample_videos()) as mock_fetch:
        from src.distribution.analytics.douyin_stats import fetch_creator_stats
        fetch_creator_stats(
            account_file=str(cookie),
            max_posts=3,
            sec_user_id="MS4wLjABAAAA_xxxx",
        )
    kwargs = mock_fetch.call_args.kwargs
    assert kwargs["account_file"] == str(cookie)
    assert kwargs["sec_user_id"] == "MS4wLjABAAAA_xxxx"
    assert kwargs["limit"] == 3


def test_fetch_creator_stats_raises_on_cookie_error():
    from src.distribution.f2_client import F2CookieError
    from src.distribution.analytics.douyin_stats import (
        DouyinStatsError, fetch_creator_stats,
    )
    with patch("src.distribution.analytics.douyin_stats.f2_client.fetch_user_videos",
               side_effect=F2CookieError("cookie 文件不存在: x")):
        with pytest.raises(DouyinStatsError, match="cookie 文件不存在"):
            fetch_creator_stats(max_posts=5)


def test_fetch_creator_stats_raises_on_empty():
    from src.distribution.analytics.douyin_stats import (
        DouyinStatsError, fetch_creator_stats,
    )
    with patch("src.distribution.analytics.douyin_stats.f2_client.fetch_user_videos",
               return_value=[]):
        with pytest.raises(DouyinStatsError, match="未抓到任何作品"):
            fetch_creator_stats(max_posts=5)


def test_fetch_creator_stats_raises_on_generic_error():
    from src.distribution.analytics.douyin_stats import (
        DouyinStatsError, fetch_creator_stats,
    )
    with patch("src.distribution.analytics.douyin_stats.f2_client.fetch_user_videos",
               side_effect=RuntimeError("接口 5xx")):
        with pytest.raises(DouyinStatsError, match="f2 抓取失败"):
            fetch_creator_stats(max_posts=5)


def test_fetch_note_stats_maps_fields():
    sample = {
        "aweme_id": "7100",
        "desc": "VLA",
        "create_time": 1714400000,
        "play_count": 1000,
        "digg_count": 50,
        "comment_count": 5,
        "share_count": 2,
        "collect_count": 1,
        "raw": {"aweme_id": "7100"},
    }
    with patch("src.distribution.analytics.douyin_stats.f2_client.fetch_video_stats",
               return_value=sample):
        from src.distribution.analytics.douyin_stats import fetch_note_stats
        out = fetch_note_stats("7100")
    assert out["post_id"] == "7100"
    assert out["title"] == "VLA"
    assert out["views"] == 1000
    assert out["likes"] == 50
    assert out["comments"] == 5
    assert out["shares"] == 2
    assert out["favorites"] == 1
    assert out["completion_rate"] == 0.0


def test_fetch_note_stats_raises_on_missing_post_id():
    from src.distribution.analytics.douyin_stats import (
        DouyinStatsError, fetch_note_stats,
    )
    with pytest.raises(DouyinStatsError, match="post_id 不能为空"):
        fetch_note_stats("")


def test_fetch_note_stats_raises_on_cookie_error():
    from src.distribution.f2_client import F2CookieError
    from src.distribution.analytics.douyin_stats import (
        DouyinStatsError, fetch_note_stats,
    )
    with patch("src.distribution.analytics.douyin_stats.f2_client.fetch_video_stats",
               side_effect=F2CookieError("cookie 失效")):
        with pytest.raises(DouyinStatsError, match="cookie 失效"):
            fetch_note_stats("7100")


def test_fetch_creator_stats_filters_videos_without_id():
    """f2 偶尔返回没 aweme_id 的脏数据 (空作品/已删除), 应过滤."""
    bad = _sample_videos()
    bad.append({
        "aweme_id": "",
        "desc": "deleted",
        "create_time": 0,
        "play_count": 0, "digg_count": 0, "comment_count": 0,
        "share_count": 0, "collect_count": 0, "raw": {},
    })
    with patch("src.distribution.analytics.douyin_stats.f2_client.fetch_user_videos",
               return_value=bad):
        from src.distribution.analytics.douyin_stats import fetch_creator_stats
        out = fetch_creator_stats(max_posts=10)
    assert len(out) == 2
    assert all(it["post_id"] for it in out)
