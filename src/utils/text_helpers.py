"""Shared Chinese / CJK character detection utilities."""

import re

_CJK_PATTERN = re.compile(r'[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]')


def contains_chinese(text: str) -> bool:
    """Return True if *text* contains at least one CJK character."""
    return bool(_CJK_PATTERN.search(text or ""))


def first_chinese_index(text: str) -> int:
    """Return the index of the first CJK character, or -1 if none found."""
    m = _CJK_PATTERN.search(text or "")
    return m.start() if m else -1
