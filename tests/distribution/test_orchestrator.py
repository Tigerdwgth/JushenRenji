from src.distribution.orchestrator import (
    parse_platforms,
    upload_generated_content,
    _build_xhs_content,
    _build_bilibili_desc,
    XHS_DEFAULT_TAGS,
)


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

    def fail_xhs_video(**kwargs):
        raise RuntimeError("xhs video error")

    def fail_xhs_note(**kwargs):
        raise RuntimeError("xhs note error")

    monkeypatch.setattr("src.distribution.orchestrator.upload_xiaohongshu_video", fail_xhs_video)
    monkeypatch.setattr("src.distribution.orchestrator.upload_xiaohongshu_note", fail_xhs_note)

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


def test_xhs_video_upload_success(monkeypatch, tmp_path):
    """小红书视频上传成功时应返回 type=video"""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")

    monkeypatch.setattr(
        "src.distribution.orchestrator.upload_xiaohongshu_video",
        lambda **kwargs: {"note_id": "VID123"},
    )

    result = upload_generated_content(
        platforms=["xiaohongshu"],
        video_path=str(video),
        cover_path=None,
        video_title="测试视频",
        video_tags="",
        video_desc="描述",
    )

    assert result["xiaohongshu"]["ok"] is True
    assert result["xiaohongshu"]["type"] == "video"
    assert result["xiaohongshu"]["id"] == "VID123"


def test_xhs_video_fallback_to_note(monkeypatch, tmp_path):
    """小红书视频上传失败时应降级为图文"""
    video = tmp_path / "video.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"x")
    cover.write_bytes(b"x")

    # 模拟 pic 目录下有图片
    pic_dir = tmp_path / "pic"
    pic_dir.mkdir()
    (pic_dir / "img1.png").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)

    def fail_video(**kwargs):
        raise RuntimeError("video upload fail")

    monkeypatch.setattr("src.distribution.orchestrator.upload_xiaohongshu_video", fail_video)
    monkeypatch.setattr(
        "src.distribution.orchestrator.upload_xiaohongshu_note",
        lambda **kwargs: {"note_id": "NOTE456"},
    )

    result = upload_generated_content(
        platforms=["xiaohongshu"],
        video_path=str(video),
        cover_path=str(cover),
        video_title="测试",
        video_tags="",
        video_desc="描述",
    )

    assert result["xiaohongshu"]["ok"] is True
    assert result["xiaohongshu"]["type"] == "note"


def test_xhs_no_video_uses_note(monkeypatch, tmp_path):
    """没有视频文件时应直接使用图文上传"""
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"x")

    monkeypatch.setattr(
        "src.distribution.orchestrator.upload_xiaohongshu_note",
        lambda **kwargs: {"note_id": "NOTE789"},
    )

    result = upload_generated_content(
        platforms=["xiaohongshu"],
        video_path="",
        cover_path=str(cover),
        video_title="测试",
        video_tags="",
        video_desc="描述",
    )

    assert result["xiaohongshu"]["ok"] is True
    assert result["xiaohongshu"]["type"] == "note"


# =========================================================================
# 文案构建测试
# =========================================================================
def test_xhs_content_includes_origin_title():
    """小红书文案必须包含论文原名（英文标题）"""
    content = _build_xhs_content(
        video_desc="",
        cn_titles=["全1比特视觉语言动作模型"],
        origin_titles=["BitVLA: 1-bit Vision-Language-Action Models"],
        summaries=["这是一篇关于1比特模型的论文摘要"],
    )
    assert "BitVLA: 1-bit Vision-Language-Action Models" in content


def test_xhs_content_includes_summary():
    """小红书文案必须包含中文摘要"""
    content = _build_xhs_content(
        video_desc="",
        cn_titles=["中文标题"],
        origin_titles=["English Title"],
        summaries=["这是论文的中文摘要，描述了核心方法和实验结果"],
    )
    assert "摘要：" in content
    assert "中文摘要" in content


def test_xhs_content_includes_cn_title():
    """小红书文案必须包含中文标题"""
    content = _build_xhs_content(
        video_desc="",
        cn_titles=["全1比特VLA模型"],
        origin_titles=["BitVLA"],
        summaries=["摘要内容"],
    )
    assert "全1比特VLA模型" in content


def test_xhs_content_truncates_to_1000():
    """小红书文案不超过1000字"""
    long_summary = "这是一段很长的摘要" * 200
    content = _build_xhs_content(
        video_desc="",
        cn_titles=["标题"],
        origin_titles=["Title"],
        summaries=[long_summary],
    )
    assert len(content) <= 1000


def test_xhs_content_backward_compatible():
    """不传 summaries 时不应报错（向后兼容）"""
    content = _build_xhs_content(
        video_desc="desc",
        cn_titles=["标题"],
        origin_titles=["Title"],
    )
    assert "Title" in content
    assert "标题" in content


def test_bilibili_desc_includes_origin_title():
    """B站描述必须包含论文原名"""
    desc = _build_bilibili_desc(
        video_desc="",
        cn_titles=["中文标题"],
        origin_titles=["BitVLA: 1-bit VLA Models"],
        summaries=["这是摘要"],
    )
    assert "BitVLA: 1-bit VLA Models" in desc


def test_bilibili_desc_includes_summary():
    """B站描述必须包含中文摘要"""
    desc = _build_bilibili_desc(
        video_desc="",
        cn_titles=["中文标题"],
        origin_titles=["Title"],
        summaries=["论文提出了全新的1比特量化方法"],
    )
    assert "1比特量化方法" in desc


def test_bilibili_desc_fallback_no_summaries():
    """没有 summaries 时回退到 video_desc"""
    desc = _build_bilibili_desc(
        video_desc="fallback desc",
        cn_titles=None,
        origin_titles=None,
        summaries=None,
    )
    assert desc == "fallback desc"


def test_bilibili_desc_multi_papers():
    """多篇论文时B站描述应包含所有论文信息"""
    desc = _build_bilibili_desc(
        video_desc="",
        cn_titles=["标题A", "标题B"],
        origin_titles=["Paper A", "Paper B"],
        summaries=["摘要A", "摘要B"],
    )
    assert "Paper A" in desc
    assert "Paper B" in desc
    assert "摘要A" in desc
    assert "摘要B" in desc


def test_upload_passes_summaries_to_bilibili(monkeypatch, tmp_path):
    """验证 summaries 被正确传递到B站描述中"""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")

    captured_desc = {}

    def mock_bilibili(**kwargs):
        captured_desc["desc"] = kwargs.get("desc", "")
        return "BV1TEST"

    monkeypatch.setattr("src.distribution.orchestrator.upload_bilibili", mock_bilibili)

    upload_generated_content(
        platforms=["bilibili"],
        video_path=str(video),
        cover_path=None,
        video_title="测试",
        video_tags="tag",
        video_desc="原始描述",
        cn_titles=["中文标题"],
        origin_titles=["English Paper Title"],
        summaries=["这是论文的中文摘要内容"],
    )

    assert "English Paper Title" in captured_desc["desc"]
    assert "中文摘要" in captured_desc["desc"]


# =========================================================================
# 小红书 Tag 测试
# =========================================================================
def test_xhs_default_tags():
    """默认标签应包含具身智能和VLA"""
    assert "具身智能" in XHS_DEFAULT_TAGS
    assert "VLA" in XHS_DEFAULT_TAGS


def test_xhs_video_receives_default_tags(monkeypatch, tmp_path):
    """小红书视频上传应传入默认标签"""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")

    captured_tags = {}

    def mock_xhs_video(**kwargs):
        captured_tags["tags"] = kwargs.get("tags")
        return {"note_id": "VID_TAG"}

    monkeypatch.setattr("src.distribution.orchestrator.upload_xiaohongshu_video", mock_xhs_video)

    upload_generated_content(
        platforms=["xiaohongshu"],
        video_path=str(video),
        cover_path=None,
        video_title="测试",
        video_tags="",
        video_desc="",
    )

    assert captured_tags["tags"] is not None
    assert "具身智能" in captured_tags["tags"]
    assert "VLA" in captured_tags["tags"]


def test_xhs_custom_tags_merged(monkeypatch, tmp_path):
    """自定义标签应与默认标签合并，去重"""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")

    captured_tags = {}

    def mock_xhs_video(**kwargs):
        captured_tags["tags"] = kwargs.get("tags")
        return {"note_id": "VID_CTAG"}

    monkeypatch.setattr("src.distribution.orchestrator.upload_xiaohongshu_video", mock_xhs_video)

    upload_generated_content(
        platforms=["xiaohongshu"],
        video_path=str(video),
        cover_path=None,
        video_title="测试",
        video_tags="",
        video_desc="",
        xhs_tags=["机器人", "VLA"],  # VLA 与默认重复，应去重
    )

    tags = captured_tags["tags"]
    assert "具身智能" in tags
    assert "VLA" in tags
    assert "机器人" in tags
    assert tags.count("VLA") == 1  # 不重复


def test_xhs_note_fallback_receives_tags(monkeypatch, tmp_path):
    """小红书图文降级上传也应传入标签"""
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"x")

    captured_tags = {}

    def mock_xhs_note(**kwargs):
        captured_tags["tags"] = kwargs.get("tags")
        return {"note_id": "NOTE_TAG"}

    monkeypatch.setattr("src.distribution.orchestrator.upload_xiaohongshu_note", mock_xhs_note)

    upload_generated_content(
        platforms=["xiaohongshu"],
        video_path="",
        cover_path=str(cover),
        video_title="测试",
        video_tags="",
        video_desc="",
    )

    assert "具身智能" in captured_tags["tags"]
    assert "VLA" in captured_tags["tags"]
