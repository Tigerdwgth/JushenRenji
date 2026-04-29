"""bilibili_comments mock 测试: 验证调用参数."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _async_runner(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_pull_recent_comments_filters_by_since():
    """ctime < since_ts 的应被过滤掉."""
    from src.distribution.comments import bilibili_comments as bc

    now = int(datetime.now().timestamp())
    fake_page = {
        "replies": [
            {"rpid": 1, "parent": 0, "ctime": now,
             "content": {"message": "新评论"}, "member": {"uname": "A"}},
            {"rpid": 2, "parent": 0, "ctime": now - 86400 * 30,
             "content": {"message": "老评论"}, "member": {"uname": "B"}},
        ],
        "cursor": {"is_end": True, "paginationReply": {"nextOffset": ""}},
    }

    async def fake_get_lazy(**kwargs):
        return fake_page

    fake_v = MagicMock()
    async def fake_get_aid():
        return 12345
    fake_v.get_aid = fake_get_aid

    with patch.object(bc, "_build_credential", return_value=None), \
         patch("bilibili_api.video.Video", return_value=fake_v), \
         patch("bilibili_api.comment.get_comments_lazy", side_effect=fake_get_lazy):
        comments = bc.pull_recent_comments("BV1abc",
                                           datetime.fromtimestamp(now - 60))
    assert len(comments) == 1
    assert comments[0].nick == "A"
    assert comments[0].aid == 12345


def test_reply_to_comment_passes_aid_and_rpid():
    from src.distribution.comments import bilibili_comments as bc

    captured = {}

    async def fake_send(**kwargs):
        captured.update(kwargs)
        return {"success_action": 0, "rpid": 999}

    fake_v = MagicMock()
    async def fake_get_aid():
        return 7777
    fake_v.get_aid = fake_get_aid

    fake_cred = object()
    with patch.object(bc, "_build_credential", return_value=fake_cred), \
         patch("bilibili_api.video.Video", return_value=fake_v), \
         patch("bilibili_api.comment.send_comment", side_effect=fake_send):
        ok = bc.reply_to_comment("BV1abc", "12345", "感谢支持~")
    assert ok is True
    assert captured["oid"] == 7777
    assert captured["root"] == 12345
    assert captured["parent"] == 12345
    assert captured["text"] == "感谢支持~"
    assert captured["credential"] is fake_cred


def test_reply_to_comment_rejects_bad_parent():
    from src.distribution.comments import bilibili_comments as bc
    assert bc.reply_to_comment("BV1abc", "not-int", "x") is False


def test_reply_to_comment_returns_false_when_no_credential():
    from src.distribution.comments import bilibili_comments as bc

    fake_v = MagicMock()
    async def fake_get_aid():
        return 1
    fake_v.get_aid = fake_get_aid

    with patch.object(bc, "_build_credential", return_value=None), \
         patch("bilibili_api.video.Video", return_value=fake_v):
        ok = bc.reply_to_comment("BV1abc", "1", "x")
    assert ok is False
