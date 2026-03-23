import os
from pathlib import Path

import pytest

from src.website_video_pipeline import (
    _sanitize_filename,
    download_asset,
    extract_page_metadata,
    forward_website_video,
    parse_args,
    upload_external_video,
    build_publish_title,
)


SAMPLE_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <title>Precise Manipulation with Efficient Online RL</title>
    <meta name="description" content="We extract an RL Token from VLA models to enable fast online RL." />
    <meta property="og:image" content="https://physicalintelligence.company/images/rlt/og.png" />
  </head>
  <body>
    <div>Loading...</div>
    <script>
      self.__next_f.push([1,"14:[[\\\"$\\\",\\\"$L17\\\",null,{\\\"className\\\":\\\"hero\\\",\\\"src\\\":\\\"https://website.pi-asset.com/rlt/hero.mp4\\\"}]]"]);
    </script>
    <script>
      self.__next_f.push([1,"15:[[\\\"$\\\",\\\"$L18\\\",null,{\\\"videos\\\":[{\\\"url\\\":\\\"https://website.pi-asset.com/rlt/secondary.mp4\\\",\\\"title\\\":\\\"secondary\\\"}]}]]"]);
    </script>
    <a href="/download/rlt.pdf">RLT.pdf</a>
  </body>
</html>
"""


def test_extract_page_metadata_returns_expected_fields():
    metadata = extract_page_metadata(
        SAMPLE_HTML,
        page_url="https://www.pi.website/research/rlt",
    )

    assert metadata["title"] == "Precise Manipulation with Efficient Online RL"
    assert metadata["description"] == "We extract an RL Token from VLA models to enable fast online RL."
    assert metadata["cover_url"] == "https://physicalintelligence.company/images/rlt/og.png"
    assert metadata["video_url"] == "https://website.pi-asset.com/rlt/hero.mp4"
    assert metadata["paper_url"] == "https://www.pi.website/download/rlt.pdf"


def test_extract_page_metadata_prefers_hero_src_over_other_videos():
    html = SAMPLE_HTML.replace(
        "https://website.pi-asset.com/rlt/hero.mp4",
        "https://website.pi-asset.com/rlt/top.mp4",
    )
    metadata = extract_page_metadata(
        html,
        page_url="https://www.pi.website/research/rlt",
    )

    assert metadata["video_url"] == "https://website.pi-asset.com/rlt/top.mp4"


def test_sanitize_filename_removes_illegal_chars():
    assert _sanitize_filename("Title: A/B?C*D") == "Title A B C D"


def test_download_asset_saves_file(monkeypatch, tmp_path):
    class FakeResponse:
        def __init__(self, content):
            self.content = content
            self.headers = {"content-type": "video/mp4"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield self.content

    class FakeSession:
        def get(self, url, **kwargs):
            return FakeResponse(b"video-bytes")

    monkeypatch.setattr("src.website_video_pipeline.requests.Session", lambda: FakeSession())

    output = download_asset(
        url="https://example.com/demo.mp4",
        dest_dir=tmp_path,
        filename_stem="demo-video",
    )

    assert output.exists()
    assert output.read_bytes() == b"video-bytes"
    assert output.suffix == ".mp4"


def test_forward_website_video_downloads_and_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.website_video_pipeline.fetch_page_html",
        lambda url, timeout=30: SAMPLE_HTML,
    )

    def fake_download(url, dest_dir, filename_stem):
        suffix = ".png" if url.endswith(".png") else ".mp4"
        path = Path(dest_dir) / f"{filename_stem}{suffix}"
        path.write_bytes(b"x")
        return path

    monkeypatch.setattr("src.website_video_pipeline.download_asset", fake_download)
    monkeypatch.setattr(
        "src.website_video_pipeline.upload_external_video",
        lambda **kwargs: {
            "bilibili": {"ok": True, "id": "BV1TEST"},
            "xiaohongshu": {"ok": True, "type": "video"},
        },
    )

    result = forward_website_video(
        url="https://www.pi.website/research/rlt",
        platforms=["bilibili", "xiaohongshu"],
        work_dir=tmp_path,
    )

    assert result["metadata"]["title"] == "Precise Manipulation with Efficient Online RL"
    assert result["upload"]["bilibili"]["id"] == "BV1TEST"
    assert result["video_path"].endswith(".mp4")
    assert os.path.exists(result["video_path"])


def test_forward_website_video_respects_explicit_empty_platforms(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.website_video_pipeline.fetch_page_html",
        lambda url, timeout=30: SAMPLE_HTML,
    )

    def fake_download(url, dest_dir, filename_stem):
        suffix = ".png" if url.endswith(".png") else ".mp4"
        path = Path(dest_dir) / f"{filename_stem}{suffix}"
        path.write_bytes(b"x")
        return path

    captured = {}

    def fake_upload(**kwargs):
        captured["platforms"] = kwargs["platforms"]
        return {}

    monkeypatch.setattr("src.website_video_pipeline.download_asset", fake_download)
    monkeypatch.setattr("src.website_video_pipeline.upload_external_video", fake_upload)

    result = forward_website_video(
        url="https://www.pi.website/research/rlt",
        platforms=[],
        work_dir=tmp_path,
    )

    assert result["upload"] == {}
    assert captured["platforms"] == []


def test_build_publish_title_prefers_llm_generated_chinese(monkeypatch):
    monkeypatch.setattr(
        "src.website_video_pipeline.generate_video_title",
        lambda text: "精准操作强化学习新突破",
    )

    title = build_publish_title(
        {
            "title": "Precise Manipulation with Efficient Online RL",
            "description": "We extract an RL Token from VLA models.",
        }
    )

    assert title == "精准操作强化学习"


def test_build_publish_title_falls_back_to_keyword_template_when_llm_unavailable(monkeypatch):
    def fail_generate(_text):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr("src.website_video_pipeline.generate_video_title", fail_generate)

    title = build_publish_title(
        {
            "title": "Precise Manipulation with Efficient Online RL",
            "description": "We extract an RL Token from VLA models.",
        }
    )

    assert "精准操作" in title
    assert "在线强化学习" in title
    assert "最新进展" not in title


def test_upload_external_video_uses_chinese_publish_title(monkeypatch, tmp_path):
    captured = {}
    video_path = tmp_path / "demo.mp4"
    video_path.write_bytes(b"x")

    def fake_bilibili(**kwargs):
        captured["bilibili_title"] = kwargs["title"]
        return "BV1TEST"

    def fake_xhs(**kwargs):
        captured["xiaohongshu_title"] = kwargs["title"]
        return {"note_id": "xhs123"}

    monkeypatch.setattr("src.website_video_pipeline.upload_bilibili", fake_bilibili)
    monkeypatch.setattr("src.website_video_pipeline.upload_xiaohongshu_video", fake_xhs)
    monkeypatch.setattr(
        "src.website_video_pipeline.generate_video_title",
        lambda text: "精准操作强化学习新突破",
    )

    result = upload_external_video(
        platforms=["bilibili", "xiaohongshu"],
        video_path=str(video_path),
        cover_path=None,
        metadata={
            "title": "Precise Manipulation with Efficient Online RL",
            "description": "We extract an RL Token from VLA models.",
            "page_url": "https://www.pi.website/research/rlt",
            "paper_url": "https://www.pi.website/download/rlt.pdf",
        },
    )

    assert result["bilibili"]["ok"] is True
    assert captured["bilibili_title"] == "精准操作强化学习"
    assert captured["xiaohongshu_title"] == "精准操作强化学习"[:20]


def test_upload_external_video_descriptions_keep_only_paper_names(monkeypatch, tmp_path):
    captured = {}
    video_path = tmp_path / "demo.mp4"
    video_path.write_bytes(b"x")

    def fake_bilibili(**kwargs):
        captured["bilibili_desc"] = kwargs["desc"]
        return "BV1TEST"

    def fake_xhs(**kwargs):
        captured["xiaohongshu_content"] = kwargs["content"]
        return {"note_id": "xhs123"}

    monkeypatch.setattr("src.website_video_pipeline.upload_bilibili", fake_bilibili)
    monkeypatch.setattr("src.website_video_pipeline.upload_xiaohongshu_video", fake_xhs)
    monkeypatch.setattr(
        "src.website_video_pipeline.generate_video_title",
        lambda text: "精准操作强化学习",
    )

    upload_external_video(
        platforms=["bilibili", "xiaohongshu"],
        video_path=str(video_path),
        cover_path=None,
        metadata={
            "title": "Precise Manipulation with Efficient Online RL",
            "cn_title": "精准操作强化学习",
            "description": "We extract an RL Token from VLA models.",
            "page_url": "https://www.pi.website/research/rlt",
            "paper_url": "https://www.pi.website/download/rlt.pdf",
        },
    )

    assert "Precise Manipulation with Efficient Online RL" in captured["bilibili_desc"]
    assert "https://" not in captured["bilibili_desc"]
    assert "We extract an RL Token" not in captured["bilibili_desc"]
    assert "精准操作强化学习" in captured["xiaohongshu_content"]
    assert "Precise Manipulation with Efficient Online RL" in captured["xiaohongshu_content"]
    assert "https://" not in captured["xiaohongshu_content"]
    assert "We extract an RL Token" not in captured["xiaohongshu_content"]


def test_upload_external_video_treats_empty_xhs_publish_result_as_failure(monkeypatch, tmp_path):
    video_path = tmp_path / "demo.mp4"
    video_path.write_bytes(b"x")

    monkeypatch.setattr(
        "src.website_video_pipeline.generate_video_title",
        lambda text: "精准操作强化学习",
    )
    monkeypatch.setattr(
        "src.website_video_pipeline.upload_xiaohongshu_video",
        lambda **kwargs: None,
    )

    result = upload_external_video(
        platforms=["xiaohongshu"],
        video_path=str(video_path),
        cover_path=None,
        metadata={
            "title": "Precise Manipulation with Efficient Online RL",
            "description": "We extract an RL Token from VLA models.",
        },
    )

    assert result["xiaohongshu"]["ok"] is False


def test_parse_args_supports_url_and_platforms():
    args = parse_args(
        ["--url", "https://www.pi.website/research/rlt", "--platforms", "bilibili"]
    )

    assert args.url == "https://www.pi.website/research/rlt"
    assert args.platforms == "bilibili"
