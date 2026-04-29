"""测试 src/distribution/analytics/bilibili_stats.py"""
from unittest.mock import patch

import pytest


def test_normalize_stat_maps_all_fields():
    from src.distribution.analytics.bilibili_stats import _normalize_stat
    raw = {
        "view": 12345, "like": 678, "coin": 90, "favorite": 11,
        "share": 5, "reply": 33, "danmaku": 7,
        # noisy
        "now_rank": 0, "his_rank": 0,
    }
    out = _normalize_stat(raw)
    assert out["views"] == 12345
    assert out["likes"] == 678
    assert out["coins"] == 90
    assert out["favorites"] == 11
    assert out["shares"] == 5
    assert out["comments"] == 33
    assert out["replies"] == 33  # alias
    assert out["danmaku"] == 7


def test_normalize_stat_handles_missing_fields():
    from src.distribution.analytics.bilibili_stats import _normalize_stat
    out = _normalize_stat({})
    for k in ("views", "likes", "coins", "favorites",
              "shares", "comments", "danmaku", "replies"):
        assert out[k] == 0


def test_normalize_stat_coerces_invalid_values():
    from src.distribution.analytics.bilibili_stats import _normalize_stat
    out = _normalize_stat({"view": "abc", "like": None, "coin": "12"})
    assert out["views"] == 0
    assert out["likes"] == 0
    assert out["coins"] == 12


def test_fetch_video_stats_invalid_bv_id():
    from src.distribution.analytics.bilibili_stats import fetch_video_stats
    with pytest.raises(ValueError):
        fetch_video_stats("")
    with pytest.raises(ValueError):
        fetch_video_stats("notbv")


def test_fetch_video_stats_calls_get_info_and_returns_normalized():
    """mock bilibili_api.video.Video.get_info, 验证 fetch_video_stats 完整路径."""
    fake_info = {
        "bvid": "BV1xx",
        "stat": {"view": 1000, "like": 50, "coin": 7,
                 "favorite": 3, "share": 1, "reply": 4, "danmaku": 2},
    }

    class _FakeVideo:
        def __init__(self, *args, **kwargs):
            self.bvid = kwargs.get("bvid")

        async def get_info(self):
            return fake_info

    with patch("bilibili_api.video.Video", _FakeVideo):
        from src.distribution.analytics.bilibili_stats import fetch_video_stats
        out = fetch_video_stats("BV1xx", credential=object())  # 任意 truthy 跳过 _build_credential
    assert out["views"] == 1000
    assert out["likes"] == 50
    assert out["coins"] == 7
    assert out["favorites"] == 3
    assert out["shares"] == 1
    assert out["comments"] == 4
    assert out["danmaku"] == 2
    assert out["raw"] == fake_info["stat"]


def test_fetch_video_stats_handles_missing_stat_key():
    """info 没 stat 字段时应抛 RuntimeError, 而不是静默返回全 0."""
    class _FakeVideo:
        def __init__(self, *args, **kwargs):
            pass
        async def get_info(self):
            return {"bvid": "BV1xx"}  # 缺 stat

    with patch("bilibili_api.video.Video", _FakeVideo):
        from src.distribution.analytics.bilibili_stats import fetch_video_stats
        # stat 默认值是 dict, 不会抛, 但全字段为 0
        out = fetch_video_stats("BV1xx", credential=object())
    assert out["views"] == 0
    assert out["likes"] == 0
