"""评论批量态势分析器.

输入跨平台评论列表, 用 LLM 一次性批量分析每条评论的:
- sentiment (positive/neutral/negative)
- intent (question/praise/spam/troll/suggestion/other)
- priority (0-100, 高=该优先回复)
- risk (是否广告/引战/政治敏感)
- topic (1-3 字主题关键词)

输出 ``CommentInsight`` 列表 + 汇总报告 (情绪/意图分布、热门话题、优先级队列、
风险标注). 不调 reply / 不写 replied_db, 只产出报告供运营决策.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CommentInsight:
    comment_id: str
    platform: str
    nick: str
    content: str
    sentiment: str        # positive / neutral / negative
    intent: str           # question / praise / spam / troll / suggestion / other
    priority: int         # 0-100
    risk: bool
    topic: Optional[str]


_VALID_SENT = {"positive", "neutral", "negative"}
_VALID_INTENT = {"question", "praise", "spam", "troll", "suggestion", "other"}


def _build_prompt(items: List[Dict[str, str]]) -> str:
    return (
        "你是视频博主的运营助手, 对一批评论批量做态势分析. 对每条评论严格返回 JSON 对象:\n"
        '{"id": str, "sentiment": "positive"|"neutral"|"negative", '
        '"intent": "question"|"praise"|"spam"|"troll"|"suggestion"|"other", '
        '"priority": 0-100 整数 (真问题/疑问 60-90, 真诚表扬 30-50, 灌水/纯表情 0-15), '
        '"risk": true|false (广告/引战/政治敏感为 true), '
        '"topic": 1-3 字主题关键词或 null}\n'
        "返回纯 JSON 数组, 数量与顺序严格对齐输入, 不要加任何说明文字或 markdown 代码块.\n\n"
        f"评论列表 (共 {len(items)} 条):\n"
        + json.dumps(items, ensure_ascii=False)
    )


def _parse_response(raw: str) -> List[dict]:
    """从 LLM 原始返回里解出 JSON 数组."""
    if not raw:
        return []
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
        s = s.strip()
        if s.startswith("json"):
            s = s[4:].strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        l = s.find("[")
        r = s.rfind("]")
        if l >= 0 and r > l:
            try:
                data = json.loads(s[l:r + 1])
            except json.JSONDecodeError:
                logger.warning("[analyzer] LLM 返回非 JSON, raw=%s", raw[:200])
                return []
        else:
            logger.warning("[analyzer] LLM 返回非 JSON 且无 [...]: %s", raw[:200])
            return []
    return data if isinstance(data, list) else []


def _coerce(item: dict, lookup: Dict[str, dict]) -> Optional[CommentInsight]:
    cid = str(item.get("id") or "")
    src = lookup.get(cid)
    if src is None:
        return None
    sentiment = str(item.get("sentiment", "neutral")).lower()
    if sentiment not in _VALID_SENT:
        sentiment = "neutral"
    intent = str(item.get("intent", "other")).lower()
    if intent not in _VALID_INTENT:
        intent = "other"
    try:
        priority = max(0, min(100, int(item.get("priority", 30))))
    except (ValueError, TypeError):
        priority = 30
    risk = bool(item.get("risk", False))
    topic = item.get("topic")
    if topic == "null" or topic == "" or not isinstance(topic, str):
        topic = None
    return CommentInsight(
        comment_id=cid,
        platform=src["platform"],
        nick=src["nick"],
        content=src["content"],
        sentiment=sentiment,
        intent=intent,
        priority=priority,
        risk=risk,
        topic=topic,
    )


def _default_llm_fn() -> Callable[[str], str]:
    try:
        from src.llm_tools.llm_agent import create_chat_completion
    except ImportError:  # pragma: no cover
        from llm_tools.llm_agent import create_chat_completion  # type: ignore

    def _fn(prompt: str) -> str:
        return create_chat_completion(prompt, model="deepseek-chat")
    return _fn


def analyze_comments(comments: List[Tuple[str, Any]],
                     *,
                     batch_size: int = 30,
                     _llm_fn: Optional[Callable[[str], str]] = None
                     ) -> List[CommentInsight]:
    """批量分析评论.

    Args:
        comments: ``[(platform, comment_obj), ...]``;
                  ``comment_obj`` 需有 ``comment_id`` / ``content`` / ``nick`` 属性.
        batch_size: 每个 LLM 调用最多多少条评论.
        _llm_fn: 可注入 mock; ``str -> str``.

    Returns:
        ``CommentInsight`` 列表; 顺序不一定保留 (LLM 偶发漏返回会跳过).
    """
    if _llm_fn is None:
        _llm_fn = _default_llm_fn()
    insights: List[CommentInsight] = []
    if not comments:
        return insights

    items_all: List[Dict[str, str]] = []
    lookup: Dict[str, dict] = {}
    for platform, c in comments:
        raw_id = str(getattr(c, "comment_id", "") or "")
        # 跨平台 id 去重: 总用 platform: 前缀
        cid = f"{platform}:{raw_id}" if raw_id else f"{platform}:{len(lookup)}"
        items_all.append({
            "id": cid,
            "platform": platform,
            "content": (getattr(c, "content", "") or "")[:300],
        })
        lookup[cid] = {
            "platform": platform,
            "nick": getattr(c, "nick", "匿名"),
            "content": getattr(c, "content", ""),
        }

    for i in range(0, len(items_all), batch_size):
        batch = items_all[i:i + batch_size]
        prompt = _build_prompt(batch)
        try:
            raw = _llm_fn(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[analyzer] LLM 调用失败 batch=%d: %s",
                           i // batch_size, exc)
            continue
        parsed = _parse_response(raw)
        if len(parsed) != len(batch):
            logger.warning("[analyzer] batch=%d 数量不齐: 期望 %d 实际 %d",
                           i // batch_size, len(batch), len(parsed))
        for item in parsed:
            ins = _coerce(item, lookup)
            if ins is not None:
                insights.append(ins)
    return insights


def summarize_insights(insights: List[CommentInsight]) -> Dict[str, Any]:
    """聚合统计."""
    sentiment_dist = {"positive": 0, "neutral": 0, "negative": 0}
    intent_dist: Dict[str, int] = {}
    topic_count: Dict[str, int] = {}
    by_platform: Dict[str, int] = {}
    risks: List[dict] = []
    for ins in insights:
        sentiment_dist[ins.sentiment] = sentiment_dist.get(ins.sentiment, 0) + 1
        intent_dist[ins.intent] = intent_dist.get(ins.intent, 0) + 1
        if ins.topic:
            topic_count[ins.topic] = topic_count.get(ins.topic, 0) + 1
        if ins.risk:
            risks.append(asdict(ins))
        by_platform[ins.platform] = by_platform.get(ins.platform, 0) + 1
    top_topics = sorted(topic_count.items(),
                        key=lambda kv: kv[1], reverse=True)[:10]
    priority_top = sorted(insights, key=lambda i: i.priority, reverse=True)[:10]
    return {
        "total": len(insights),
        "by_platform": by_platform,
        "sentiment_dist": sentiment_dist,
        "intent_dist": intent_dist,
        "top_topics": top_topics,
        "priority_top": [asdict(i) for i in priority_top],
        "risks": risks,
    }


def render_report(summary: Dict[str, Any]) -> str:
    """ASCII 报告."""
    lines: List[str] = []
    total = summary.get("total", 0) or 1
    lines.append(f"评论分析报告 (共 {summary.get('total', 0)} 条)")
    lines.append("=" * 60)
    bp = summary.get("by_platform", {})
    if bp:
        lines.append("按平台: " + " ".join(f"{k}={v}" for k, v in bp.items()))
    sd = summary.get("sentiment_dist", {})
    lines.append(
        f"情绪分布: 正面 {sd.get('positive', 0)} ({sd.get('positive', 0) * 100 / total:.0f}%) "
        f"中性 {sd.get('neutral', 0)} ({sd.get('neutral', 0) * 100 / total:.0f}%) "
        f"负面 {sd.get('negative', 0)} ({sd.get('negative', 0) * 100 / total:.0f}%)"
    )
    if summary.get("intent_dist"):
        ids = sorted(summary["intent_dist"].items(),
                     key=lambda kv: kv[1], reverse=True)
        lines.append("意图分布: " + " ".join(f"{k}={v}" for k, v in ids))
    if summary.get("top_topics"):
        lines.append("热门话题:")
        for topic, cnt in summary["top_topics"]:
            lines.append(f"  {topic}: {cnt}")
    if summary.get("priority_top"):
        lines.append("\n优先级 Top 10 (建议先回复):")
        for i, ins in enumerate(summary["priority_top"][:10], 1):
            content = (ins.get("content") or "").replace("\n", " ")[:60]
            lines.append(
                f"  {i:>2}. [{ins.get('priority', 0):>3}] "
                f"{ins.get('platform', ''):>10} @{(ins.get('nick') or '')[:10]:<10} "
                f"{ins.get('intent', ''):<10} | {content}"
            )
    if summary.get("risks"):
        lines.append(f"\n风险评论 ({len(summary['risks'])} 条):")
        for ins in summary["risks"]:
            content = (ins.get("content") or "").replace("\n", " ")[:60]
            lines.append(
                f"  [{ins.get('platform', '')}] @{(ins.get('nick') or '')[:10]} | {content}"
            )
    return "\n".join(lines)
