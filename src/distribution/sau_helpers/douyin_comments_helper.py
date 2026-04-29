#!/usr/bin/env python3
"""SAU venv 内执行的抖音评论拉取/回帖 helper (Playwright headed via Xvfb).

selector 用 keyword-based locator (get_by_text) 兜底, 失败时返回空数据.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import traceback
from pathlib import Path

logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")


def _emit(payload: dict, code: int = 0):
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(code)


async def _new_page(account_file: str):
    from playwright.async_api import async_playwright  # type: ignore
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, args=[
        "--no-sandbox", "--disable-blink-features=AutomationControlled",
    ])
    ctx = await browser.new_context(storage_state=account_file)
    page = await ctx.new_page()
    return pw, browser, ctx, page


async def _pull(args) -> dict:
    pw = browser = None
    try:
        pw, browser, ctx, page = await _new_page(args.account_file)
        await page.goto(args.aweme_url, wait_until="domcontentloaded",
                        timeout=30000)
        await page.wait_for_timeout(3000)
        # 滚动加载评论
        for _ in range(5):
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(800)
        items = []
        comment_nodes = await page.locator(
            "[data-e2e=feed-comment-item], .comment-item, "
            "[class*=CommentItem]"
        ).all()
        for n in comment_nodes[:50]:
            try:
                text = (await n.inner_text()).strip()
            except Exception:  # noqa: BLE001
                continue
            if not text:
                continue
            cid = hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
            # nick 取第一行, content 取后续
            lines = [ln for ln in text.split("\n") if ln.strip()]
            nick = lines[0] if lines else ""
            content = " ".join(lines[1:]) if len(lines) > 1 else text
            items.append({
                "id": cid,
                "content": content,
                "nick": nick,
                "ctime": 0,
            })
        return {"ok": True, "data": items}
    finally:
        try:
            if browser:
                await browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if pw:
                await pw.stop()
        except Exception:  # noqa: BLE001
            pass


async def _reply(args) -> dict:
    pw = browser = None
    try:
        pw, browser, ctx, page = await _new_page(args.account_file)
        await page.goto(args.aweme_url, wait_until="domcontentloaded",
                        timeout=30000)
        await page.wait_for_timeout(3000)
        # 找到包含 parent-text 的评论行, 点其下的 "回复" 按钮
        try:
            row = page.get_by_text(args.parent_text, exact=False).first
            await row.scroll_into_view_if_needed(timeout=5000)
            reply_btn = page.locator(
                f"text={args.parent_text}"
            ).locator("xpath=..").get_by_text("回复").first
            await reply_btn.click(timeout=5000)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"locate parent failed: {exc}"}
        try:
            box = page.locator("textarea, [contenteditable=true]").last
            await box.fill(args.content)
            await page.wait_for_timeout(500)
            await page.get_by_text("发送", exact=False).first.click(timeout=5000)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"send failed: {exc}"}
        await page.wait_for_timeout(2000)
        return {"ok": True, "data": None}
    finally:
        try:
            if browser:
                await browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if pw:
                await pw.stop()
        except Exception:  # noqa: BLE001
            pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--account-file", default=os.environ.get(
        "DOUYIN_ACCOUNT_FILE",
        "/home/jdh/Projects/VlogCutter/JushenRenji/cache/douyin_cookies.json",
    ))
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("pull")
    pp.add_argument("--aweme-url", required=True)
    pp.add_argument("--since-ts", type=int, default=0)

    pr = sub.add_parser("reply")
    pr.add_argument("--aweme-url", required=True)
    pr.add_argument("--parent-text", required=True)
    pr.add_argument("--content", required=True)

    args = p.parse_args()
    if not Path(args.account_file).expanduser().exists():
        _emit({"ok": False, "error": f"cookie 文件不存在: {args.account_file}"}, 1)

    try:
        if args.cmd == "pull":
            _emit(asyncio.run(_pull(args)))
        elif args.cmd == "reply":
            _emit(asyncio.run(_reply(args)))
        else:
            _emit({"ok": False, "error": f"unknown cmd: {args.cmd}"}, 2)
    except Exception as exc:  # noqa: BLE001
        _emit({"ok": False, "error": f"helper crash: {exc}",
               "tb": traceback.format_exc()[-500:]}, 1)


if __name__ == "__main__":  # pragma: no cover
    main()
