#!/usr/bin/env python3
"""SAU venv 内执行的抖音评论 reply helper (Playwright headed via Xvfb).

读路径 (拉评论) 已迁移到 f2 SDK
(``src/distribution/f2_client.py``), 不再走 Playwright.
本文件仅保留 reply 子命令; 写路径 f2 暂未封装,
仍依赖 SAU venv 里的 patchright headed 浏览器.

reply 模式支持 JSR_USE_CDP_DAEMON=1, 走 connect_over_cdp 复用
chromium-daemon page; 默认仍 launch 独立 chromium。
"""
from __future__ import annotations

import argparse
import asyncio
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


def _use_cdp() -> bool:
    return os.environ.get("JSR_USE_CDP_DAEMON", "0") not in ("0", "", "false", "False")


async def _new_page(account_file: str):
    """Legacy 路径: launch headed browser + new_context with storage_state."""
    from playwright.async_api import async_playwright  # type: ignore
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, args=[
        "--no-sandbox", "--disable-blink-features=AutomationControlled",
    ])
    ctx = await browser.new_context(storage_state=account_file)
    page = await ctx.new_page()
    return pw, browser, ctx, page


async def _do_reply_on_page(page, parent_text: str, content: str) -> dict:
    """通用回帖步骤: 不管 page 来自 legacy launch 还是 CDP daemon。"""
    try:
        row = page.get_by_text(parent_text, exact=False).first
        await row.scroll_into_view_if_needed(timeout=5000)
        reply_btn = page.locator(
            f"text={parent_text}"
        ).locator("xpath=..").get_by_text("回复").first
        await reply_btn.click(timeout=5000)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"locate parent failed: {exc}"}
    try:
        box = page.locator("textarea, [contenteditable=true]").last
        await box.fill(content)
        await page.wait_for_timeout(500)
        await page.get_by_text("发送", exact=False).first.click(timeout=5000)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"send failed: {exc}"}
    await page.wait_for_timeout(2000)
    return {"ok": True, "data": None}


async def _reply_legacy(args) -> dict:
    pw = browser = None
    try:
        pw, browser, ctx, page = await _new_page(args.account_file)
        await page.goto(args.aweme_url, wait_until="domcontentloaded",
                        timeout=30000)
        await page.wait_for_timeout(3000)
        return await _do_reply_on_page(page, args.parent_text, args.content)
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


async def _reply_cdp(args) -> dict:
    """CDP 模式: 复用 chromium-daemon 现有 page, 跑完不写回 cookie。"""
    from src.distribution.sau_helpers.cdp_helpers import (
        get_cdp_page, navigate_and_wait, close_cdp,
    )
    pw, browser, ctx, page = await get_cdp_page(args.daemon_url)
    try:
        await navigate_and_wait(page, args.aweme_url)
        await page.wait_for_timeout(3000)
        return await _do_reply_on_page(page, args.parent_text, args.content)
    finally:
        await close_cdp(pw, browser)


async def _reply(args) -> dict:
    if _use_cdp():
        return await _reply_cdp(args)
    return await _reply_legacy(args)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--account-file", default=os.environ.get(
        "DOUYIN_ACCOUNT_FILE",
        "/home/jdh/Projects/VlogCutter/JushenRenji/cache/douyin_cookies.json",
    ))
    p.add_argument("--daemon-url", default=os.environ.get(
        "JSR_CHROMIUM_DAEMON_URL", "http://localhost:9222"))
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("reply")
    pr.add_argument("--aweme-url", required=True)
    pr.add_argument("--parent-text", required=True)
    pr.add_argument("--content", required=True)

    args = p.parse_args()
    # CDP 模式下 cookie 在 daemon 里, 不强制要求 host 上有 cookie 文件
    if not _use_cdp() and not Path(args.account_file).expanduser().exists():
        _emit({"ok": False, "error": f"cookie 文件不存在: {args.account_file}"}, 1)

    try:
        if args.cmd == "reply":
            _emit(asyncio.run(_reply(args)))
        else:
            _emit({"ok": False, "error": f"unknown cmd: {args.cmd}"}, 2)
    except Exception as exc:  # noqa: BLE001
        _emit({"ok": False, "error": f"helper crash: {exc}",
               "tb": traceback.format_exc()[-500:]}, 1)


if __name__ == "__main__":  # pragma: no cover
    main()
