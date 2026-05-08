"""blog_pipeline 单元测试 (mock requests / BeautifulSoup)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from src.blog_pipeline import (
    BlogFetchError,
    extract_body_text,
    extract_image_urls,
    extract_video_urls,
    extract_title,
    extract_published_date,
    fetch_blog_assets,
    materialize_blog_as_paper_cache,
)


# ---- HTML fixtures ----

BLOG_HTML = """<!DOCTYPE html>
<html>
<head>
<title>GENE-26.5: Advancing Manipulation</title>
<meta property="og:title" content="GENE-26.5">
<meta property="og:image" content="https://example.com/cover.png">
<meta name="description" content="Genesis blog post on robotic manipulation">
<meta property="article:published_time" content="2026-05-01T10:00:00Z">
</head>
<body>
<nav><p>Navigation links</p></nav>
<article>
  <h1>Manipulation: why and how</h1>
  <p>This is the first paragraph with detailed methodology description.</p>
  <p>Second paragraph describing the architecture and training procedure.</p>
  <img src="/img/teaser.png" width="1280" height="720">
  <img src="/img/method.png" width="1024" height="768">
  <img src="/img/icon.svg" width="20" height="20">
  <video src="https://cdn.example.com/demo.mp4" controls></video>
  <video><source src="/static/results.webm" type="video/webm"></video>
  <video><source src="https://cdn.example.com/live.m3u8" type="application/x-mpegURL"></video>
</article>
<footer><p>Footer</p></footer>
</body>
</html>
"""


def _soup(html=BLOG_HTML):
    return BeautifulSoup(html, "html.parser")


# ---- extract_body_text ----

def test_body_text_prefers_article_tag():
    text = extract_body_text(_soup())
    assert "first paragraph" in text
    assert "Second paragraph" in text
    # 不应包含 nav/footer 段落
    assert "Navigation links" not in text
    assert "Footer" not in text


def test_body_text_fallback_to_all_p_when_no_article():
    html = "<html><body><p>Hello world content here</p><p>Another paragraph</p></body></html>"
    text = extract_body_text(BeautifulSoup(html, "html.parser"))
    assert "Hello world" in text
    assert "Another paragraph" in text


# ---- extract_image_urls ----

def test_image_urls_filter_small_icons():
    urls = extract_image_urls(_soup(), "https://www.genesis.ai/blog/abc")
    assert all("icon.svg" not in u for u in urls)


def test_image_urls_sort_by_area():
    urls = extract_image_urls(_soup(), "https://www.genesis.ai/blog/abc")
    # teaser (1280*720=921600) > method (1024*768=786432)
    assert urls[0].endswith("teaser.png")
    assert urls[1].endswith("method.png")


def test_image_urls_resolves_relative_to_absolute():
    urls = extract_image_urls(_soup(), "https://www.genesis.ai/blog/abc")
    assert all(u.startswith("https://www.genesis.ai/img/") for u in urls if "img/" in u)


def test_image_urls_max_n_limit():
    html = "".join(f'<img src="/i{i}.png" width="500" height="500">' for i in range(20))
    urls = extract_image_urls(BeautifulSoup(html, "html.parser"), "https://e.com", max_n=5)
    assert len(urls) == 5


# ---- extract_video_urls ----

def test_video_urls_collects_mp4_and_webm():
    urls = extract_video_urls(_soup(), "https://www.genesis.ai/blog/abc")
    # mp4 (绝对) + webm (相对) 都收
    assert any("demo.mp4" in u for u in urls)
    assert any("results.webm" in u for u in urls)


def test_video_urls_filters_m3u8():
    urls = extract_video_urls(_soup(), "https://www.genesis.ai/blog/abc")
    assert all("m3u8" not in u for u in urls)


def test_video_urls_resolves_relative():
    urls = extract_video_urls(_soup(), "https://www.genesis.ai/blog/abc")
    webm = [u for u in urls if "webm" in u]
    assert webm and webm[0].startswith("https://www.genesis.ai/")


# ---- title / date ----

def test_title_prefers_title_tag():
    assert extract_title(_soup(), BLOG_HTML).startswith("GENE-26.5")


def test_published_date_from_meta():
    assert extract_published_date(_soup(), BLOG_HTML) == "2026-05-01"


# ---- fetch_blog_assets (mock requests) ----

class _FakeResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_fetch_blog_assets_ok():
    sess = MagicMock()
    sess.get.return_value = _FakeResp(BLOG_HTML)
    out = fetch_blog_assets("https://example.com/blog", _session=sess)
    assert out["title"].startswith("GENE-26.5")
    assert "first paragraph" in out["body_text"]
    assert len(out["image_urls"]) >= 2
    assert len(out["video_urls"]) >= 2  # mp4 + webm
    assert out["published_date"] == "2026-05-01"


def test_fetch_blog_assets_invalid_url_raises():
    with pytest.raises(BlogFetchError, match="无效"):
        fetch_blog_assets("not-a-url")


def test_fetch_blog_assets_short_content_raises():
    sess = MagicMock()
    sess.get.return_value = _FakeResp("<html></html>")
    with pytest.raises(BlogFetchError, match="过短"):
        fetch_blog_assets("https://e.com/x", _session=sess)


def test_fetch_blog_assets_spa_no_body_raises():
    """SPA 渲染 body 极少, 只有少量 description."""
    spa = ('<html><head><title>X</title>'
           '<meta name="description" content="hi">'
           '</head><body><div id="root"></div></body></html>')
    sess = MagicMock()
    sess.get.return_value = _FakeResp(spa + " " * 200)  # 凑长度
    with pytest.raises(BlogFetchError, match="过少"):
        fetch_blog_assets("https://e.com/x", _session=sess)


# ---- materialize_blog_as_paper_cache (集成测试) ----

def test_materialize_writes_expected_files(tmp_path):
    fake_meta = {
        "page_url": "https://e.com/x",
        "title": "Hello",
        "description": "desc",
        "body_text": "Body content " * 20,
        "image_urls": ["https://e.com/a.png", "https://e.com/b.png"],
        "video_urls": ["https://e.com/v.mp4"],
        "published_date": "2026-05-08",
    }

    # 注入 mock fetch + mock _download_binary
    import src.blog_pipeline as bp
    orig_dl = bp._download_binary

    def fake_dl(url, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE_BYTES_" + url.encode())
        return True

    bp._download_binary = fake_dl
    try:
        record = materialize_blog_as_paper_cache(
            "https://e.com/x",
            cache_dir=str(tmp_path / "cache"),
            pic_dir=str(tmp_path / "pic"),
            clips_dir=str(tmp_path / "cache" / "blog_clips"),
            _fetch_fn=lambda url: fake_meta,
        )
    finally:
        bp._download_binary = orig_dl

    assert (tmp_path / "cache" / "paper_text.txt").exists()
    assert (tmp_path / "pic" / "1.png").exists()
    assert (tmp_path / "pic" / "2.png").exists()
    assert (tmp_path / "cache" / "blog_clips" / "0.mp4").exists()
    assert (tmp_path / "cache" / "blog_meta.json").exists()
    blog_meta = json.loads((tmp_path / "cache" / "blog_meta.json").read_text())
    assert blog_meta["arxiv_id_substitute"].startswith("blog-")
    assert blog_meta["title"] == "Hello"
    assert len(record["image_paths"]) == 2
    assert len(record["clip_paths"]) == 1


def test_materialize_paper_text_includes_title_desc(tmp_path):
    fake_meta = {
        "page_url": "https://e.com/x",
        "title": "MyTitle",
        "description": "MyDesc",
        "body_text": "Article body content " * 20,
        "image_urls": [],
        "video_urls": [],
        "published_date": "2026-05-08",
    }
    materialize_blog_as_paper_cache(
        "https://e.com/x",
        cache_dir=str(tmp_path / "cache"),
        pic_dir=str(tmp_path / "pic"),
        clips_dir=str(tmp_path / "cache" / "clips"),
        _fetch_fn=lambda url: fake_meta,
    )
    text = (tmp_path / "cache" / "paper_text.txt").read_text(encoding="utf-8")
    assert "标题: MyTitle" in text
    assert "摘要: MyDesc" in text
    assert "Article body content" in text
