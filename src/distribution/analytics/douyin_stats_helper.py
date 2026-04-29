#!/usr/bin/env python3
"""SAU venv 内执行的抖音创作者中心数据抓取 helper.

策略:
    XHR (默认): 进 ``creator-micro/data`` 作品分析页, 拦截
                ``aweme/v1/creator/data/`` 系 XHR JSON.
    DOM: 进 ``creator-micro/content/manage``, 解析作品卡片
                上的统计文本(播放/点赞/评论/分享).
    auto: 先 XHR 抓 ~25s, 拿不到就 fallback 到 DOM.

stdout 单行 JSON: {"ok": true, "items": [...]} / {"ok": false, "error": "..."}.
日志全部 stderr.

Usage:
    sau_venv_python -m src.distribution.analytics.douyin_stats_helper \
        --account-file <cookies.json> [--max-posts 20] [--mode auto|xhr|dom]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("douyin_stats_helper")


XHR_KEYWORDS = (
    "aweme/v1/creator/data",
    "creator/data/aweme",
    "creator/aweme/list",
    "creator_center/aweme_data",
)

DATA_PAGE = "https://creator.douyin.com/creator-micro/data/following"
MANAGE_PAGE = "https://creator.douyin.com/creator-micro/content/manage"


def _emit(payload: Dict[str, Any], code: int = 0):
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(code)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--account-file", required=True)
    p.add_argument("--max-posts", type=int, default=20)
    p.add_argument("--mode", choices=["auto", "xhr", "dom"], default="auto")
    p.add_argument("--sau-dir", default=os.environ.get(
        "SAU_DIR",
        "/home/jdh/Projects/VlogCutter/third_party/social-auto-upload",
    ))
    p.add_argument("--xhr-wait", type=int, default=25,
                   help="XHR 模式下最多等待 XHR 的秒数")
    return p.parse_args()


def _coerce_int(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if not s:
        return 0
    multiplier = 1
    if s.endswith("万"):
        multiplier = 10000
        s = s[:-1]
    elif s.endswith("亿"):
        multiplier = 100000000
        s = s[:-1]
    elif s.lower().endswith("k"):
        multiplier = 1000
        s = s[:-1]
    elif s.lower().endswith("w"):
        multiplier = 10000
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except (TypeError, ValueError):
        return 0


def _hash_id(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


def _normalize_xhr_item(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """抖音创作者中心 XHR 字段 best-effort 映射. 字段名按观测填,
    不同版本可能略有差异. 缺失字段 -> 0.

    我们看 raw 里的 ``aweme_id`` / ``item_id``, 内层 ``statistics``,
    或 ``play_count`` / ``digg_count`` 等顶层字段(列表场景).
    """
    if not isinstance(raw, dict):
        return None

    aweme_id = (
        raw.get("aweme_id") or raw.get("item_id") or raw.get("id")
        or raw.get("aid") or ""
    )
    title = (
        raw.get("desc") or raw.get("title") or raw.get("share_desc") or ""
    )
    stats = raw.get("statistics") or raw.get("stats") or {}
    if not isinstance(stats, dict):
        stats = {}

    views = _coerce_int(
        raw.get("play_count") or stats.get("play_count")
        or raw.get("video_play_count") or stats.get("video_play_count")
    )
    likes = _coerce_int(
        raw.get("digg_count") or stats.get("digg_count")
        or raw.get("like_count") or stats.get("like_count")
    )
    comments = _coerce_int(
        raw.get("comment_count") or stats.get("comment_count")
    )
    shares = _coerce_int(
        raw.get("share_count") or stats.get("share_count")
        or raw.get("forward_count") or stats.get("forward_count")
    )
    favorites = _coerce_int(
        raw.get("collect_count") or stats.get("collect_count")
        or raw.get("favorite_count") or stats.get("favorite_count")
    )
    completion = raw.get("avg_play_finish_rate") or stats.get("avg_play_finish_rate")
    if isinstance(completion, (int, float)):
        # 抖音返回 0~100 (%) 或 0~1, 统一成 %
        completion_rate = float(completion) * 100 if completion <= 1 else float(completion)
    else:
        completion_rate = 0.0

    # 没拿到任何统计数据的项跳过 (避免 list 接口返回空壳被误算)
    if views == 0 and likes == 0 and comments == 0:
        return None

    post_id = str(aweme_id) or _hash_id(title)
    return {
        "post_id": post_id,
        "title": title,
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "favorites": favorites,
        "completion_rate": round(completion_rate, 2),
        "raw": raw,
    }


def _extract_xhr_items(payload: Any) -> List[Dict[str, Any]]:
    """从 XHR JSON 里抽 list[item]. 抖音不同接口路径不同, 尝试多个 key."""
    if not isinstance(payload, dict):
        return []
    candidates = []
    for key in (
        "aweme_list", "aweme_data", "data", "list",
        "items", "video_list", "result", "results",
    ):
        v = payload.get(key)
        if isinstance(v, list):
            candidates.extend(v)
        elif isinstance(v, dict):
            for sub_key in ("aweme_list", "list", "items", "data"):
                sv = v.get(sub_key)
                if isinstance(sv, list):
                    candidates.extend(sv)
    out: List[Dict[str, Any]] = []
    for raw in candidates:
        norm = _normalize_xhr_item(raw)
        if norm:
            out.append(norm)
    return out


_DOM_NUM = re.compile(r"([\d.]+\s*[万亿wkWK]?)")


def _parse_dom_card(card_text: str) -> Dict[str, int]:
    """容错地从作品卡片文本里抽 4 个数(播放/点赞/评论/分享).

    抖音作品管理页卡片大概长这样(2026 版):
        "标题摘要... 播放 1.2万 点赞 234 评论 12 分享 5"
    顺序与字段名都不稳定, 我们靠 label-后跟数字 的正则.
    """
    fields = {
        "views": [r"播放[^\d]{0,4}([\d.]+\s*[万亿wkWK]?)"],
        "likes": [r"点赞[^\d]{0,4}([\d.]+\s*[万亿wkWK]?)",
                  r"赞[^\d]{0,4}([\d.]+\s*[万亿wkWK]?)"],
        "comments": [r"评论[^\d]{0,4}([\d.]+\s*[万亿wkWK]?)"],
        "shares": [r"分享[^\d]{0,4}([\d.]+\s*[万亿wkWK]?)",
                   r"转发[^\d]{0,4}([\d.]+\s*[万亿wkWK]?)"],
    }
    out: Dict[str, int] = {}
    for key, patterns in fields.items():
        val = 0
        for pat in patterns:
            m = re.search(pat, card_text)
            if m:
                val = _coerce_int(m.group(1).replace(" ", ""))
                break
        out[key] = val
    return out


async def _collect_xhr(page, max_wait_sec: int) -> List[Dict[str, Any]]:
    """监听 XHR, 收集匹配 keywords 的 JSON 响应."""
    raw_payloads: List[Any] = []

    async def _on_response(resp):
        try:
            url = resp.url
        except Exception:
            return
        if not any(k in url for k in XHR_KEYWORDS):
            return
        try:
            body = await resp.json()
        except Exception:
            return
        raw_payloads.append(body)

    page.on("response", lambda r: asyncio.ensure_future(_on_response(r)))

    try:
        await page.goto(DATA_PAGE, wait_until="domcontentloaded",
                        timeout=60000)
    except Exception as exc:
        logger.warning("data 页打开失败: %s", exc)
        return []

    # 等待 XHR
    waited = 0
    while waited < max_wait_sec and not raw_payloads:
        await asyncio.sleep(2)
        waited += 2

    items: List[Dict[str, Any]] = []
    for body in raw_payloads:
        items.extend(_extract_xhr_items(body))
    return items


async def _collect_dom(page, max_posts: int) -> List[Dict[str, Any]]:
    """退路: 抓作品管理页的卡片 DOM."""
    try:
        await page.goto(MANAGE_PAGE, wait_until="domcontentloaded",
                        timeout=60000)
    except Exception as exc:
        logger.warning("manage 页打开失败: %s", exc)
        return []

    # 给 SPA 渲染留时间
    await asyncio.sleep(8)

    # 通用兜底: 找所有卡片. 抖音改 className 频繁, 我们用 role 与 text 启发式.
    try:
        # 抖音作品卡通常是 div, 内含 video preview + 数据 row
        cards = await page.locator("div.video-card, div[class*='video-card'], div[class*='content-item']").all()
        if not cards:
            # fallback: 任何含 "播放" 文本的 div
            cards = await page.locator("xpath=//div[contains(., '播放') and contains(., '点赞')]").all()
    except Exception as exc:
        logger.warning("locator 失败: %s", exc)
        cards = []

    items: List[Dict[str, Any]] = []
    for c in cards[: max_posts * 2]:
        try:
            txt = await c.inner_text()
        except Exception:
            continue
        if not txt or "播放" not in txt:
            continue
        # 取第一行作为标题
        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        title = lines[0] if lines else ""
        stats = _parse_dom_card(txt)
        if stats["views"] == 0 and stats["likes"] == 0:
            continue
        items.append({
            "post_id": _hash_id(title) if title else _hash_id(txt[:64]),
            "title": title,
            "views": stats["views"],
            "likes": stats["likes"],
            "comments": stats["comments"],
            "shares": stats["shares"],
            "favorites": 0,
            "completion_rate": 0.0,
            "raw": {"dom_text": txt[:1000]},
        })
        if len(items) >= max_posts:
            break
    return items


def _dedup_by_post_id(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同 post_id 取数据最满的(views 最大的)."""
    by_id: Dict[str, Dict[str, Any]] = {}
    for it in items:
        pid = it.get("post_id")
        if not pid:
            continue
        cur = by_id.get(pid)
        if cur is None or (it.get("views", 0) > cur.get("views", 0)):
            by_id[pid] = it
    return list(by_id.values())


async def _run(args) -> Dict[str, Any]:
    sau_dir = Path(args.sau_dir).expanduser().resolve()
    if not sau_dir.exists():
        return {"ok": False, "error": f"SAU 目录不存在: {sau_dir}"}

    sys.path.insert(0, str(sau_dir))
    os.chdir(sau_dir)

    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"playwright import 失败: {exc}"}

    account_file = Path(args.account_file).expanduser().resolve()
    if not account_file.exists():
        return {"ok": False, "error": f"cookie 文件不存在: {account_file}"}

    items: List[Dict[str, Any]] = []
    err: Optional[str] = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                storage_state=str(account_file),
                viewport={"width": 1440, "height": 900},
            )
            page = await context.new_page()

            try:
                if args.mode in ("xhr", "auto"):
                    items = await _collect_xhr(page, args.xhr_wait)
                if (not items) and args.mode in ("dom", "auto"):
                    if args.mode == "auto":
                        logger.warning("XHR 抓不到, 退到 DOM 模式")
                    items = await _collect_dom(page, args.max_posts)
            except Exception as exc:
                err = f"抓取失败: {exc}"

            await context.close()
            await browser.close()
    except Exception as exc:
        return {"ok": False, "error": f"playwright 启动失败: {exc}"}

    items = _dedup_by_post_id(items)[: args.max_posts]
    if not items:
        return {
            "ok": False,
            "error": err or "未抓到任何作品(可能 cookie 过期或 UI 变更)",
            "items": [],
        }
    return {"ok": True, "items": items}


def main():
    args = _parse_args()
    try:
        payload = asyncio.run(_run(args))
    except Exception as exc:
        payload = {"ok": False, "error": f"helper 异常: {exc}"}
    _emit(payload, 0 if payload.get("ok") else 1)


if __name__ == "__main__":
    main()
