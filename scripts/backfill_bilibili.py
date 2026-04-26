#!/usr/bin/env python3
"""从 B 站作者频道拉全量稿件，merge 进 cache/published_papers.json。

依赖：bilibili-api-python（User.get_videos 异步分页 API）。
鉴权：复用 config.yaml 的 bilibili_cookies 构造 Credential，避免风控。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import yaml
from bilibili_api import user, Credential

STATE_PATH = os.path.join(ROOT, "cache", "published_papers.json")
CONFIG_PATH = os.path.join(ROOT, "config.yaml")

_AID_RE = re.compile(r"(\d{4}\.\d{4,6})")


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_credential(config: dict):
    c = (config.get("bilibili_cookies") or {})
    if not c.get("sessdata"):
        return None
    return Credential(
        sessdata=c.get("sessdata"),
        bili_jct=c.get("bili_jct"),
        buvid3="",
        dedeuserid=str(c.get("dedeuserid") or ""),
    )


async def fetch_all_videos(uid: int, credential, max_pages: int = 30):
    u = user.User(uid=uid, credential=credential)
    all_videos = []
    pn = 1
    while pn <= max_pages:
        try:
            data = await u.get_videos(pn=pn, ps=50)
        except Exception as e:
            print(f"[backfill_bilibili] page {pn} failed: {e}", file=sys.stderr)
            break
        vlist = (data.get("list") or {}).get("vlist") or []
        if not vlist:
            break
        all_videos.extend(vlist)
        page_info = data.get("page") or {}
        total = page_info.get("count", 0)
        print(f"[backfill_bilibili] page {pn}: +{len(vlist)} (got {len(all_videos)}/{total})")
        if total and len(all_videos) >= total:
            break
        pn += 1
        await asyncio.sleep(0.6)
    return all_videos


def _normalize_entry(v: dict) -> dict:
    title = (v.get("title") or "").strip()
    desc = v.get("description") or ""
    m = _AID_RE.search(desc) or _AID_RE.search(title)
    aid = m.group(1) if m else None
    pubdate_ts = v.get("created") or 0
    date = time.strftime("%Y-%m-%d", time.localtime(pubdate_ts)) if pubdate_ts else ""
    return {
        "arxiv_id": aid,
        "title": title,
        "date": date,
        "video_path": "",
        "bvid": v.get("bvid") or "",
        "source": "bilibili_backfill",
    }


def merge_published(new_entries, dry_run: bool = False):
    existing = []
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)

    seen_bvid = {e.get("bvid"): e for e in existing if e.get("bvid")}
    title_idx = {}
    for e in existing:
        t = (e.get("title") or "").strip().lower()
        if t:
            title_idx.setdefault(t, []).append(e)

    added = 0
    enriched = 0
    for entry in new_entries:
        bvid = entry.get("bvid")
        title_lc = entry.get("title", "").strip().lower()
        if bvid and bvid in seen_bvid:
            continue
        if title_lc and title_lc in title_idx:
            for old in title_idx[title_lc]:
                if not old.get("bvid"):
                    old["bvid"] = bvid
                if entry.get("arxiv_id") and not old.get("arxiv_id"):
                    old["arxiv_id"] = entry["arxiv_id"]
                if entry.get("date") and not old.get("date"):
                    old["date"] = entry["date"]
            enriched += 1
            if bvid:
                seen_bvid[bvid] = title_idx[title_lc][0]
            continue
        existing.append(entry)
        added += 1
        if bvid:
            seen_bvid[bvid] = entry
        if title_lc:
            title_idx.setdefault(title_lc, []).append(entry)

    if not dry_run:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    return added, enriched, len(existing)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uid", type=int, default=None, help="bilibili UID; 默认读 config.yaml dedeuserid")
    parser.add_argument("--max-pages", type=int, default=30)
    args = parser.parse_args()

    config = _load_config()
    uid = args.uid
    if not uid:
        raw = (config.get("bilibili_cookies") or {}).get("dedeuserid")
        uid = int(raw) if raw else None
    if not uid:
        print("[backfill_bilibili] uid not configured", file=sys.stderr)
        sys.exit(1)

    credential = _load_credential(config)
    print(f"[backfill_bilibili] uid={uid} credential={'yes' if credential else 'no'}")

    videos = asyncio.run(fetch_all_videos(uid, credential, max_pages=args.max_pages))
    print(f"[backfill_bilibili] fetched {len(videos)} videos")

    entries = [_normalize_entry(v) for v in videos]
    sample_aid = sum(1 for e in entries if e.get("arxiv_id"))
    print(f"[backfill_bilibili] entries with arxiv_id from desc: {sample_aid}/{len(entries)}")

    added, enriched, total = merge_published(entries, dry_run=args.dry_run)
    print(f"[backfill_bilibili] added={added} enriched_existing={enriched} total_in_state={total}")
    if args.dry_run:
        print("[backfill_bilibili] --dry-run, not writing")
    else:
        print(f"[backfill_bilibili] wrote {STATE_PATH}")


if __name__ == "__main__":
    main()
