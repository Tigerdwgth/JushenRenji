"""js_anim_engine 渲染底座单测。

- test_render_real_html_to_mp4: 真跑 Playwright + ffmpeg, 48帧@24fps → 2.0s mp4。
- test_render_clamps_soft_max:   soft_max 截断生效, 时长 ≈1s。
- test_generate_html_extracts_and_validates: mock subprocess, 主路径落盘 + 契约校验,
  返回存在的 .html 文件路径。
- test_generate_html_fallback_writes_file: fallback 从 stdout 抽内容也落盘并返回路径。
- test_generate_html_returns_none_on_opencode_fail: opencode 失败 → None, 不抛。
"""
import os
import sys
import subprocess
from unittest import mock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from src.js_anim_engine import (
    _opencode_generate_html,
    render_html_to_mp4,
    _find_chromium_executable,
)


# 写死的自包含 HTML: canvas 画一个随帧移动的方块。
_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>html,body{{margin:0}}</style></head>
<body>
<canvas id="c" width="1280" height="720"></canvas>
<script>
window.TOTAL_FRAMES = {total};
window.FPS = {fps};
var cv = document.getElementById("c");
var ctx = cv.getContext("2d");
window.renderFrame = function(n) {{
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, 1280, 720);
  ctx.fillStyle = "#0f0";
  var x = (n * 20) % 1200;
  ctx.fillRect(x, 300, 80, 80);
}};
</script>
</body></html>
"""


def _ffprobe_duration(mp4_path):
    """用 ffprobe 读取 mp4 时长(秒)。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mp4_path],
        capture_output=True, text=True, timeout=60,
    )
    return float(out.stdout.strip())



def _chromium_can_render_file(tmp_path):
    """探针: chromium 能否真正 goto 一个 file:// 页面并渲染。

    某些无头/受限环境下 chromium 可启动 (set_content 正常) 但 goto file://
    会一直卡到超时 (沙箱/文件协议受限)。此时所有真渲染测试都无法跑,
    应当 skip 而非 fail。用一个最小页面做 5s 探针。
    """
    exe = _find_chromium_executable()
    if not exe:
        return False
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    probe = tmp_path / "_probe.html"
    probe.write_text("<!doctype html><html><body>probe</body></html>",
                     encoding="utf-8")
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, executable_path=exe)
            try:
                pg = b.new_page()
                pg.goto("file://%s" % os.path.abspath(str(probe)),
                        wait_until="load", timeout=30000)
            finally:
                b.close()
        return True
    except Exception:
        return False

def test_render_real_html_to_mp4(tmp_path):
    """真跑 playwright+ffmpeg: 48帧@24fps HTML → mp4 时长 ≈2.0s。"""
    if not _find_chromium_executable():
        pytest.skip("无缓存 chromium, 跳过真渲染测试")

    html_path = tmp_path / "anim.html"
    html_path.write_text(_HTML_TEMPLATE.format(total=48, fps=24), encoding="utf-8")
    out_mp4 = tmp_path / "out.mp4"

    result = render_html_to_mp4(str(html_path), str(out_mp4))

    assert result is not None, "渲染应成功返回路径"
    assert os.path.exists(out_mp4), "mp4 应存在"
    dur = _ffprobe_duration(str(out_mp4))
    assert abs(dur - 2.0) <= 0.2, f"时长应 ≈2.0s, 实际 {dur:.3f}s"


def test_render_clamps_soft_max(tmp_path):
    """TOTAL_FRAMES=10000 但 soft_max_seconds=1 → 实际只渲染 ≤24 帧(时长 ≈1s)。"""
    if not _find_chromium_executable():
        pytest.skip("无缓存 chromium, 跳过真渲染测试")

    html_path = tmp_path / "big.html"
    html_path.write_text(_HTML_TEMPLATE.format(total=10000, fps=24), encoding="utf-8")
    out_mp4 = tmp_path / "clamped.mp4"

    result = render_html_to_mp4(
        str(html_path), str(out_mp4), soft_max_seconds=1.0,
    )

    assert result is not None
    assert os.path.exists(out_mp4)
    dur = _ffprobe_duration(str(out_mp4))
    # soft_max=1s @24fps = 24 帧 → 时长 ≈1.0s, 远小于 10000/24≈417s
    assert abs(dur - 1.0) <= 0.2, f"应被截断到 ≈1.0s, 实际 {dur:.3f}s"


def _make_fake_run(temp_dir, scene_name, html_content, returncode=0, stdout=""):
    """构造一个 fake subprocess.run: 模拟 opencode 把 html 写到 cwd 并返回。"""
    def _fake_run(cmd, **kwargs):
        if html_content is not None:
            with open(os.path.join(temp_dir, f"{scene_name}.html"), "w",
                      encoding="utf-8") as f:
                f.write(html_content)
        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout=stdout, stderr="",
        )
    return _fake_run


def test_generate_html_extracts_and_validates(tmp_path):
    """mock subprocess(主路径, opencode Write 落盘):
    合法 html → 返回存在的 .html 文件路径(内容含 canvas/renderFrame);
    缺 renderFrame → None。"""
    temp_dir = str(tmp_path)
    scene = "TestScene"

    # 合法 HTML(fake run 模拟 opencode Write 写到 cwd/<scene>.html)
    good = _HTML_TEMPLATE.format(total=48, fps=24)
    with mock.patch("subprocess.run",
                    side_effect=_make_fake_run(temp_dir, scene, good)):
        ret = _opencode_generate_html("prompt", scene, temp_dir)
    assert ret is not None, "合法 HTML 应通过"
    # 返回的应是存在的 .html 文件路径, 而非内容字符串
    assert os.path.exists(ret), f"应返回存在的文件路径, 实际 {ret!r}"
    assert ret == os.path.join(temp_dir, f"{scene}.html")
    content = open(ret, "r", encoding="utf-8").read()
    assert "<canvas" in content
    assert "renderFrame" in content and "TOTAL_FRAMES" in content

    # 缺 renderFrame 的 HTML → 校验拦截
    bad = """<!doctype html><html><body><canvas id=c></canvas>
<script>window.TOTAL_FRAMES=10;window.FPS=24;</script></body></html>"""
    with mock.patch("subprocess.run",
                    side_effect=_make_fake_run(temp_dir, scene, bad)):
        ret2 = _opencode_generate_html("prompt", scene, temp_dir)
    assert ret2 is None, "缺 renderFrame 应被校验拦截返回 None"


def test_generate_html_fallback_writes_file(tmp_path):
    """fallback 路径: opencode 没用 Write 落盘, 但 stdout 含 ```html``` 代码块,
    内容应被写入 cwd/<scene>.html 并返回该路径。"""
    temp_dir = str(tmp_path)
    scene = "FallbackScene"

    good = _HTML_TEMPLATE.format(total=48, fps=24)
    stdout = "some log\n```html\n" + good + "\n```\nbye\n"
    # html_content=None → fake run 不写 <scene>.html 文件, 只给 stdout
    with mock.patch("subprocess.run",
                    side_effect=_make_fake_run(
                        temp_dir, scene, html_content=None,
                        returncode=0, stdout=stdout)):
        ret = _opencode_generate_html("prompt", scene, temp_dir)
    assert ret is not None, "fallback 合法 HTML 应通过"
    assert os.path.exists(ret), f"fallback 内容应落盘, 实际 {ret!r}"
    assert ret == os.path.join(temp_dir, f"{scene}.html")
    content = open(ret, "r", encoding="utf-8").read()
    assert "<canvas" in content
    assert "renderFrame" in content and "TOTAL_FRAMES" in content


def test_generate_html_returns_none_on_opencode_fail(tmp_path):
    """mock subprocess 返回非0且不写文件且 stdout 空 → None, 不抛。"""
    temp_dir = str(tmp_path)
    scene = "FailScene"

    with mock.patch("subprocess.run",
                    side_effect=_make_fake_run(
                        temp_dir, scene, html_content=None,
                        returncode=1, stdout="")):
        html = _opencode_generate_html("prompt", scene, temp_dir)
    assert html is None, "opencode 失败应返回 None"


def test_generate_then_render_end_to_end(tmp_path):
    """串联集成(堵 Bug#1 漏网): 不 mock _opencode_generate_html / render_html_to_mp4,
    只 mock opencode subprocess(让它把合法自包含 HTML 写到 temp_dir/<scene>.html)。
    真实调用链:
        path = _opencode_generate_html(...)  -> 必须是存在的 .html 文件路径
        mp4  = render_html_to_mp4(path, out) -> 真跑 playwright+ffmpeg
    断言 mp4 存在且时长 == TOTAL_FRAMES/FPS。

    若将来有人把 _opencode_generate_html 改回"返回 HTML 内容(而非路径)",
    render_html_to_mp4 会拿到一段 HTML 字符串当文件路径 -> 渲染必然失败,
    本测试直接挂掉。
    """
    if not _chromium_can_render_file(tmp_path):
        pytest.skip("chromium 不可用或 goto file:// 受限, 跳过串联真渲染测试")

    temp_dir = str(tmp_path)
    scene = "E2EScene"
    total, fps = 48, 24
    good = _HTML_TEMPLATE.format(total=total, fps=fps)

    # 只 mock opencode subprocess: 模拟 opencode 用 Write 工具把 HTML 落盘到 cwd/<scene>.html。
    with mock.patch("subprocess.run",
                    side_effect=_make_fake_run(temp_dir, scene, good)):
        path = _opencode_generate_html("prompt", scene, temp_dir)

    # 1) _opencode_generate_html 必须返回存在的 .html 文件路径(不是内容字符串)
    assert path is not None, "HTML 生成应成功"
    assert isinstance(path, str) and path.endswith(".html"), \
        f"应返回 .html 文件路径而非内容, 实际 {path!r:.80}"
    assert os.path.exists(path), f"返回的路径应真实存在, 实际 {path!r}"

    # 2) 真实把上一步产出的 path 喂给 render_html_to_mp4(不 mock, 真跑 playwright+ffmpeg)
    out_mp4 = os.path.join(temp_dir, f"{scene}.mp4")
    mp4 = render_html_to_mp4(path, out_mp4)

    assert mp4 is not None, "串联渲染应成功返回 mp4 路径"
    assert os.path.exists(out_mp4), "mp4 应存在"
    dur = _ffprobe_duration(out_mp4)
    expected = total / fps  # 48/24 = 2.0s
    assert abs(dur - expected) <= 0.2, \
        f"时长应 ≈ TOTAL_FRAMES/FPS = {expected:.2f}s, 实际 {dur:.3f}s"
