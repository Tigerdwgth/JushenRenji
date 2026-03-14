from src.distribution.orchestrator import parse_platforms, upload_generated_content


def test_parse_platforms_default_dual():
    assert parse_platforms(None) == ["bilibili", "xiaohongshu"]


def test_parse_platforms_none_disables_upload():
    assert parse_platforms("none") == []


def test_parse_platforms_filters_unknown_values():
    assert parse_platforms("bilibili,foo,xiaohongshu") == ["bilibili", "xiaohongshu"]


def test_partial_success_does_not_raise(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"x")
    cover.write_bytes(b"x")

    monkeypatch.setattr(
        "src.distribution.orchestrator.upload_bilibili",
        lambda **kwargs: "BV1TEST",
    )

    def fail_xhs(**kwargs):
        raise RuntimeError("xhs error")

    monkeypatch.setattr("src.distribution.orchestrator.upload_xiaohongshu_note", fail_xhs)

    result = upload_generated_content(
        platforms=["bilibili", "xiaohongshu"],
        video_path=str(video),
        cover_path=str(cover),
        video_title="title",
        video_tags="tag1,tag2",
        video_desc="desc",
        cn_titles=["中文标题"],
        origin_titles=["English title"],
    )

    assert result["bilibili"]["ok"] is True
    assert result["xiaohongshu"]["ok"] is False
