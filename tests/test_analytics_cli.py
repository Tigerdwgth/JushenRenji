"""测试 CLI 分发与各 fetch 子流程的 mock 集成."""
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest


def _write_papers(tmp_path: Path, papers: list) -> Path:
    p = tmp_path / "published_papers.json"
    p.write_text(json.dumps(papers, ensure_ascii=False), encoding="utf-8")
    return p


def test_parse_platforms_default():
    from src.distribution.analytics.cli import (DEFAULT_PLATFORMS,
                                                _parse_platforms)
    assert _parse_platforms(None) == list(DEFAULT_PLATFORMS)
    assert _parse_platforms("") == list(DEFAULT_PLATFORMS)


def test_parse_platforms_alias_and_unknown():
    from src.distribution.analytics.cli import _parse_platforms
    # xiaohongshu -> xhs
    assert _parse_platforms("xiaohongshu") == ["xhs"]
    # 未知忽略
    assert _parse_platforms("bilibili,unknown,douyin") == ["bilibili", "douyin"]
    # 全未知 -> 默认
    out = _parse_platforms("totally,bogus")
    assert "bilibili" in out


def test_cmd_fetch_dispatches_to_each_platform(tmp_path, capsys):
    """mock 三个 fetch_* 函数, 验证 cli fetch 把数据转发到 stats_store."""
    papers_path = _write_papers(tmp_path, [
        {"title": "T1", "bvid": "BV1xx"},
        {"title": "T2", "bvid": "BV2xx"},
        {"title": "X", "xhs_note_id": "n1", "xhs_xsec_token": "tk"},
    ])
    db_path = tmp_path / "stats.db"

    fake_bili_stats = {"views": 100, "likes": 10, "coins": 1,
                       "favorites": 2, "shares": 3, "comments": 4,
                       "danmaku": 0, "replies": 4, "raw": {}}
    fake_xhs_stats = {"views": 50, "likes": 5, "collects": 2,
                      "comments": 1, "shares": 0, "raw": {}}
    fake_douyin_items = [
        {"post_id": "7100", "title": "DY1", "views": 200, "likes": 20,
         "comments": 3, "shares": 1, "favorites": 0,
         "completion_rate": 30.0, "raw": {}},
    ]

    with patch(
        "src.distribution.analytics.bilibili_stats.fetch_video_stats",
        return_value=fake_bili_stats,
    ) as mock_b, patch(
        "src.distribution.analytics.xhs_stats.fetch_note_stats",
        return_value=fake_xhs_stats,
    ) as mock_x, patch(
        "src.distribution.analytics.douyin_stats.fetch_creator_stats",
        return_value=fake_douyin_items,
    ) as mock_d:
        from src.distribution.analytics.cli import main
        rc = main([
            "fetch",
            "--platforms", "bilibili,xhs,douyin",
            "--published-papers", str(papers_path),
            "--db", str(db_path),
            "--max-posts", "20",
        ])
    captured = capsys.readouterr()
    summary = json.loads(captured.out.strip().splitlines()[-1])
    assert summary["ok"] is True
    plats = {r["platform"] for r in summary["results"]}
    assert plats == {"bilibili", "xhs", "douyin"}
    # bilibili 调用了 2 次 (BV1, BV2), xhs 1 次, douyin 1 次
    assert mock_b.call_count == 2
    assert mock_x.call_count == 1
    assert mock_d.call_count == 1
    assert rc == 0

    # db 应该写了 2 + 1 + 1 = 4 条
    from src.distribution.analytics.stats_store import get_recent
    rows = get_recent(days=1, db_path=db_path)
    assert len(rows) == 4


def test_cmd_fetch_handles_platform_failure(tmp_path, capsys):
    papers = _write_papers(tmp_path, [{"title": "T", "bvid": "BV1xx"}])
    db_path = tmp_path / "stats.db"

    def _boom(*args, **kwargs):
        raise RuntimeError("network down")

    with patch(
        "src.distribution.analytics.bilibili_stats.fetch_video_stats",
        side_effect=_boom,
    ):
        from src.distribution.analytics.cli import main
        rc = main([
            "fetch", "--platforms", "bilibili",
            "--published-papers", str(papers),
            "--db", str(db_path),
        ])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is False
    assert out["results"][0]["fail"] == 1
    assert "network down" in out["results"][0]["errors"][0]
    assert rc == 1


def test_cmd_summary_outputs_table(tmp_path, capsys):
    db_path = tmp_path / "stats.db"
    from src.distribution.analytics.stats_store import upsert_stats
    today = date.today().isoformat()
    upsert_stats("bilibili", "BV1", today, views=100, likes=10,
                 title="hello", db_path=db_path)
    upsert_stats("xhs", "n1", today, views=50, likes=5,
                 title="xhs note", db_path=db_path)

    from src.distribution.analytics.cli import main
    rc = main([
        "summary", "--platforms", "bilibili,xhs",
        "--days", "1", "--db", str(db_path),
    ])
    captured = capsys.readouterr().out
    assert "BILIBILI" in captured.upper()
    assert "BV1" in captured
    assert "n1" in captured
    assert rc == 0


def test_cmd_summary_empty_db(tmp_path, capsys):
    from src.distribution.analytics.cli import main
    db_path = tmp_path / "fresh.db"
    rc = main(["summary", "--platforms", "bilibili",
               "--days", "1", "--db", str(db_path)])
    out = capsys.readouterr().out
    assert "no data" in out.lower()
    assert rc == 0


def test_lark_uploader_stub_raises():
    from src.distribution.analytics.lark_uploader import push_to_lark
    with pytest.raises(NotImplementedError, match="待实现|配置"):
        push_to_lark([{"platform": "bilibili"}])
