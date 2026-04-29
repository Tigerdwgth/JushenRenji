"""真启 chromium_daemon 子进程, curl health, SIGTERM 收尾。

不 mock。daemon 必须在 SAU venv 跑(patchright 在那), 测试主体在 paperagent venv。
跑这个测试需要:
- SAU venv 路径: SAU_VENV (默认 /home/jdh/Projects/VlogCutter/third_party/social-auto-upload/.venv)
- DISPLAY=:99 (Xvfb 已起或 daemon 自己 ensure)
- 9223 端口空闲(测试用 9224 避开生产端口)
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


def _xvfb_available() -> bool:
    return shutil.which("Xvfb") is not None


@pytest.mark.skipif(
    not (SAU_VENV / "bin" / "python").exists(),
    reason=f"SAU venv 不存在: {SAU_VENV}",
)
@pytest.mark.skipif(not _xvfb_available(), reason="Xvfb 未安装")
def test_daemon_starts_health_endpoint_and_shuts_down_cleanly(tmp_path):
    """启动 daemon, 等 health 200, 取 current-url, SIGTERM 退出, 检查返回码非 -SIGKILL。"""
    cdp_port = 19222  # 避开生产 9222
    health_port = 19223  # 避开生产 9223
    if not _port_free(cdp_port) or not _port_free(health_port):
        pytest.skip(f"测试端口被占用: {cdp_port}/{health_port}")

    cookie_path = tmp_path / "douyin_cookies.json"  # 不存在 -> logged_out 状态
    env = os.environ.copy()
    env["JSR_CHROMIUM_DAEMON_CDP_PORT"] = str(cdp_port)
    env["JSR_CHROMIUM_DAEMON_HEALTH_PORT"] = str(health_port)
    env["JSR_CHROMIUM_DAEMON_COOKIE"] = str(cookie_path)
    # nav 一个本地 file:// 而不是 douyin, 避免外网依赖
    blank_html = tmp_path / "blank.html"
    blank_html.write_text(
        "<html><head><title>blank</title></head><body>blank</body></html>")
    env["JSR_CHROMIUM_DAEMON_HOME_URL"] = f"file://{blank_html}"
    env["DISPLAY"] = env.get("DISPLAY", ":99")
    env["PYTHONPATH"] = f"{REPO_ROOT}:{env.get('PYTHONPATH', '')}"

    proc = subprocess.Popen(
        [str(SAU_VENV / "bin" / "python"), "-u", "-m", "src.chromium_daemon"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    health_url = f"http://127.0.0.1:{health_port}"
    try:
        # 等 health 就绪 (chromium 启动可能 5-15s)
        deadline = time.time() + 60
        last_err: Exception | None = None
        ready_payload: dict | None = None
        while time.time() < deadline:
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
                pytest.fail(
                    f"daemon 提前退出, rc={proc.returncode}, stderr 末尾:\n"
                    f"{stderr[-2000:]}")
            try:
                r = requests.get(f"{health_url}/health", timeout=2)
                if r.status_code == 200:
                    body = r.json()
                    if body.get("status") in ("ready", "logged_out"):
                        ready_payload = body
                        break
            except Exception as exc:
                last_err = exc
            time.sleep(1)
        if ready_payload is None:
            stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            pytest.fail(
                f"daemon health 60s 内未就绪, last_err={last_err}\n"
                f"stderr 末尾:\n{stderr[-2000:]}")

        assert ready_payload["status"] == "logged_out"

        # current-url 应当是 home_url (file://...)
        r = requests.get(f"{health_url}/current-url", timeout=5)
        assert r.status_code == 200
        url = r.json().get("url", "")
        assert url.startswith("file://"), f"unexpected url: {url}"
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            pytest.fail("daemon SIGTERM 后 20s 内未退出")
        # 优雅退出 rc 应为 0 或 -SIGTERM (-15), 不应 -SIGKILL
        assert proc.returncode != -signal.SIGKILL, "daemon 被 SIGKILL"
