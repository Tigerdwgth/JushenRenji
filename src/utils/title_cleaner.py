import re
from typing import Iterable


EXAGGERATED_TITLE_PHRASES = (
    "首次",
    "首个",
    "首款",
    "第一",
    "突破",
    "新突破",
    "最新进展",
    "重磅",
    "炸裂",
    "震撼",
    "颠覆",
    "必看",
)


def _normalize_title(text: str) -> str:
    normalized = re.sub(r"[：:|]+", " ", text or "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" ，。！？、;；-_")


def remove_exaggerated_phrases(title: str, phrases: Iterable[str] = EXAGGERATED_TITLE_PHRASES) -> str:
    cleaned = title or ""
    for phrase in sorted(phrases, key=len, reverse=True):
        cleaned = cleaned.replace(phrase, "")
    return _normalize_title(cleaned)


def sanitize_generated_title(title: str, fallback: str = "论文解读") -> str:
    cleaned = remove_exaggerated_phrases(title)
    return cleaned or fallback
