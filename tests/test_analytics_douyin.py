"""测试 src/distribution/analytics/douyin_stats.py + helper."""
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


def _make_proc(stdout: str, returncode: int = 0, stderr: str = ""):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.stdout = stdout
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


def test_fetch_creator_stats_returns_items(tmp_path):
    sau_dir = tmp_path / "sau"
    venv_py = sau_dir / ".venv/bin/python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/usr/bin/env python3\n")
    venv_py.chmod(0o755)
    cookie = tmp_path / "cookies.json"
    cookie.write_text("{}")

    items = [
        {"post_id": "7123", "title": "测试 1",
         "views": 100, "likes": 10, "comments": 2, "shares": 1,
         "favorites": 0, "completion_rate": 50.0, "raw": {}},
        {"post_id": "7124", "title": "测试 2",
         "views": 200, "likes": 20, "comments": 5, "shares": 3,
         "favorites": 1, "completion_rate": 60.0, "raw": {}},
    ]
    proc = _make_proc(stdout=json.dumps({"ok": True, "items": items}) + "\n")
    with patch("subprocess.run", return_value=proc) as mock_run:
        from src.distribution.analytics.douyin_stats import fetch_creator_stats
        out = fetch_creator_stats(
            account_file=str(cookie), sau_dir=str(sau_dir), max_posts=5,
        )
    assert out == items
    cmd = mock_run.call_args.args[0]
    assert "src.distribution.analytics.douyin_stats_helper" in cmd
    assert "--max-posts" in cmd
    assert "5" in cmd
    assert "--mode" in cmd
    assert "auto" in cmd


def test_fetch_creator_stats_raises_on_no_cookie(tmp_path):
    sau_dir = tmp_path / "sau"
    sau_dir.mkdir()
    from src.distribution.analytics.douyin_stats import (DouyinStatsError,
                                                        fetch_creator_stats)
    with pytest.raises(DouyinStatsError, match="cookie 文件不存在"):
        fetch_creator_stats(
            account_file=str(tmp_path / "missing.json"),
            sau_dir=str(sau_dir),
        )


def test_fetch_creator_stats_raises_on_helper_error(tmp_path):
    sau_dir = tmp_path / "sau"
    sau_dir.mkdir()
    cookie = tmp_path / "cookies.json"
    cookie.write_text("{}")
    proc = _make_proc(
        stdout=json.dumps({"ok": False, "error": "未抓到任何作品"}) + "\n",
        returncode=1,
    )
    with patch("subprocess.run", return_value=proc):
        from src.distribution.analytics.douyin_stats import (DouyinStatsError,
                                                            fetch_creator_stats)
        with pytest.raises(DouyinStatsError, match="未抓到"):
            fetch_creator_stats(
                account_file=str(cookie), sau_dir=str(sau_dir),
            )


def test_helper_normalize_xhr_item_extracts_fields():
    from src.distribution.analytics.douyin_stats_helper import _normalize_xhr_item
    raw = {
        "aweme_id": "7100",
        "desc": "Hello world",
        "statistics": {
            "play_count": 1000,
            "digg_count": 50,
            "comment_count": 5,
            "share_count": 2,
            "collect_count": 1,
            "avg_play_finish_rate": 0.45,  # 0~1 -> 45%
        },
    }
    out = _normalize_xhr_item(raw)
    assert out is not None
    assert out["post_id"] == "7100"
    assert out["title"] == "Hello world"
    assert out["views"] == 1000
    assert out["likes"] == 50
    assert out["comments"] == 5
    assert out["shares"] == 2
    assert out["favorites"] == 1
    assert out["completion_rate"] == 45.0


def test_helper_normalize_xhr_item_skips_empty():
    from src.distribution.analytics.douyin_stats_helper import _normalize_xhr_item
    # 全 0 的应被过滤掉
    assert _normalize_xhr_item({"aweme_id": "7", "desc": "x"}) is None


def test_helper_extract_xhr_items_handles_nested_lists():
    from src.distribution.analytics.douyin_stats_helper import _extract_xhr_items
    payload = {
        "data": {
            "aweme_list": [
                {"aweme_id": "1", "statistics": {"play_count": 100,
                                                 "digg_count": 10,
                                                 "comment_count": 1,
                                                 "share_count": 0,
                                                 "collect_count": 0}},
                {"aweme_id": "2", "statistics": {"play_count": 200,
                                                 "digg_count": 20,
                                                 "comment_count": 2,
                                                 "share_count": 1,
                                                 "collect_count": 0}},
            ]
        }
    }
    items = _extract_xhr_items(payload)
    assert len(items) == 2
    assert items[0]["post_id"] == "1"
    assert items[0]["views"] == 100
    assert items[1]["views"] == 200


def test_helper_parse_dom_card():
    from src.distribution.analytics.douyin_stats_helper import _parse_dom_card
    text = "VLA论文解读 播放 1.2万 点赞 234 评论 12 分享 5"
    out = _parse_dom_card(text)
    assert out["views"] == 12000
    assert out["likes"] == 234
    assert out["comments"] == 12
    assert out["shares"] == 5


def test_helper_parse_dom_card_partial():
    from src.distribution.analytics.douyin_stats_helper import _parse_dom_card
    text = "测试视频 播放 100"
    out = _parse_dom_card(text)
    assert out["views"] == 100
    assert out["likes"] == 0
    assert out["comments"] == 0
    assert out["shares"] == 0


def test_helper_dedup_picks_highest_views():
    from src.distribution.analytics.douyin_stats_helper import _dedup_by_post_id
    items = [
        {"post_id": "a", "views": 100, "likes": 1},
        {"post_id": "a", "views": 500, "likes": 2},  # 同 id, 数据更全
        {"post_id": "b", "views": 50, "likes": 1},
    ]
    out = _dedup_by_post_id(items)
    by_id = {it["post_id"]: it for it in out}
    assert by_id["a"]["views"] == 500
    assert by_id["a"]["likes"] == 2
    assert by_id["b"]["views"] == 50
