"""arXiv venue-based paper discovery.

按会议名称 + 年份在 arxiv ``co:`` (comments) 字段做 best-effort 模糊搜索：
arxiv 接收备注没有规范写法（e.g. ``Accepted to RSS 2025`` /
``To appear at NeurIPS 2025`` / ``RSS 2025`` / ``RSS'25`` 都常见），所以拼多
个 OR 子句覆盖典型变体。

公开 API:
    fetch_arxiv_by_venue(venue, year, limit=50, accepted_only=True,
                          categories=None) -> list[Candidate]

注意：
- arxiv ``co:`` 字段索引并不完全，召回率 best-effort（README + SKILL.md 都已
  注明）。
- 与 ``arxiv_recent.py`` 一致：用 ``urllib.parse.quote_plus`` 拼短语，
  ``feedparser`` 解析 atom feed，结果转 ``Candidate``（与 paper_discovery
  里的 dataclass 兼容）。
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


_DEFAULT_CATEGORIES = ["cs.RO", "cs.CV", "cs.LG", "cs.AI"]


def _parse_arxiv_id_from_link(link: str) -> Optional[str]:
    if not link:
        return None
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,6})", link)
    if m:
        return m.group(1)
    m = re.search(r"([0-9]{4}\.[0-9]{4,6})", link)
    return m.group(1) if m else None


def _year_short(year: int) -> str:
    """2025 -> "'25"; 2009 -> "'09"。"""
    y = int(year) % 100
    return "'%02d" % y


def _venue_co_clauses(venue: str, year: int, accepted_only: bool) -> list:
    """生成搜 arxiv comments 字段的多个变体短语（未拼接）。

    返回 list[str]，每条已经 ``quote_plus`` 编码（含外层 ``%22..%22``），
    交给 :func:`_build_venue_query` 拼 ``co:%22..%22+OR+co:%22..%22``。

    accepted_only=True 时返回 4 条变体；False 再加 1 条 ``submitted to ...``。
    """
    venue_str = str(venue or "").strip()
    if not venue_str:
        raise ValueError("venue must be non-empty")
    yr = int(year)
    yr_short = _year_short(yr)

    variants = [
        "accepted to %s %d" % (venue_str, yr),
        "%s %d" % (venue_str, yr),
        "%s%s" % (venue_str, yr_short),       # RSS'25
        "to appear at %s %d" % (venue_str, yr),
    ]
    if not accepted_only:
        variants.append("submitted to %s %d" % (venue_str, yr))

    out = []
    for v in variants:
        # quote_plus('accepted to RSS 2025') = 'accepted+to+RSS+2025'
        # 外层加 %22..%22 标记 arxiv 短语搜索
        out.append("%22" + quote_plus(v) + "%22")
    return out


def _build_venue_query(venue: str, year: int, accepted_only: bool = True,
                       categories: Optional[list] = None) -> str:
    """拼最终 arxiv search_query。

    形如::

        (co:%22accepted+to+RSS+2025%22+OR+co:%22RSS+2025%22+OR+co:%22RSS%2725%22+OR+co:%22to+appear+at+RSS+2025%22)
        +AND+(cat:cs.RO+OR+cat:cs.CV+OR+cat:cs.LG+OR+cat:cs.AI)
    """
    cats = list(categories) if categories else list(_DEFAULT_CATEGORIES)
    cat_part = "+OR+".join(
        "cat:" + str(c).strip() for c in cats if c and str(c).strip()
    )
    if not cat_part:
        cat_part = "cat:cs.RO"

    co_clauses = _venue_co_clauses(venue, year, accepted_only)
    co_part = "+OR+".join("co:" + c for c in co_clauses)

    return "(" + co_part + ")+AND+(" + cat_part + ")"


def _fetch_via_arxiv_api(query: str, limit: int) -> list:
    """Wrapper around feedparser.parse for testability."""
    import feedparser
    url = ("https://export.arxiv.org/api/query?search_query="
           + query
           + "&sortBy=lastUpdatedDate&sortOrder=descending&max_results="
           + str(int(limit)))
    feed = feedparser.parse(url)
    return list(getattr(feed, "entries", []) or [])


def fetch_arxiv_by_venue(
    venue: str,
    year: int,
    limit: int = 50,
    accepted_only: bool = True,
    categories: Optional[list] = None,
) -> list:
    """从 arxiv 按 venue+year 拉接收论文，返回 list[Candidate]。

    Args:
        venue: 会议名（"RSS" / "NeurIPS" / "CoRL" / "ICLR" / "ICRA" /
            "CVPR" / "ICCV" / "ECCV" 等）。原样拼到 query，不做大小写矫正。
        year: 4 位年份（2025/2026 …）。
        limit: 最大返回条数（也是 arxiv max_results）。
        accepted_only: True 时只匹配 ``accepted to / to appear at``
            等接收备注；False 再加 ``submitted to`` 变体。
        categories: arxiv 分类过滤，默认 ``["cs.RO","cs.CV","cs.LG","cs.AI"]``。

    Returns:
        list[Candidate]：与 ``hf_papers`` / ``arxiv_recent`` 同结构。
        网络/解析失败返回空列表（不抛）。

    Notes:
        ``co:`` 字段索引在 arxiv 上 best-effort，召回率不保证；
        SKILL.md 与 README 均已注明该限制。
    """
    # 延迟 import 避免循环 (Candidate dataclass 在 paper_discovery)
    from src.paper_discovery import Candidate

    if not venue or not str(venue).strip():
        logger.warning("[discovery.venue] empty venue, skip")
        return []
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        logger.warning("[discovery.venue] invalid year=%r, skip", year)
        return []

    query = _build_venue_query(
        venue=venue,
        year=year_int,
        accepted_only=bool(accepted_only),
        categories=categories,
    )

    try:
        entries = _fetch_via_arxiv_api(query, int(limit))
    except Exception as e:  # noqa: BLE001
        logger.warning("[discovery.venue] feed fetch failed: %s", e)
        return []

    out = []
    seen = set()
    for e in entries:
        link = (
            getattr(e, "link", None)
            or (e.get("link") if isinstance(e, dict) else None)
            or ""
        )
        title = (
            getattr(e, "title", None)
            or (e.get("title") if isinstance(e, dict) else None)
            or ""
        )
        summary = (
            getattr(e, "summary", None)
            or (e.get("summary") if isinstance(e, dict) else None)
            or ""
        )
        published = (
            getattr(e, "published", None)
            or (e.get("published") if isinstance(e, dict) else None)
            or ""
        )
        updated = (
            getattr(e, "updated", None)
            or (e.get("updated") if isinstance(e, dict) else None)
            or ""
        )

        aid = _parse_arxiv_id_from_link(link)
        if not aid or aid in seen:
            continue
        seen.add(aid)

        sd_raw = updated or published or ""
        out.append(Candidate(
            arxiv_id=aid,
            title=str(title).replace("\n", " ").strip(),
            abstract=str(summary).strip(),
            url="https://arxiv.org/abs/" + aid,
            submitted_date=str(sd_raw)[:10],
            upvotes=0,
            github_repo=None,
            project_page=None,
            source="arxiv_venue",
        ))

    logger.info(
        "[discovery.venue] venue=%s year=%d accepted_only=%s -> %d candidates",
        venue, year_int, accepted_only, len(out),
    )
    return out
