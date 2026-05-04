"""analyzer.analyze_comments 单元测试: 不打 LLM, 注入 _llm_fn."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

import pytest

from src.distribution.comments import analyzer
from src.distribution.comments.analyzer import (
    CommentInsight,
    analyze_comments,
    summarize_insights,
    render_report,
    _build_prompt,
    _parse_response,
)


@dataclass
class _FakeComment:
    comment_id: str
    content: str
    nick: str = "测试用户"


# --------------------------------------------------------------------------- #
# _parse_response
# --------------------------------------------------------------------------- #

def test_parse_response_plain_array():
    raw = '[{"id": "x", "sentiment": "positive"}]'
    assert _parse_response(raw) == [{"id": "x", "sentiment": "positive"}]


def test_parse_response_markdown_codeblock():
    raw = '```json\n[{"id": "x"}]\n```'
    assert _parse_response(raw) == [{"id": "x"}]


def test_parse_response_with_leading_text():
    raw = '抱歉, 我返回这个: [{"id": "x"}]  谢谢'
    assert _parse_response(raw) == [{"id": "x"}]


def test_parse_response_empty():
    assert _parse_response("") == []
    assert _parse_response("不是 JSON") == []


# --------------------------------------------------------------------------- #
# analyze_comments 主路径
# --------------------------------------------------------------------------- #

def _make_llm(mapping: dict):
    """造一个 mock LLM, 根据 prompt 里 id 回相应字段."""
    def _fn(prompt: str) -> str:
        items = json.loads(prompt[prompt.find("["):])
        out = []
        for it in items:
            cid = it["id"]
            out.append(mapping.get(cid, {
                "id": cid,
                "sentiment": "neutral",
                "intent": "other",
                "priority": 30,
                "risk": False,
                "topic": None,
            }))
        return json.dumps(out, ensure_ascii=False)
    return _fn


def test_analyze_basic_dispatch():
    comments = [
        ("bilibili", _FakeComment("c1", "讲得真清楚, 谢谢博主!")),
        ("xiaohongshu", _FakeComment("c2", "请问 IDM 模型怎么训练?")),
        ("douyin", _FakeComment("c3", "加微信 abc123 刷量")),
    ]
    fake_llm = _make_llm({
        "bilibili:c1": {"id": "bilibili:c1", "sentiment": "positive",
                        "intent": "praise", "priority": 40, "risk": False,
                        "topic": "好评"},
        "xiaohongshu:c2": {"id": "xiaohongshu:c2", "sentiment": "neutral",
                           "intent": "question", "priority": 80, "risk": False,
                           "topic": "训练"},
        "douyin:c3": {"id": "douyin:c3", "sentiment": "negative",
                      "intent": "spam", "priority": 5, "risk": True,
                      "topic": None},
    })
    insights = analyze_comments(comments, batch_size=10, _llm_fn=fake_llm)
    assert len(insights) == 3
    by_id = {i.comment_id: i for i in insights}
    assert by_id["bilibili:c1"].sentiment == "positive"
    assert by_id["bilibili:c1"].intent == "praise"
    assert by_id["xiaohongshu:c2"].priority == 80
    assert by_id["douyin:c3"].risk is True
    assert by_id["douyin:c3"].topic is None


def test_analyze_invalid_fields_coerced():
    """LLM 返回不在白名单的 sentiment/intent 自动归 neutral/other."""
    comments = [("bilibili", _FakeComment("c1", "评论内容"))]
    fake_llm = _make_llm({
        "bilibili:c1": {"id": "bilibili:c1", "sentiment": "怪",
                        "intent": "未知", "priority": 999, "risk": False,
                        "topic": None},
    })
    insights = analyze_comments(comments, _llm_fn=fake_llm)
    assert len(insights) == 1
    assert insights[0].sentiment == "neutral"
    assert insights[0].intent == "other"
    assert insights[0].priority == 100


def test_analyze_priority_clamp_negative():
    comments = [("bilibili", _FakeComment("c1", "测试"))]
    fake_llm = _make_llm({
        "bilibili:c1": {"id": "bilibili:c1", "sentiment": "neutral",
                        "intent": "other", "priority": -50, "risk": False,
                        "topic": None},
    })
    insights = analyze_comments(comments, _llm_fn=fake_llm)
    assert insights[0].priority == 0


def test_analyze_batching():
    comments = [
        ("bilibili", _FakeComment(f"c{i}", f"评论 {i}")) for i in range(7)
    ]
    call_count = {"n": 0, "sizes": []}
    def fake_llm(prompt: str) -> str:
        call_count["n"] += 1
        items = json.loads(prompt[prompt.find("["):])
        call_count["sizes"].append(len(items))
        return json.dumps([
            {"id": it["id"], "sentiment": "neutral", "intent": "other",
             "priority": 30, "risk": False, "topic": None}
            for it in items
        ], ensure_ascii=False)
    insights = analyze_comments(comments, batch_size=3, _llm_fn=fake_llm)
    assert call_count["n"] == 3
    assert call_count["sizes"] == [3, 3, 1]
    assert len(insights) == 7


def test_analyze_empty():
    assert analyze_comments([]) == []


def test_analyze_llm_failure_skips_batch():
    comments = [
        ("bilibili", _FakeComment("c1", "评论")),
        ("bilibili", _FakeComment("c2", "评论 2")),
    ]
    def fake_llm(prompt: str) -> str:
        raise RuntimeError("API error")
    insights = analyze_comments(comments, _llm_fn=fake_llm)
    assert insights == []


def test_analyze_llm_returns_short_count():
    """LLM 漏返一条; 已返的应正常 coerce 入列."""
    comments = [
        ("bilibili", _FakeComment("c1", "评论 1")),
        ("bilibili", _FakeComment("c2", "评论 2")),
    ]
    def fake_llm(prompt: str) -> str:
        # 只回 c1
        return json.dumps([
            {"id": "bilibili:c1", "sentiment": "positive", "intent": "praise",
             "priority": 50, "risk": False, "topic": None},
        ], ensure_ascii=False)
    insights = analyze_comments(comments, _llm_fn=fake_llm)
    assert len(insights) == 1
    assert insights[0].comment_id == "bilibili:c1"


# --------------------------------------------------------------------------- #
# summarize / render
# --------------------------------------------------------------------------- #

def test_summarize_dist_and_priority():
    insights = [
        CommentInsight("bilibili:c1", "bilibili", "u1", "x", "positive", "praise", 60, False, "好评"),
        CommentInsight("bilibili:c2", "bilibili", "u2", "y", "negative", "troll", 5, False, None),
        CommentInsight("xiaohongshu:c3", "xiaohongshu", "u3", "z", "neutral", "question", 90, False, "训练"),
        CommentInsight("douyin:c4", "douyin", "u4", "ad", "negative", "spam", 0, True, None),
    ]
    s = summarize_insights(insights)
    assert s["total"] == 4
    assert s["sentiment_dist"] == {"positive": 1, "neutral": 1, "negative": 2}
    assert s["intent_dist"]["question"] == 1
    assert s["intent_dist"]["spam"] == 1
    assert s["by_platform"]["bilibili"] == 2
    # priority 排序: 90 > 60 > 5 > 0
    top_ids = [p["comment_id"] for p in s["priority_top"]]
    assert top_ids[0] == "xiaohongshu:c3"
    assert top_ids[-1] == "douyin:c4"
    # risk
    assert len(s["risks"]) == 1
    assert s["risks"][0]["comment_id"] == "douyin:c4"
    # topic
    topic_keys = [t for t, _ in s["top_topics"]]
    assert "好评" in topic_keys
    assert "训练" in topic_keys


def test_render_report_contains_key_sections():
    insights = [
        CommentInsight("b:1", "bilibili", "u", "good", "positive", "praise", 50, False, "好评"),
        CommentInsight("d:1", "douyin", "u", "ad", "negative", "spam", 0, True, None),
    ]
    s = summarize_insights(insights)
    text = render_report(s)
    assert "评论分析报告" in text
    assert "正面 1" in text
    assert "风险评论 (1 条)" in text
    assert "好评" in text
