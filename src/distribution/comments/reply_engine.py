"""统一回复生成器.

走 llm_tools.llm_agent.create_chat_completion + prompts.prompts_dict
[generate_comment_reply], 然后做三层兜底:
1. 跳过条件: 纯表情/单字/commenter == OP/含敏感词/文本过长(>200字)
2. 字符过滤 + 长度截断 (B站100字/小红书100字/抖音60字)
3. LLM 失败时 fallback "谢谢支持~"

返回 None 表示跳过, 调用方应略过该评论.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# 平台单条回复字符上限
PLATFORM_MAX_CHARS = {
    "bilibili": 100,
    "xiaohongshu": 100,
    "douyin": 60,
}

DEFAULT_FALLBACK = "谢谢支持~"

# 敏感词黑名单 (粗筛, LLM 进一步把关)
SENSITIVE_WORDS = {
    "傻逼", "操你", "去死", "滚", "煞笔", "脑残",
    "习近平", "毛泽东", "共产党", "六四",
    "法轮", "翻墙", "vpn",
    "代刷", "刷赞", "广告", "加微信",
}

# 回复中禁止出现的"夸张"词 (符合用户活泼但不浮夸的人设)
BANNED_OUTPUT_WORDS = {
    "首次", "突破", "震撼", "颠覆", "革命", "全球首发",
    "前所未有", "划时代", "里程碑",
}

# 表情字符范围
_EMOJI_PATTERN = re.compile(
    r"[🌀-🫿☀-➿🀀-🀯"
    r"‍️]+"
)


def _strip_emoji(text: str) -> str:
    return _EMOJI_PATTERN.sub("", text or "")


def is_pure_emoji(text: str) -> bool:
    """整段除去表情/空白后空 → 视为纯表情."""
    if not text:
        return True
    return _strip_emoji(text).strip() == ""


def is_sensitive(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(w in text or w.lower() in low for w in SENSITIVE_WORDS)


def should_skip(comment_text: str,
                commenter_nick: Optional[str] = None,
                op_nick: Optional[str] = None,
                max_input_chars: int = 200) -> Optional[str]:
    """返回跳过原因 (str) 或 None (不跳过)."""
    if comment_text is None:
        return "empty"
    text = comment_text.strip()
    if not text:
        return "empty"
    if len(text) > max_input_chars:
        return "too_long"
    # 单字（去 emoji 后 <= 1 字符）
    cleaned = _strip_emoji(text).strip()
    if len(cleaned) <= 1:
        return "too_short_or_emoji"
    if is_sensitive(text):
        return "sensitive"
    if commenter_nick and op_nick and commenter_nick == op_nick:
        return "self_comment"
    return None


def _sanitize_output(text: str, max_chars: int) -> str:
    """字符过滤 + 长度截断."""
    if not text:
        return ""
    out = text.strip()
    # 反复 strip 引号 + 去 "回复:" 前缀, 直到稳定 (LLM 偶尔会嵌套包裹)
    _quote_chars = '"' + "'" + '`' + chr(0x201C) + chr(0x201D) + chr(0x2018) + chr(0x2019)
    for _ in range(3):
        prev = out
        out = out.strip().strip(_quote_chars).strip()
        out = re.sub(r"^回复[:：\s]*", "", out)
        out = out.strip(_quote_chars).strip()
        if out == prev:
            break
    # 移除多余换行
    out = re.sub(r"\s*\n+\s*", " ", out)
    # 替换违禁夸张词
    for w in BANNED_OUTPUT_WORDS:
        out = out.replace(w, "")
    out = re.sub(r"\s+", " ", out).strip()
    # 长度截断 (字符级, 中英文统一按 len)
    if len(out) > max_chars:
        out = out[: max_chars - 1].rstrip() + "…"
    return out


def generate_reply(post_title: str,
                   post_summary: str,
                   comment_text: str,
                   commenter_nick: str,
                   platform: str = "bilibili",
                   op_nick: Optional[str] = None,
                   _llm_fn=None) -> Optional[str]:
    """生成对单条评论的回复.

    Args:
        post_title: 视频标题
        post_summary: 视频简介(可空)
        comment_text: 评论原文
        commenter_nick: 评论者昵称
        platform: bilibili / xiaohongshu / douyin (决定字符上限)
        op_nick: 视频博主昵称, 用于检测自评
        _llm_fn: 测试时注入 mock LLM, 默认走 create_chat_completion

    Returns:
        str: 可回帖的清洗后文本
        None: 应跳过 (跳过原因走 logger.info)
    """
    skip = should_skip(comment_text, commenter_nick=commenter_nick,
                       op_nick=op_nick)
    if skip:
        logger.info("[reply_engine] skip comment (%s): %r", skip,
                    (comment_text or "")[:60])
        return None

    max_chars = PLATFORM_MAX_CHARS.get(platform, 80)

    # 取 prompt
    try:
        from src.llm_tools.prompts import prompts_dict
    except ImportError:  # pragma: no cover
        from llm_tools.prompts import prompts_dict  # type: ignore
    prompt_tpl = prompts_dict.get(
        "generate_comment_reply",
        "你是一个活泼的科普博主, 用一两句话友好回复读者评论.",
    )

    user_payload = (
        f"视频标题: {post_title or '(未提供)'}\n"
        f"视频简介: {(post_summary or '')[:300]}\n"
        f"评论者: {commenter_nick or '匿名'}\n"
        f"评论内容: {comment_text}\n"
        f"平台: {platform}, 字数限制: {max_chars} 字以内.\n"
        "请直接给出回复文本, 不要加引号, 不要加 '回复:' 前缀."
    )

    llm_fn = _llm_fn
    if llm_fn is None:
        try:
            from src.llm_tools.llm_agent import create_chat_completion
        except ImportError:  # pragma: no cover
            from llm_tools.llm_agent import create_chat_completion  # type: ignore
        llm_fn = create_chat_completion

    raw = ""
    try:
        raw = llm_fn(prompt_tpl, user_payload) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("[reply_engine] LLM 调用失败, 使用 fallback: %s", exc)
        raw = ""

    cleaned = _sanitize_output(raw, max_chars)
    if not cleaned:
        cleaned = DEFAULT_FALLBACK
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned
