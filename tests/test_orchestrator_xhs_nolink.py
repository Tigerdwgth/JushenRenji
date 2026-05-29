"""测试小红书文案不含链接 (防限流), B站简介仍保留链接。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
for p in (ROOT, SRC):
    if p not in sys.path:
        sys.path.insert(0, p)

from distribution.orchestrator import _build_xhs_content, _build_bilibili_desc  # noqa: E402

_KW = dict(
    video_desc="FineVLA: Fine-Grained Instruction Alignment",
    cn_titles=["FineVLA: 细粒度指令对齐"],
    origin_titles=["FineVLA: Fine-Grained Instruction Alignment for Steerable VLA Policies"],
    summaries=["这是一段口语化的论文摘要，介绍方法的核心思路与实验结论。"],
    paper_links=["https://arxiv.org/abs/2605.27284"],
    project_links=["https://project.example.com/finevla"],
)


def test_xhs_content_has_no_link():
    c = _build_xhs_content(**_KW)
    assert "http" not in c, c
    assert "链接" not in c, c
    assert "arxiv.org" not in c, c
    assert "project.example.com" not in c, c
    # 仍保留标题/摘要信息
    assert ("FineVLA" in c) or ("细粒度指令对齐" in c)
    assert "摘要" in c


def test_bilibili_desc_has_no_link():
    """B站简介带链接也会被限流, 同样去链接。"""
    d = _build_bilibili_desc(**_KW)
    assert "http" not in d, d
    assert "链接" not in d, d
    assert "arxiv.org" not in d, d
    assert "project.example.com" not in d, d
    # 仍保留标题/摘要信息
    assert "FineVLA" in d
    assert "摘要" in d
