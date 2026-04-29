"""真启 chromium-daemon, 通过 CDP attach 取 page url, 不 mock。

运行需要 SAU venv (patchright 在那) + Xvfb + daemon 子进程。
为复用 daemon 启动逻辑, 这里独立启一个端口隔离的 daemon 实例。
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
SAU_VENV = Path(os.environ.get(
    "SAU_VENV",
    "/home/jdh/Projects/VlogCutter/third_party/social-auto-upload/.venv",
))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


@pytest.fixture(scope="module")
def daemon(tmp_path_factory):
    if not (SAU_VENV / "bin" / "python").exists():
        pytest.skip(f"SAU venv 不存在: {SAU_VENV}")
    if not shutil.which("Xvfb"):
        pytest.skip("Xvfb 未安装")
    cdp_port = 19232
    health_port = 19233
    if not _port_free(cdp_port) or not _port_free(health_port):
        pytest.skip(f"端口被占: {cdp_port}/{health_port}")

    tmp = tmp_path_factory.mktemp("daemon")
    cookie_path = tmp / "cookies.json"
    blank = tmp / "blank.html"
    blank.write_text("<html><body>cdp-test</body></html>")

    env = os.environ.copy()
    env["JSR_CHROMIUM_DAEMON_CDP_PORT"] = str(cdp_port)
    env["JSR_CHROMIUM_DAEMON_HEALTH_PORT"] = str(health_port)
    env["JSR_CHROMIUM_DAEMON_COOKIE"] = str(cookie_path)
    env["JSR_CHROMIUM_DAEMON_HOME_URL"] = f"file://{blank}"
    env["DISPLAY"] = env.get("DISPLAY", ":99")
    env["PYTHONPATH"] = f"{REPO_ROOT}:{env.get('PYTHONPATH', '')}"

    proc = subprocess.Popen(
        [str(SAU_VENV / "bin" / "python"), "-u", "-m", "src.chromium_daemon"],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    health = f"http://127.0.0.1:{health_port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            pytest.fail(f"daemon 提前退出 rc={proc.returncode}\n{err[-2000:]}")
        try:
            r = requests.get(f"{health}/health", timeout=2)
            if r.status_code == 200 and r.json().get("status") in ("ready", "logged_out"):
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        proc.kill()
        pytest.fail("daemon 60s 内未就绪")

    yield {
        "cdp_url": f"http://127.0.0.1:{cdp_port}",
        "health_url": health,
        "blank_url": f"file://{blank}",
    }
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_get_cdp_page_returns_existing_page(daemon):
    """connect_over_cdp 复用 daemon default context 的第一个 page, url 是 daemon nav 的 home_url。"""
    code = (
        "import asyncio, json, sys\n"
        "from src.distribution.sau_helpers.cdp_helpers import "
        "get_cdp_page, navigate_and_wait, close_cdp\n"
        f"DAEMON_URL = {daemon['cdp_url']!r}\n"
        f"BLANK_URL = {daemon['blank_url']!r}\n"
        "async def main():\n"
        "    pw, browser, ctx, page = await get_cdp_page(DAEMON_URL)\n"
        "    try:\n"
        "        url = page.url\n"
        "        ctx_count = len(browser.contexts)\n"
        "        page_count = len(ctx.pages)\n"
        "        print(json.dumps({\n"
        "            'url': url,\n"
        "            'ctx_count': ctx_count,\n"
        "            'page_count': page_count,\n"
        "        }))\n"
        "    finally:\n"
        "        await close_cdp(pw, browser)\n"
        "asyncio.run(main())\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
    proc = subprocess.run(
        [str(SAU_VENV / "bin" / "python"), "-c", code],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr[-1500:]}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ctx_count"] >= 1
    assert payload["page_count"] >= 1
    assert payload["url"].startswith("file://"), payload


def test_navigate_and_wait_uses_existing_page(daemon, tmp_path):
    """navigate_and_wait 复用同一 page (不 new_page) 跳转到新 URL。"""
    other = tmp_path / "other.html"
    other.write_text("<html><body>other</body></html>")
    other_url = f"file://{other}"
    code = (
        "import asyncio, json\n"
        "from src.distribution.sau_helpers.cdp_helpers import "
        "get_cdp_page, navigate_and_wait, close_cdp\n"
        f"DAEMON_URL = {daemon['cdp_url']!r}\n"
        f"OTHER_URL = {other_url!r}\n"
        "async def main():\n"
        "    pw, browser, ctx, page = await get_cdp_page(DAEMON_URL)\n"
        "    try:\n"
        "        before_pages = len(ctx.pages)\n"
        "        await navigate_and_wait(page, OTHER_URL)\n"
        "        after_pages = len(ctx.pages)\n"
        "        print(json.dumps({\n"
        "            'before': before_pages,\n"
        "            'after': after_pages,\n"
        "            'url': page.url,\n"
        "        }))\n"
        "    finally:\n"
        "        await close_cdp(pw, browser)\n"
        "asyncio.run(main())\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
    proc = subprocess.run(
        [str(SAU_VENV / "bin" / "python"), "-c", code],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr[-1500:]}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    # 没新开 page
    assert payload["after"] == payload["before"]
    assert payload["url"] == other_url
