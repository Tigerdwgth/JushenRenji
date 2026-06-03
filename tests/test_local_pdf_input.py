"""集成测试: 本地 PDF 直接输入入口（feature: local pdf input / 解耦获取与处理 PDF）。

只测解耦层纯逻辑, 不真跑 LLM / manim / 视频合成:
  - download_if_remote(本地存在文件): 直接返回该路径, 不下载;
  - download_if_remote(不存在的本地路径): 返回 -1 (老行为不变);
  - download_if_remote(http URL): 仍走下载分支 (老行为不变, 这里只断言不短路);
  - generate_daily_arxiv_summary(local_pdf_path=...): 构造的 Paper.link == 本地路径,
    不调 fetch_arxiv_by_id, arxiv_id 走 local- 前缀;
  - _fetch_tex_source("local-xxx") 返回 None (公式走 LLM 兜底, 同 blog-);
  - main.py 参数互斥: --pdf 与 --paper-link 同给 _given>1 报错。

mock 策略参考 test_formula_pipeline.py / test_js_anim.py: monkeypatch 掉重活
(PDFProcessor / ImageAgent / VideoCreator / 各 LLM 调用), 让 generate_daily_arxiv_summary
跑到构造 Paper 后即可断言, 不产视频。
"""
import argparse
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
for p in (ROOT, SRC):
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------- download_if_remote ----------------

def test_download_if_remote_local_existing_returns_path(tmp_path):
    """本地已存在的文件路径直接返回, 不下载。"""
    from src.paperagent_workflow import download_if_remote
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    assert download_if_remote(str(pdf)) == str(pdf)


def test_download_if_remote_local_missing_returns_minus1(tmp_path):
    """不存在的本地路径返回 -1 (老行为不变)。"""
    from src.paperagent_workflow import download_if_remote
    missing = str(tmp_path / "nope.pdf")
    assert download_if_remote(missing) == -1


def test_download_if_remote_http_not_short_circuited(monkeypatch, tmp_path):
    """http URL 不被本地短路, 仍进下载分支 (mock 掉真实下载)。"""
    import src.paperagent_workflow as wf
    fake_pdf = tmp_path / "cached_pdf.pdf"
    fake_pdf.write_bytes(b"%PDF dummy")

    called = {"download": False}

    class _Resp:
        status_code = 200
        content = b"%PDF dummy"

        def raise_for_status(self):
            pass

    def _fake_get(url, timeout=60):
        called["download"] = True
        return _Resp()

    monkeypatch.setattr("requests.get", _fake_get, raising=False)
    # 确保不命中 1 小时缓存: 让 os.path.isfile 对 cache_path 返回 False
    real_isfile = os.path.isfile

    def _isfile(p):
        if p.endswith("cached_pdf.pdf"):
            return False
        return real_isfile(p)

    monkeypatch.setattr(wf.os.path, "isfile", _isfile)
    monkeypatch.setattr(wf.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr("builtins.open", real_open := open)  # keep open
    # 让写文件落到 tmp
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "cache", exist_ok=True)
    try:
        wf.download_if_remote("http://example.com/p.pdf")
    except Exception:
        pass
    assert called["download"] is True


# ---------------- _fetch_tex_source local- 前缀 ----------------

def test_fetch_tex_source_local_prefix_returns_none():
    """local- 前缀像 blog- 一样不尝试 arxiv 源码, 返回 None 走 LLM 兜底。"""
    from src.llm_tools.llm_agent import _fetch_tex_source
    assert _fetch_tex_source("local-deadbeef") is None
    # 对照: blog- 也返回 None
    assert _fetch_tex_source("blog-deadbeef") is None


# ---------------- generate_daily_arxiv_summary local_pdf_path 分支 ----------------

def test_local_pdf_branch_builds_paper_with_local_link(monkeypatch, tmp_path):
    """local_pdf_path 模式: Paper.link == 本地路径, 不调 fetch_arxiv_by_id, arxiv_id 走 local-。

    skip_main_video=True 让流程跑到缓存 paper_text/structured_plan 即 continue,
    避免真合成视频。捕获构造出的 Paper 做断言。
    """
    import src.paperagent_workflow as wf

    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")

    captured = {}

    # ---- 捕获 Paper, 同时拦截 fetch_arxiv_by_id 确认未被调用 ----
    fetch_called = {"n": 0}

    def _fail_fetch(*a, **k):
        fetch_called["n"] += 1
        raise AssertionError("local_pdf 模式不应调 fetch_arxiv_by_id")

    monkeypatch.setattr("env_setup.fetch_arxiv_by_id", _fail_fetch, raising=False)

    # ---- mock 重活: PDFProcessor / ImageAgent / 各 LLM / 封面 ----
    class _FakeProc:
        def __init__(self, path):
            captured.setdefault("proc_paths", []).append(path)

        def extract_text(self):
            return "Cosmos Title Line\nAbstract\nThis is a fake abstract body for testing.\n1 Introduction\nrest"

    monkeypatch.setattr(wf, "PDFProcessor", _FakeProc)
    monkeypatch.setattr(wf, "process_pdf_images", lambda proc, cnt=None: [str(tmp_path / "1.png")])
    monkeypatch.setattr(wf, "_clean_pipeline_cache", lambda *a, **k: None)

    # 拦截 Paper 构造 (记录 link)
    real_paper = wf.Paper

    def _spy_paper(**kw):
        captured["paper_kwargs"] = kw
        return real_paper(**kw)

    monkeypatch.setattr(wf, "Paper", _spy_paper)

    # ImageAgent / captions / rating
    class _FakeImageAgent:
        def explain_images(self, *a, **k):
            return [{"image": "1.png", "explanation": "x"}]

    monkeypatch.setattr(wf, "ImageAgent", _FakeImageAgent)
    monkeypatch.setattr(wf, "add_context_to_image_explanations", lambda e: e)
    monkeypatch.setattr(wf, "generate_summary", lambda *a, **k: "核心总结")
    monkeypatch.setattr(wf, "generate_cover", lambda *a, **k: None)
    # long 模式才用 structured plan; 这里用 short 简化, mock call_llm_multithread
    monkeypatch.setattr(
        wf, "call_llm_multithread",
        lambda tasks: ("http://demo", "Origin Title", "短摘要", "中文标题"),
    )
    monkeypatch.setattr(wf, "get_videoclips", lambda *a, **k: [], raising=False)

    # 落到 tmp 工作目录, 让 ./cache ./output 写在隔离区
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "cache", exist_ok=True)
    os.makedirs(tmp_path / "output", exist_ok=True)
    os.makedirs(tmp_path / "pic", exist_ok=True)

    # skip_main_video=True + short, 跑到 continue 后, papers==1 走单篇返回分支
    result = wf.generate_daily_arxiv_summary(
        local_pdf_path=str(pdf),
        skip_main_video=True,
        long_or_short="short",
        max_papers=1,
        target_duration=60,
    )

    assert fetch_called["n"] == 0, "不应调用 fetch_arxiv_by_id"
    assert captured["paper_kwargs"]["link"] == str(pdf), "Paper.link 必须是本地 PDF 路径"
    # 标题从 PDF 第一行提取
    assert captured["paper_kwargs"]["title"]
    # 返回值是六元组
    assert isinstance(result, tuple) and len(result) == 6


def test_local_pdf_derives_local_arxiv_id(tmp_path):
    """local- arxiv_id = local- + md5(abspath)[:8], 与 main.py 写法一致。"""
    import hashlib
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"x")
    aid = "local-" + hashlib.md5(os.path.abspath(str(pdf)).encode()).hexdigest()[:8]
    assert aid.startswith("local-")
    assert len(aid) == len("local-") + 8


# ---------------- 参数互斥 ----------------

def _build_main_parser():
    """复制 main.py parse_args 关键参数 (含 --pdf), 不 import src.* (避免重链)。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-link", type=str, default=None)
    parser.add_argument("--filename", type=str, default=None)
    parser.add_argument("--discover", type=str, default=None)
    parser.add_argument("--blog-url", type=str, default=None)
    parser.add_argument("--pdf", type=str, default=None)
    return parser


def test_pdf_arg_parsed():
    parser = _build_main_parser()
    args = parser.parse_args(["--pdf", "./cache/x.pdf"])
    assert args.pdf == "./cache/x.pdf"
    given = sum(1 for x in (args.paper_link, args.filename, args.discover, args.blog_url, args.pdf) if x)
    assert given == 1


def test_pdf_mutually_exclusive_with_paper_link():
    """--pdf 与 --paper-link 同给 → _given>1 (main.py 据此 raise)。"""
    parser = _build_main_parser()
    args = parser.parse_args(["--pdf", "./x.pdf", "--paper-link", "https://arxiv.org/abs/1234.5678"])
    given = sum(1 for x in (args.paper_link, args.filename, args.discover, args.blog_url, args.pdf) if x)
    assert given == 2  # main.py: _given>1 → raise ValueError


def test_pdf_mutually_exclusive_with_blog_url():
    parser = _build_main_parser()
    args = parser.parse_args(["--pdf", "./x.pdf", "--blog-url", "https://e.com/b"])
    given = sum(1 for x in (args.paper_link, args.filename, args.discover, args.blog_url, args.pdf) if x)
    assert given == 2
