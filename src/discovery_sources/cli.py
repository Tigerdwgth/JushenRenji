"""Discovery CLI — opencode skill 的命令行入口。

子命令：
- ``arxiv-search``      按 topic + cat 拉 arxiv 最近 N 天
- ``arxiv-by-venue``    按 venue + year 拉接收论文（best-effort 模糊匹配）
- ``hf-daily``          HF Daily Papers 当日热榜

统一 JSON 输出：``{"ok": bool, "count": int, "papers": [...], "error"?: str}``。
失败时 ``ok=false``，``papers=[]``，exit code 1，``error`` 写错误摘要。

调用前自动 ``apply_network_workarounds()``（幂等，``JSR_NETWORK_PROFILE`` 环境
变量决定是否启用）。

Bash 例子::

    python -m src.discovery_sources.cli arxiv-search \
        --query "diffusion policy" --days 7 --limit 30
    python -m src.discovery_sources.cli arxiv-by-venue \
        --venue RSS --year 2025 --limit 50
    python -m src.discovery_sources.cli hf-daily --limit 20
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Optional


def _candidate_to_dict(c) -> dict:
    """Candidate dataclass -> JSON-safe dict（与 Candidate 字段一致）。"""
    return {
        "arxiv_id": getattr(c, "arxiv_id", "") or "",
        "title": getattr(c, "title", "") or "",
        "abstract": getattr(c, "abstract", "") or "",
        "url": getattr(c, "url", "") or "",
        "submitted_date": getattr(c, "submitted_date", "") or "",
        "upvotes": int(getattr(c, "upvotes", 0) or 0),
        "github_repo": getattr(c, "github_repo", None),
        "project_page": getattr(c, "project_page", None),
        "source": getattr(c, "source", "") or "",
    }


def _print_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discovery-cli",
        description="Discovery CLI: arxiv / venue / HF Daily 搜索（JSON stdout）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # arxiv-search
    p1 = sub.add_parser(
        "arxiv-search",
        help="按 topic + 分类拉 arxiv 最近 N 天的论文",
    )
    p1.add_argument("--query", required=True, help="topic 短语，会拼到 abs:")
    p1.add_argument("--days", type=int, default=7,
                    help="保留 submitted_date >= now-days 的条目（默认 7）")
    p1.add_argument("--limit", type=int, default=30,
                    help="单次拉取上限（默认 30）")
    p1.add_argument("--categories", default="cs.RO,cs.CV",
                    help="逗号分隔的 arxiv cat 列表，默认 cs.RO,cs.CV")

    # arxiv-by-venue
    p2 = sub.add_parser(
        "arxiv-by-venue",
        help="按 venue + year 在 arxiv co: 字段做 best-effort 模糊搜索",
    )
    p2.add_argument("--venue", required=True,
                    help="会议名（RSS/NeurIPS/CoRL/ICLR/ICRA/CVPR/ICCV/ECCV …）")
    p2.add_argument("--year", type=int, required=True,
                    help="4 位年份（2025/2026 …）")
    p2.add_argument("--limit", type=int, default=50,
                    help="最大返回条数（默认 50）")
    p2.add_argument(
        "--include-submitted",
        action="store_true",
        help="同时匹配 'submitted to <venue> <year>'（默认只搜接收类）",
    )
    p2.add_argument(
        "--categories",
        default="cs.RO,cs.CV,cs.LG,cs.AI",
        help="逗号分隔的 arxiv cat 列表，默认 cs.RO,cs.CV,cs.LG,cs.AI",
    )

    # hf-daily
    p3 = sub.add_parser(
        "hf-daily",
        help="HuggingFace Daily Papers 当日热榜",
    )
    p3.add_argument("--limit", type=int, default=30,
                    help="最大返回条数（默认 30）")

    return parser


def _setup_logging() -> None:
    """CLI 默认 WARNING，避免污染 stdout JSON。"""
    logging.basicConfig(
        level=logging.WARNING,
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _apply_network_workarounds_safe() -> None:
    """幂等调 apply_network_workarounds；失败仅 warning 不退出。"""
    try:
        # CLI 既可能从项目根 (`python -m src.discovery_sources.cli`) 也可能
        # 从 src 目录直接 (`python -m discovery_sources.cli`) 进，两种 import
        # 都兜一下。
        try:
            from src.env_setup import apply_network_workarounds
        except ImportError:
            from env_setup import apply_network_workarounds  # type: ignore
        apply_network_workarounds()
    except Exception as e:  # noqa: BLE001
        logging.warning("[discovery.cli] apply_network_workarounds failed: %s", e)


def _run_arxiv_search(args) -> list:
    from src.discovery_sources.arxiv_recent import fetch_arxiv_recent
    cats = [c.strip() for c in (args.categories or "").split(",") if c.strip()]
    return fetch_arxiv_recent(
        tags=cats,
        days=int(args.days),
        limit=int(args.limit),
        topic=args.query,
    ) or []


def _run_arxiv_by_venue(args) -> list:
    from src.discovery_sources.venue_search import fetch_arxiv_by_venue
    cats = [c.strip() for c in (args.categories or "").split(",") if c.strip()]
    return fetch_arxiv_by_venue(
        venue=args.venue,
        year=int(args.year),
        limit=int(args.limit),
        accepted_only=not bool(args.include_submitted),
        categories=cats or None,
    ) or []


def _run_hf_daily(args) -> list:
    from src.discovery_sources.hf_papers import fetch_hf_daily
    return fetch_hf_daily(limit=int(args.limit)) or []


_DISPATCH = {
    "arxiv-search": _run_arxiv_search,
    "arxiv-by-venue": _run_arxiv_by_venue,
    "hf-daily": _run_hf_daily,
}


def main(argv: Optional[list] = None) -> int:
    _setup_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    _apply_network_workarounds_safe()

    handler = _DISPATCH.get(args.cmd)
    if handler is None:
        _print_json({"ok": False, "error": "unknown cmd: %s" % args.cmd, "papers": []})
        return 1

    try:
        cands = handler(args)
    except Exception as e:  # noqa: BLE001
        logging.exception("[discovery.cli] %s failed", args.cmd)
        _print_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                     "papers": []})
        return 1

    payload = {
        "ok": True,
        "count": len(cands),
        "papers": [_candidate_to_dict(c) for c in cands],
    }
    _print_json(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
