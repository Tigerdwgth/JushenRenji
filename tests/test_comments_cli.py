"""cli dispatching 测试: 各 platform handler 调用检查."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def fake_published(tmp_path):
    p = tmp_path / "published.json"
    p.write_text(json.dumps([
        {"arxiv_id": "2501.00001", "title": "测试论文",
         "date": datetime.now().strftime("%Y-%m-%d"),
         "video_path": "/x.mp4"},
    ]), encoding="utf-8")
    return str(p)


@pytest.fixture
def fake_post_ids(tmp_path):
    p = tmp_path / "post_ids.json"
    p.write_text(json.dumps({
        "2501.00001": {
            "bilibili": {"bv": "BV1zz", "title": "测试 B站标题"},
            "xiaohongshu": {"note_id": "n1", "xsec_token": "tk", "title": "..."},
            "douyin": {"aweme_url": "https://www.douyin.com/video/x", "title": "..."},
        }
    }), encoding="utf-8")
    return str(p)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db = str(tmp_path / "replied.db")
    monkeypatch.setenv("JSR_COMMENTS_DB", db)
    # 强制 reload replied_db 让它读新环境变量
    import importlib
    from src.distribution.comments import replied_db as r
    importlib.reload(r)
    return db


def test_cli_dry_run_dispatches_all_platforms(fake_published, fake_post_ids,
                                              isolated_db):
    from src.distribution.comments import cli

    fake_bili_comment = MagicMock(comment_id="111", content="赞", nick="A",
                                   ctime=int(datetime.now().timestamp()),
                                   aid=1, parent_id="0", rpid=111)
    fake_xhs_comment = MagicMock(comment_id="222", content="干货",
                                  nick="B", ctime=0, note_id="n1",
                                  parent_id=None)
    fake_dy_comment = MagicMock(comment_id="333", content="支持",
                                nick="C", ctime=0,
                                aweme_url="https://www.douyin.com/video/x")

    with patch("src.distribution.comments.bilibili_comments.pull_recent_comments",
               return_value=[fake_bili_comment]), \
         patch("src.distribution.comments.xhs_comments.pull_recent_comments",
               return_value=[fake_xhs_comment]), \
         patch("src.distribution.comments.douyin_comments.pull_recent_comments",
               return_value=[fake_dy_comment]), \
         patch("src.distribution.comments.cli.generate_reply",
               return_value="谢谢~"), \
         patch("src.distribution.comments.bilibili_comments.reply_to_comment") as bili_send, \
         patch("src.distribution.comments.xhs_comments.reply_to_comment") as xhs_send, \
         patch("src.distribution.comments.douyin_comments.reply_to_comment") as dy_send:
        rc = cli.main([
            "--platforms", "bilibili,xiaohongshu,douyin",
            "--published-json", fake_published,
            "--post-ids-json", fake_post_ids,
            "--max-posts", "5",
            "--max-age-hours", "999",
            "--sleep-min", "0", "--sleep-max", "0",
            "--dry-run",
        ])
    assert rc == 0
    # dry-run 不应真的调 reply_to_comment
    bili_send.assert_not_called()
    xhs_send.assert_not_called()
    dy_send.assert_not_called()


def test_cli_no_dry_run_invokes_reply(fake_published, fake_post_ids,
                                      isolated_db):
    from src.distribution.comments import cli

    fake_c = MagicMock(comment_id="111", content="赞", nick="A",
                       ctime=int(datetime.now().timestamp()),
                       aid=1, parent_id="0", rpid=111)

    with patch("src.distribution.comments.bilibili_comments.pull_recent_comments",
               return_value=[fake_c]), \
         patch("src.distribution.comments.xhs_comments.pull_recent_comments",
               return_value=[]), \
         patch("src.distribution.comments.douyin_comments.pull_recent_comments",
               return_value=[]), \
         patch("src.distribution.comments.cli.generate_reply",
               return_value="谢谢~"), \
         patch("src.distribution.comments.bilibili_comments.reply_to_comment",
               return_value=True) as bili_send:
        rc = cli.main([
            "--platforms", "bilibili",
            "--published-json", fake_published,
            "--post-ids-json", fake_post_ids,
            "--max-posts", "5",
            "--max-age-hours", "999",
            "--sleep-min", "0", "--sleep-max", "0",
            "--no-dry-run",
        ])
    assert rc == 0
    bili_send.assert_called_once()


def test_cli_skips_when_no_mapping(fake_published, tmp_path,
                                   isolated_db):
    from src.distribution.comments import cli

    empty_post_ids = tmp_path / "empty.json"
    empty_post_ids.write_text("{}", encoding="utf-8")

    with patch("src.distribution.comments.bilibili_comments.pull_recent_comments") as pp:
        rc = cli.main([
            "--platforms", "bilibili",
            "--published-json", fake_published,
            "--post-ids-json", str(empty_post_ids),
            "--max-age-hours", "999",
            "--dry-run",
        ])
    assert rc == 0
    pp.assert_not_called()


def test_cli_unknown_platform_returns_error():
    from src.distribution.comments import cli
    rc = cli.main(["--platforms", "twitter", "--dry-run"])
    assert rc == 2
