"""创作者中心数据聚合 CLI.

用法:
    python -m src.distribution.analytics.cli fetch [--platforms ...]
                                                   [--max-posts 20]
                                                   [--published-papers PATH]
                                                   [--db PATH]
    python -m src.distribution.analytics.cli summary [--platforms ...]
                                                     [--days 7]
                                                     [--db PATH]

约定:
    - stdout: ``fetch`` 一行 JSON 概要 (兼容上层 cron 落日志);
              ``summary`` 直接打印 ASCII 表.
    - stderr: logging.

cron 建议:
    0 9 * * * cd /home/jdh/Projects/VlogCutter/JushenRenji && \
        /home/jdh/miniconda3/envs/paperagent/bin/python \
        -m src.distribution.analytics.cli fetch --max-posts 20 \
        >> tmp/analytics_fetch.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("analytics.cli")
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s | %(message)s")

DEFAULT_PLATFORMS = ("bilibili", "xhs", "douyin")
DEFAULT_PUBLISHED_PAPERS = Path(
    "/home/jdh/Projects/VlogCutter/JushenRenji/cache/published_papers.json"
)


def _parse_platforms(s: Optional[str]) -> List[str]:
    if not s:
        return list(DEFAULT_PLATFORMS)
    out: List[str] = []
    for p in s.split(","):
        p = p.strip().lower()
        if not p:
            continue
        if p == "xiaohongshu":
            p = "xhs"
        if p in DEFAULT_PLATFORMS:
            out.append(p)
        else:
            logger.warning("忽略未知平台: %s", p)
    return out or list(DEFAULT_PLATFORMS)


def _load_published(papers_path: Path) -> List[Dict[str, Any]]:
    if not papers_path.exists():
        logger.warning("published_papers.json 不存在: %s", papers_path)
        return []
    try:
        with open(papers_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("published_papers.json 解析失败: %s", exc)
        return []
    if not isinstance(data, list):
        return []
    return data


def _fetch_bilibili(
    papers: List[Dict[str, Any]],
    max_posts: int,
    db_path: Optional[Path],
) -> Dict[str, Any]:
    from . import bilibili_stats, stats_store

    bv_ids: List[Dict[str, Any]] = []
    seen = set()
    for p in papers:
        bv = p.get("bvid") or p.get("bv_id")
        if bv and bv not in seen:
            seen.add(bv)
            bv_ids.append({"bvid": bv, "title": p.get("title", "")})
    bv_ids = bv_ids[-max_posts:]  # 只取最近 N 条

    today = date.today().isoformat()
    ok, fail = 0, 0
    errors: List[str] = []
    for item in bv_ids:
        try:
            stats = bilibili_stats.fetch_video_stats(item["bvid"])
        except Exception as exc:
            fail += 1
            errors.append(f"{item['bvid']}: {exc}")
            logger.warning("[bilibili] %s: %s", item["bvid"], exc)
            continue
        try:
            stats_store.upsert_stats(
                platform="bilibili",
                post_id=item["bvid"],
                fetch_date=today,
                title=item["title"],
                raw_json=stats.get("raw"),
                db_path=db_path,
                views=stats.get("views", 0),
                likes=stats.get("likes", 0),
                comments=stats.get("comments", 0),
                shares=stats.get("shares", 0),
                favorites=stats.get("favorites", 0),
            )
            ok += 1
        except Exception as exc:
            fail += 1
            errors.append(f"{item['bvid']} upsert: {exc}")
    return {"platform": "bilibili", "ok": ok, "fail": fail,
            "total": len(bv_ids), "errors": errors[:10]}


def _fetch_xhs(
    papers: List[Dict[str, Any]],
    max_posts: int,
    db_path: Optional[Path],
) -> Dict[str, Any]:
    from . import stats_store, xhs_stats

    notes: List[Dict[str, Any]] = []
    seen = set()
    for p in papers:
        nid = p.get("xhs_note_id") or p.get("xhs_id")
        token = p.get("xhs_xsec_token") or p.get("xsec_token")
        if nid and token and nid not in seen:
            seen.add(nid)
            notes.append({
                "note_id": nid,
                "xsec_token": token,
                "title": p.get("title", ""),
            })
    notes = notes[-max_posts:]

    today = date.today().isoformat()
    ok, fail = 0, 0
    errors: List[str] = []
    if not notes:
        logger.info("[xhs] published_papers.json 中没有 xhs_note_id, 跳过")
        return {"platform": "xhs", "ok": 0, "fail": 0, "total": 0,
                "errors": ["no xhs_note_id in published_papers"]}

    for item in notes:
        try:
            stats = xhs_stats.fetch_note_stats(
                item["note_id"], item["xsec_token"]
            )
        except Exception as exc:
            fail += 1
            errors.append(f"{item['note_id']}: {exc}")
            logger.warning("[xhs] %s: %s", item["note_id"], exc)
            continue
        try:
            stats_store.upsert_stats(
                platform="xhs",
                post_id=item["note_id"],
                fetch_date=today,
                title=item["title"],
                raw_json=stats.get("raw"),
                db_path=db_path,
                views=stats.get("views", 0),
                likes=stats.get("likes", 0),
                comments=stats.get("comments", 0),
                shares=stats.get("shares", 0),
                favorites=stats.get("collects", 0),
            )
            ok += 1
        except Exception as exc:
            fail += 1
            errors.append(f"{item['note_id']} upsert: {exc}")
    return {"platform": "xhs", "ok": ok, "fail": fail,
            "total": len(notes), "errors": errors[:10]}


def _fetch_douyin(
    max_posts: int,
    db_path: Optional[Path],
) -> Dict[str, Any]:
    from . import douyin_stats, stats_store

    today = date.today().isoformat()
    try:
        items = douyin_stats.fetch_creator_stats(max_posts=max_posts)
    except Exception as exc:
        logger.warning("[douyin] 抓取失败: %s", exc)
        return {"platform": "douyin", "ok": 0, "fail": 0, "total": 0,
                "errors": [str(exc)]}

    ok, fail = 0, 0
    errors: List[str] = []
    for it in items:
        try:
            stats_store.upsert_stats(
                platform="douyin",
                post_id=it["post_id"],
                fetch_date=today,
                title=it.get("title", ""),
                raw_json=it.get("raw"),
                db_path=db_path,
                views=it.get("views", 0),
                likes=it.get("likes", 0),
                comments=it.get("comments", 0),
                shares=it.get("shares", 0),
                favorites=it.get("favorites", 0),
            )
            ok += 1
        except Exception as exc:
            fail += 1
            errors.append(f"{it.get('post_id')}: {exc}")
    return {"platform": "douyin", "ok": ok, "fail": fail,
            "total": len(items), "errors": errors[:10]}


def cmd_fetch(args) -> int:
    platforms = _parse_platforms(args.platforms)
    papers_path = Path(args.published_papers) if args.published_papers \
        else DEFAULT_PUBLISHED_PAPERS
    papers = _load_published(papers_path)
    db_path = Path(args.db) if args.db else None

    results: List[Dict[str, Any]] = []
    if "bilibili" in platforms:
        results.append(_fetch_bilibili(papers, args.max_posts, db_path))
    if "xhs" in platforms:
        results.append(_fetch_xhs(papers, args.max_posts, db_path))
    if "douyin" in platforms:
        results.append(_fetch_douyin(args.max_posts, db_path))

    summary = {
        "ok": all(r.get("fail", 0) == 0 for r in results),
        "date": date.today().isoformat(),
        "platforms": platforms,
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False))
    sys.stdout.flush()
    # 任一平台 fail > 0 时 exit 1, 但仍输出 JSON
    return 0 if summary["ok"] else 1


def cmd_summary(args) -> int:
    from . import stats_store

    platforms = _parse_platforms(args.platforms)
    db_path = Path(args.db) if args.db else None
    if len(platforms) == 1:
        out = stats_store.summary_table(
            platform=platforms[0], days=args.days, db_path=db_path
        )
        print(out, end="")
    else:
        for plat in platforms:
            print(f"=== {plat.upper()} ===")
            out = stats_store.summary_table(
                platform=plat, days=args.days, db_path=db_path
            )
            print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analytics", description="创作者中心数据聚合 CLI"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="抓取并写入 sqlite")
    pf.add_argument("--platforms", default=None,
                    help="逗号分隔, 默认 bilibili,xhs,douyin")
    pf.add_argument("--max-posts", type=int, default=20)
    pf.add_argument("--published-papers", default=None,
                    help="cache/published_papers.json 路径")
    pf.add_argument("--db", default=None, help="sqlite 路径")
    pf.set_defaults(func=cmd_fetch)

    ps = sub.add_parser("summary", help="输出 ASCII 表汇总")
    ps.add_argument("--platforms", default=None)
    ps.add_argument("--days", type=int, default=7)
    ps.add_argument("--db", default=None)
    ps.set_defaults(func=cmd_summary)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
