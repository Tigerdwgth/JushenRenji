"""reply_engine 单元测试: 跳过条件/违禁词过滤/长度截断/fallback."""
from __future__ import annotations

import os
import sys

import pytest

# 测试不依赖真实 LLM
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _import_engine():
    from src.distribution.comments import reply_engine
    return reply_engine


def test_should_skip_empty():
    re_mod = _import_engine()
    assert re_mod.should_skip("") == "empty"
    assert re_mod.should_skip("   ") == "empty"


def test_should_skip_pure_emoji():
    re_mod = _import_engine()
    # 单个 emoji
    assert re_mod.should_skip("😀") == "too_short_or_emoji"
    # 多个 emoji + 空格
    assert re_mod.should_skip("👍 🎉") == "too_short_or_emoji"


def test_should_skip_single_char():
    re_mod = _import_engine()
    assert re_mod.should_skip("好") == "too_short_or_emoji"


def test_should_skip_too_long():
    re_mod = _import_engine()
    long_text = "好" * 250
    assert re_mod.should_skip(long_text) == "too_long"


def test_should_skip_sensitive():
    re_mod = _import_engine()
    assert re_mod.should_skip("这个内容是广告 求关注加微信") == "sensitive"


def test_should_skip_self_comment():
    re_mod = _import_engine()
    assert re_mod.should_skip("自顶一下", commenter_nick="OP", op_nick="OP") == "self_comment"


def test_generate_reply_normal_path():
    re_mod = _import_engine()
    fake_llm = lambda prompt, content: "感谢支持，这个工作我也很喜欢"
    out = re_mod.generate_reply(
        post_title="LARY 论文解读",
        post_summary="一篇潜动作编码的工作",
        comment_text="讲得很清晰，受益匪浅",
        commenter_nick="user1",
        platform="bilibili",
        _llm_fn=fake_llm,
    )
    assert out is not None
    assert "感谢支持" in out
    assert len(out) <= 100


def test_generate_reply_strips_banned_words():
    re_mod = _import_engine()
    fake_llm = lambda prompt, content: "首次震撼登场, 这是革命性突破!"
    out = re_mod.generate_reply(
        post_title="t", post_summary="", comment_text="不错呀写得真好",
        commenter_nick="u", platform="douyin", _llm_fn=fake_llm,
    )
    assert out is not None
    for w in ("首次", "震撼", "革命", "突破"):
        assert w not in out


def test_generate_reply_truncates_to_platform_limit():
    re_mod = _import_engine()
    long_text = "感谢" * 100
    fake_llm = lambda prompt, content: long_text
    out = re_mod.generate_reply("t", "", "你好你好", "u",
                                platform="douyin", _llm_fn=fake_llm)
    assert out is not None
    assert len(out) <= re_mod.PLATFORM_MAX_CHARS["douyin"]


def test_generate_reply_fallback_on_llm_failure():
    re_mod = _import_engine()
    def boom(prompt, content):
        raise RuntimeError("llm down")
    out = re_mod.generate_reply("t", "", "棒棒哒,继续加油", "u",
                                platform="bilibili", _llm_fn=boom)
    assert out == re_mod.DEFAULT_FALLBACK


def test_generate_reply_fallback_on_empty_llm():
    re_mod = _import_engine()
    fake_llm = lambda prompt, content: ""
    out = re_mod.generate_reply("t", "", "学到了!", "u",
                                platform="xiaohongshu", _llm_fn=fake_llm)
    assert out == re_mod.DEFAULT_FALLBACK


def test_generate_reply_skipped_returns_none():
    re_mod = _import_engine()
    out = re_mod.generate_reply("t", "", "", "u",
                                platform="bilibili", _llm_fn=lambda *a: "x")
    assert out is None


def test_generate_reply_strips_quotes_and_prefix():
    re_mod = _import_engine()
    fake_llm = lambda prompt, content: '回复: "这个观点很赞"'
    out = re_mod.generate_reply("t", "", "我也这么觉得", "u",
                                platform="bilibili", _llm_fn=fake_llm)
    assert out is not None
    assert "回复:" not in out
    assert not out.startswith('"')
