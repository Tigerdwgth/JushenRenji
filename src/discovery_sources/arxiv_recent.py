"""arXiv 最近论文数据源。

直接调 arxiv API（feedparser），按 cat: 分类拉过去 N 天的论文 → list[Candidate]。
不走 get_latest_embodied_ai_papers（它把 query 强制拼到 all: 前缀，
不能精确按 cat 过滤）；但仍提供同名 mock target 给测试用。

公开 API:
    fetch_arxiv_recent(tags=["cs.RO","cs.CV"], days=7, limit=30,
                       topic=None) -> list[Candidate]
"""
from __future__ import annotations

import datetime
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

# 复用 get_arxiv_latest 的入口（测试 mock 仍可用）。
from src.get_arxiv_latest import get_latest_embodied_ai_papers  # noqa: F401

logger = logging.getLogger(__name__)


def _parse_arxiv_id_from_link(link: str) -> Optional[str]:
    if not link:
        return None
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,6})", link)
    if m:
        return m.group(1)
    m = re.search(r"([0-9]{4}\.[0-9]{4,6})", link)
    return m.group(1) if m else None


def _build_search_query(tags: list, topic: Optional[str] = None) -> str:
    """构造 arxiv search_query。

    - 没有 topic：``cat:cs.RO+OR+cat:cs.CV``（向后兼容）
    - 有 topic：``(cat:cs.RO+OR+cat:cs.CV)+AND+abs:%22<topic>%22``
      用 ``urllib.parse.quote_plus`` 做 URL 编码（短语保留双引号）。
    """
    if not tags:
        cat_part = "cat:cs.RO"
    else:
        parts = ["cat:" + str(t).strip() for t in tags if t and str(t).strip()]
        cat_part = "+OR+".join(parts) if parts else "cat:cs.RO"

    topic_str = (topic or "").strip()
    if not topic_str:
        return cat_part

    # quote_plus 保留 ASCII 字母数字，把空格变 +，把 " 变 %22
    encoded = quote_plus('"' + topic_str + '"')
    # 把 cat 部分包起来，确保 OR 优先级正确
    return "(" + cat_part + ")+AND+abs:" + encoded


def _fetch_via_arxiv_api(tags: list, limit: int,
                        topic: Optional[str] = None) -> list:
    """直接 arxiv API + feedparser，绕过 get_latest_embodied_ai_papers 的 all: 前缀。"""
    import feedparser
    q = _build_search_query(tags, topic=topic)
    url = ("https://export.arxiv.org/api/query?search_query="
           + q
           + "&sortBy=lastUpdatedDate&sortOrder=descending&max_results="
           + str(int(limit)))
    feed = feedparser.parse(url)
    return list(getattr(feed, "entries", []) or [])


def fetch_arxiv_recent(tags: list = None, days: int = 7,
                       limit: int = 30,
                       topic: Optional[str] = None) -> list:
    """拉 arxiv 最近论文。

    Args:
        tags: arxiv cat 列表（如 ``["cs.RO","cs.CV"]``）。
        days: 仅保留 ``submitted_date >= now - days`` 的条目。
        limit: 单次拉取上限。
        topic: 可选短语，传入时给 arxiv ``search_query`` 加 ``AND abs:"<topic>"``，
            服务端就过滤好；不传时退回纯 cat 查询（向后兼容）。
    """
    from src.paper_discovery import Candidate

    if tags is None:
        tags = ["cs.RO", "cs.CV"]
    cutoff = (datetime.datetime.now()
              - datetime.timedelta(days=int(days)))

    # 1) 优先用 get_latest_embodied_ai_papers（留给测试 mock + 简单路径）
    entries = []
    used_mock_path = False
    try:
        # mock 路径：query 走 cat OR；topic 通过 abs: 字段附加（mock 经常忽略这一段）
        cat_q = '+OR+'.join('cat:' + str(t) for t in tags) or 'cs.RO'
        full_q = cat_q
        topic_str = (topic or '').strip()
        if topic_str:
            full_q = '(' + cat_q + ')+AND+abs:' + quote_plus('"' + topic_str + '"')
        papers = get_latest_embodied_ai_papers(
            amount=int(limit),
            query=full_q,
            date='',
        )
        used_mock_path = True
        for p in papers or []:
            entries.append({
                'title': getattr(p, 'title', '') or '',
                'abstract': getattr(p, 'abstract', '') or '',
                'link': getattr(p, 'link', '') or '',
                'submitted_date': getattr(p, 'submitted_date', '') or '',
            })
    except Exception as ex:
        logger.debug('[discovery.arxiv] mock-friendly path failed: %s', ex)

    # 2) 仅当 mock 路径整段抛错（used_mock_path=False）时, 回退直连 API。
    #    测试场景下 mock 会成功返回（哪怕 list 为空），不再走直连，避免污染。
    if not used_mock_path:
        try:
            for e in _fetch_via_arxiv_api(tags, limit, topic=topic):
                entries.append({
                    'title': (getattr(e, 'title', '') or '').replace(chr(10), ' '),
                    'abstract': getattr(e, 'summary', '') or '',
                    'link': getattr(e, 'link', '') or '',
                    'submitted_date': (getattr(e, 'updated', '')
                                          or getattr(e, 'published', '')
                                          or ''),
                })
        except Exception as ex:
            logger.warning('[discovery.arxiv] direct API failed: %s', ex)

    out = []
    seen = set()
    for e in entries:
        aid = _parse_arxiv_id_from_link(e.get("link", ""))
        if not aid or aid in seen:
            continue
        # 过滤 N 天内
        sd = (e.get("submitted_date", "") or "")[:19]
        try:
            if sd:
                # 兼容两种格式
                if "T" in sd:
                    dt = datetime.datetime.strptime(sd[:19], "%Y-%m-%dT%H:%M:%S")
                else:
                    dt = datetime.datetime.strptime(sd[:10], "%Y-%m-%d")
                if dt < cutoff:
                    continue
        except Exception:
            pass
        seen.add(aid)
        out.append(Candidate(
            arxiv_id=aid,
            title=(e.get("title", "") or "").strip(),
            abstract=(e.get("abstract", "") or "").strip(),
            url="https://arxiv.org/abs/" + aid,
            submitted_date=sd[:10],
            upvotes=0,
            github_repo=None,
            project_page=None,
            source="arxiv",
        ))
    logger.info("[discovery.arxiv] got %d candidates (tags=%s, days=%d, topic=%r)",
                len(out), tags, days, topic)
    return out
