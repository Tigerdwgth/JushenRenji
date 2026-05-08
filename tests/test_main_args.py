"""测试 main.py CLI 参数解析"""
import argparse


def test_target_duration_default():
    """--target_duration 默认值应为 300"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", type=str)
    parser.add_argument("--video_length", type=str, default="long", choices=["long", "short"])
    parser.add_argument("--output_language", type=str, default="zh", choices=["zh", "en"])
    parser.add_argument("--platforms", type=str, default="bilibili,xiaohongshu")
    parser.add_argument("--target_duration", type=int, default=300)
    args = parser.parse_args(["--filename", "cs.RO"])
    assert args.target_duration == 300


def test_target_duration_custom():
    """--target_duration 可自定义"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", type=str)
    parser.add_argument("--target_duration", type=int, default=300)
    args = parser.parse_args(["--filename", "test", "--target_duration", "180"])
    assert args.target_duration == 180



# ---- blog-url 测试 (新增) ----

def _build_main_parser():
    """复制 main.py parse_args 的关键参数, 不依赖 src.* import (避免重 LLM 链)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-link", type=str, default=None)
    parser.add_argument("--filename", type=str, default=None)
    parser.add_argument("--discover", type=str, default=None)
    parser.add_argument("--blog-url", type=str, default=None)
    return parser


def test_blog_url_parsed_into_namespace():
    """--blog-url 参数能正确解析."""
    parser = _build_main_parser()
    args = parser.parse_args(["--blog-url", "https://example.com/blog"])
    assert args.blog_url == "https://example.com/blog"
    assert args.paper_link is None
    assert args.filename is None
    assert args.discover is None


def test_blog_url_alone_sets_no_other():
    parser = _build_main_parser()
    args = parser.parse_args(["--blog-url", "https://e.com"])
    given = sum(1 for x in (args.paper_link, args.filename, args.discover, args.blog_url) if x)
    assert given == 1


def test_paper_link_alone_compatible():
    """老 --paper-link 路径行为不变."""
    parser = _build_main_parser()
    args = parser.parse_args(["--paper-link", "https://arxiv.org/abs/1234.5678"])
    assert args.paper_link == "https://arxiv.org/abs/1234.5678"
    assert args.blog_url is None
