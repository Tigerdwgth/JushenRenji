"""Hugging Face Daily Papers 数据源。

调 ``https://huggingface.co/api/daily_papers`` 拿当日热门论文，转成 ``Candidate``。

公开 API:
    fetch_hf_daily(limit: int = 30) -> list[Candidate]
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_HF_DAILY_URL = "https://huggingface.co/api/daily_papers"
_HTTP_TIMEOUT = 20


def _normalize_arxiv_id(raw: str) -> Optional[str]:
    """HF 返回的 paper.id 一般是 arxiv id（如 2410.11758），偶有 vN 后缀。"""
    if not raw:
        return None
    m = re.search(r"([0-9]{4}\.[0-9]{4,6})", str(raw))
    return m.group(1) if m else None


def _to_candidate_dict(item: dict) -> Optional[dict]:
    """把 HF 单条 daily paper item 转 Candidate 构造字典。

    HF 返回结构（节选）::
        {"paper": {"id": "...", "title": "...", "summary": "...",
                    "upvotes": int, "githubRepo": str|null,
                    "projectPage": str|null, "publishedAt": iso8601},
         "publishedAt": iso8601, "title": "...", "summary": "..."}
    """
    paper = item.get("paper") or {}
    arxiv_id = _normalize_arxiv_id(paper.get("id") or "")
    if not arxiv_id:
        return None
    title = (paper.get("title") or item.get("title") or "").strip()
    abstract = (paper.get("summary") or item.get("summary") or "").strip()
    upvotes = int(paper.get("upvotes") or 0)
    github_repo = paper.get("githubRepo") or None
    project_page = paper.get("projectPage") or None
    published_at = (paper.get("publishedAt") or item.get("publishedAt") or "")[:10]
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "submitted_date": published_at,
        "upvotes": upvotes,
        "github_repo": github_repo,
        "project_page": project_page,
        "source": "hf",
    }


def fetch_hf_daily(limit: int = 30) -> list:
    """拉 HF Daily Papers，返回 list[Candidate]。

    失败（网络/解析）返回空列表，调用方不应因此整体失败。
    """
    # 延迟导入避免循环
    from src.paper_discovery import Candidate

    try:
        params = {"limit": int(limit)} if limit else {}
        resp = requests.get(_HF_DAILY_URL, params=params, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        items = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("[discovery.hf] fetch failed: %s", e)
        return []

    if not isinstance(items, list):
        logger.warning("[discovery.hf] unexpected response shape: %s",
                       type(items).__name__)
        return []

    out = []
    seen = set()
    for item in items[: int(limit) if limit else None]:
        if not isinstance(item, dict):
            continue
        d = _to_candidate_dict(item)
        if not d:
            continue
        if d["arxiv_id"] in seen:
            continue
        seen.add(d["arxiv_id"])
        out.append(Candidate(**d))
    logger.info("[discovery.hf] got %d candidates", len(out))
    return out
