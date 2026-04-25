#!/usr/bin/env python3
"""一次性脚本：扫 ``output/*.mp4`` 反推 arxiv_id，灌进 ``cache/published_papers.json``。

Heuristic 反推规则：
1. 同名 ``*_meta.json`` 存在 → 优先读 ``paper_links[0]`` 解析 arxiv id
2. 否则尝试 ``*.mp4`` 文件名里匹配 ``YYYY-MM-DD`` 前缀做 date 字段
3. arxiv_id 缺失但 cn 标题在则记录 title-only（用于 fuzzy 去重）

Usage:
    cd /home/jdh/Projects/VlogCutter/JushenRenji
    conda run -n paperagent python scripts/backfill_published.py [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUTPUT_DIR = os.path.join(ROOT, "output")
STATE_PATH = os.path.join(ROOT, "cache", "published_papers.json")

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_AID_RE = re.compile(r"([0-9]{4}\.[0-9]{4,6})")


def _extract_arxiv_id_from_meta(meta_path: str):
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        for link in (meta.get("paper_links") or []):
            m = _AID_RE.search(str(link))
            if m:
                return m.group(1)
    except Exception:
        return None
    return None


def _scan_mp4(mp4_path: str):
    name = os.path.basename(mp4_path)
    base = os.path.splitext(name)[0]
    # date
    m = _DATE_RE.search(name)
    date = m.group(1) if m else ""
    # meta json
    meta_path = os.path.join(os.path.dirname(mp4_path), base + "_meta.json")
    aid = _extract_arxiv_id_from_meta(meta_path)
    title = ""
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            cn = (meta.get("cn_titles") or [])
            en = (meta.get("titles") or [])
            title = (cn[0] if cn else (en[0] if en else "")).strip()
        except Exception:
            pass
    if not title:
        # 从文件名（去日期前缀）当 title
        t = base
        if date:
            t = t.replace(date + "_", "", 1)
        # 去末尾 _with_cover / _fast / _script 等
        t = re.sub(r"_(with_cover|fast|script)$", "", t)
        title = t.strip()
    return aid, title, date


def main():
    ap = argparse.ArgumentParser(description="Backfill cache/published_papers.json from output/*.mp4")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印不写入")
    args = ap.parse_args()

    if not os.path.isdir(OUTPUT_DIR):
        print("[backfill] output dir not found:", OUTPUT_DIR)
        return 1

    mp4_paths = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.mp4")))
    print("[backfill] scanning %d mp4 files" % len(mp4_paths))

    # 现存 state
    pub = []
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                pub = json.load(f)
            if not isinstance(pub, list):
                pub = []
        except Exception:
            pub = []
    seen = {(p.get("arxiv_id") or "").strip() for p in pub if p.get("arxiv_id")}

    added = 0
    skipped = 0
    for mp4 in mp4_paths:
        aid, title, date = _scan_mp4(mp4)
        # 忽略合并 _with_cover 等重复版（同 arxiv_id 已存在）
        if aid and aid in seen:
            skipped += 1
            continue
        if not aid and not title:
            skipped += 1
            continue
        entry = {
            "arxiv_id": aid or "",
            "title": title,
            "date": date or datetime.datetime.now().strftime("%Y-%m-%d"),
            "video_path": os.path.abspath(mp4),
        }
        pub.append(entry)
        if aid:
            seen.add(aid)
        added += 1
        print("[backfill] +", aid or "(no-id)", "|", title[:60])

    print("[backfill] added=%d skipped=%d total=%d" % (added, skipped, len(pub)))
    if args.dry_run:
        print("[backfill] --dry-run, not writing")
        return 0
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(pub, f, ensure_ascii=False, indent=2)
    print("[backfill] wrote", STATE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
