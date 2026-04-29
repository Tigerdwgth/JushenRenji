"""通过 CDP attach 复用 chromium-daemon 中现有 page 的小工具。

由 SAU 上传 helper / 评论回帖 helper / 扫码登录脚本共享。
所有函数在 SAU venv 内执行(import patchright)。

关键约定:
- daemon 启动时 launch chromium 并 new_context(已加载 cookie), 我们 connect_over_cdp
  之后取 browser.contexts[0] (默认 context), 再取它的 pages[0] 复用。
- **绝对不要** 在 attach 完跑完任务后调 context.storage_state(path=...) 写回 cookie,
  这会和 daemon 自身退出时的写回竞争, 且 SAU 老坑里发现这一步多次破坏 cookie。
- daemon 退出时统一一次写回。
"""
from __future__ import annotations

import logging
import os
from typing import Tuple

logger = logging.getLogger(__name__)

DEFAULT_DAEMON_URL = os.environ.get(
    "JSR_CHROMIUM_DAEMON_URL",
    "http://localhost:9222",
)


async def get_cdp_browser(daemon_url: str = DEFAULT_DAEMON_URL):
    """connect_over_cdp 拿到 browser。调用方负责 close 自己的 playwright instance。"""
    from patchright.async_api import async_playwright  # type: ignore
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(daemon_url)
    return pw, browser


async def get_cdp_page(daemon_url: str = DEFAULT_DAEMON_URL) -> Tuple[object, object, object, object]:
    """连接 daemon, 返回 (pw, browser, context, page).

    取 default context 的第一个 page。如果 default context 还没 page (理论上 daemon
    启动后必然有 home_url page), 会新开一个空白 page; 但常态下 daemon 已经 nav 到
    creator.douyin.com, 直接复用。
    """
    pw, browser = await get_cdp_browser(daemon_url)
    contexts = browser.contexts
    if not contexts:
        raise RuntimeError(
            f"daemon {daemon_url} 没有任何 browser context, 检查 daemon 是否就绪")
    context = contexts[0]
    pages = context.pages
    if pages:
        page = pages[0]
    else:
        page = await context.new_page()
    return pw, browser, context, page


async def navigate_and_wait(page, url: str, timeout: int = 30000,
                             wait_until: str = "domcontentloaded") -> None:
    """复用现有 page 跳到 url, 不再 new_page。"""
    if page.url == url:
        return
    await page.goto(url, wait_until=wait_until, timeout=timeout)


async def close_cdp(pw, browser) -> None:
    """断开 CDP 连接但**不关 daemon 的 chromium**。

    connect_over_cdp 返回的 browser.close() 只断 CDP 连接, 不杀进程; 但稳妥起见,
    我们只 stop 自己的 playwright, 让 GC 处理 browser 引用。
    """
    try:
        await pw.stop()
    except Exception as exc:
        logger.warning("close playwright 异常: %s", exc)
