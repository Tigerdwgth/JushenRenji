"""测试 generate_daily_arxiv_summary 的 skip_main_video 开关 (manim-only 模式)。

skip_main_video=True 时:
- 不调 video_creator.create_video()
- 不调 generate_cover (单篇分支)
- 不调 os.replace 物理重命名
- 仍产出 cn_titles / summaries / paper_links / project_links
- 返回 path 是 `<date>_<cn_title>.mp4` 形式的预定路径 (字符串非空)

skip_main_video=False (默认) 时行为完全不变。
"""
import datetime
import os
import re
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
for p in (ROOT, SRC):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def fake_paper():
    """伪造一个 arxiv Paper 对象 (兼容 paperagent_workflow 内部 Paper 数据类)。"""
    from get_arxiv_latest import Paper
    return Paper(
        title="Fake Paper For Manim Only Test",
        authors=["A. Test"],
        abstract="abs.",
        link="https://arxiv.org/abs/9999.00001",
        announced_date="2026-04-29T00:00:00Z",
        submitted_date="2026-04-29T00:00:00Z",
        comments="",
    )


@pytest.fixture
def workflow_module():
    import paperagent_workflow as wf
    return wf


def _install_common_mocks(monkeypatch, wf, fake_paper):
    """patch 所有外部副作用 (网络/LLM/文件系统/视频), 让 generate_daily_arxiv_summary 可纯逻辑跑。"""
    # 跳过 cache 清理 (避免删测试目录)
    monkeypatch.setattr(wf, "_clean_pipeline_cache", lambda *a, **k: None)

    # paper_link 分支会 import env_setup, 直接 patch 模块入口
    import env_setup
    monkeypatch.setattr(env_setup, "parse_arxiv_link", lambda link: "9999.00001")
    monkeypatch.setattr(env_setup, "fetch_arxiv_by_id", lambda aid: {
        "title": fake_paper.title,
        "abstract": fake_paper.abstract,
        "submitted_date": "2026-04-29",
        "updated_date": "2026-04-29",
        "pdf_url": "https://arxiv.org/pdf/9999.00001.pdf",
    })

    # PDF 下载 / 处理
    monkeypatch.setattr(wf, "download_if_remote", lambda url: "./cache/cached_pdf.pdf")

    pdf_proc = MagicMock()
    pdf_proc.extract_text.return_value = "Fake paper text. " * 50
    monkeypatch.setattr(wf, "PDFProcessor", lambda *a, **k: pdf_proc)

    # 图片提取: 返回 1 张 PIL fake image
    fake_img = MagicMock()
    monkeypatch.setattr(wf, "process_pdf_images", lambda *a, **k: [fake_img])

    # 图像 agent
    fake_image_agent = MagicMock()
    fake_image_agent.explain_images.return_value = [{"image_index": 0, "explanation": "x"}]
    monkeypatch.setattr(wf, "ImageAgent", lambda *a, **k: fake_image_agent)

    # caption 抽取
    if hasattr(wf, "extract_captions_from_pdf") and wf.extract_captions_from_pdf is not None:
        monkeypatch.setattr(wf, "extract_captions_from_pdf", lambda *a, **k: {})

    # demo 视频
    monkeypatch.setattr(wf, "get_videoclips", lambda *a, **k: [])

    # LLM 调用
    monkeypatch.setattr(wf, "generate_summary", lambda *a, **k: "core summary")
    monkeypatch.setattr(wf, "generate_origin_title", lambda *a, **k: "Fake Paper For Manim Only Test")
    monkeypatch.setattr(wf, "generate_video_title", lambda *a, **k: "测试中文标题")
    monkeypatch.setattr(wf, "get_paper_demo_website", lambda *a, **k: "")
    monkeypatch.setattr(wf, "rate_image_importance", lambda caps: [5] * len(caps))
    monkeypatch.setattr(wf, "select_top_images", lambda imgs, scores, top_n=5: imgs[:top_n])
    monkeypatch.setattr(wf, "add_context_to_image_explanations", lambda x: x)
    monkeypatch.setattr(wf, "generate_structured_video_plan", lambda *a, **k: {
        "opening": "op", "intro": "in", "method": "me", "results": "re", "conclusion": "co"
    })
    monkeypatch.setattr(wf, "structured_plan_to_text", lambda plan: "merged structured text")
    monkeypatch.setattr(wf, "generate_short_summary", lambda *a, **k: "short summary")

    # 封面 / video creator / 上传 hook
    monkeypatch.setattr(wf, "generate_cover", MagicMock())
    monkeypatch.setattr(wf, "_record_published_safe", lambda *a, **k: None)


def _make_video_creator_mock(create_video_calls):
    """构造一个 VideoCreator factory, 记录 create_video 调用次数, 实际产出文件供后续 os.replace。"""
    def factory(*args, **kwargs):
        instance = MagicMock()
        def fake_create_video(save_path):
            create_video_calls.append(save_path)
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(b"FAKEMP4")
            return save_path
        instance.create_video.side_effect = fake_create_video
        return instance
    return factory


# ============================================================================
# Test cases
# ============================================================================

def test_skip_main_video_skips_video_creator(tmp_path, monkeypatch, workflow_module, fake_paper):
    """skip_main_video=True 时 VideoCreator.create_video 完全不被调用。"""
    wf = workflow_module
    _install_common_mocks(monkeypatch, wf, fake_paper)
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "output", exist_ok=True)

    create_video_calls = []
    monkeypatch.setattr(wf, "VideoCreator", _make_video_creator_mock(create_video_calls))

    path, titles, cn_titles, summaries, paper_links, project_links = wf.generate_daily_arxiv_summary(
        query="test",
        max_papers=1,
        date="2026-04-29",
        long_or_short="long",
        target_duration=60,
        paper_link="https://arxiv.org/abs/9999.00001",
        skip_main_video=True,
    )

    assert create_video_calls == [], f"VideoCreator.create_video 不应被调用, 实际: {create_video_calls}"


def test_skip_main_video_returns_metadata(tmp_path, monkeypatch, workflow_module, fake_paper):
    """skip_main_video=True 时仍产出 cn_titles / summaries / paper_links。"""
    wf = workflow_module
    _install_common_mocks(monkeypatch, wf, fake_paper)
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "output", exist_ok=True)
    monkeypatch.setattr(wf, "VideoCreator", _make_video_creator_mock([]))

    path, titles, cn_titles, summaries, paper_links, project_links = wf.generate_daily_arxiv_summary(
        query="test",
        max_papers=1,
        date="2026-04-29",
        long_or_short="long",
        target_duration=60,
        paper_link="https://arxiv.org/abs/9999.00001",
        skip_main_video=True,
    )

    assert len(cn_titles) == 1, f"cn_titles 应有一条, 实际: {cn_titles}"
    assert cn_titles[0] == "测试中文标题"
    assert len(summaries) == 1 and summaries[0]
    assert len(paper_links) == 1 and "9999.00001" in paper_links[0]
    assert len(project_links) == 1
    assert len(titles) == 1


def test_default_behavior_unchanged(tmp_path, monkeypatch, workflow_module, fake_paper):
    """skip_main_video=False (默认) 时, VideoCreator.create_video 必须被调用一次。"""
    wf = workflow_module
    _install_common_mocks(monkeypatch, wf, fake_paper)
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "output", exist_ok=True)

    create_video_calls = []
    monkeypatch.setattr(wf, "VideoCreator", _make_video_creator_mock(create_video_calls))

    path, titles, cn_titles, summaries, paper_links, project_links = wf.generate_daily_arxiv_summary(
        query="test",
        max_papers=1,
        date="2026-04-29",
        long_or_short="long",
        target_duration=60,
        paper_link="https://arxiv.org/abs/9999.00001",
        # skip_main_video 默认 False
    )

    assert len(create_video_calls) == 1, f"默认行为下 create_video 应被调一次, 实际: {create_video_calls}"
    # 默认行为下产物文件 (经过 os.replace 重命名后) 必须实际存在
    assert os.path.exists(path), f"默认 path 应存在: {path}"


def test_skip_main_video_returns_predicted_path(tmp_path, monkeypatch, workflow_module, fake_paper):
    """skip_main_video=True 时 path 是预定路径 (字符串非空, 不要求文件存在)。"""
    wf = workflow_module
    _install_common_mocks(monkeypatch, wf, fake_paper)
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "output", exist_ok=True)
    monkeypatch.setattr(wf, "VideoCreator", _make_video_creator_mock([]))

    path, *_ = wf.generate_daily_arxiv_summary(
        query="test",
        max_papers=1,
        date="2026-04-29",
        long_or_short="long",
        target_duration=60,
        paper_link="https://arxiv.org/abs/9999.00001",
        skip_main_video=True,
    )

    assert isinstance(path, str) and len(path) > 0, f"path 应为非空字符串: {path!r}"
    assert path.endswith(".mp4"), f"path 应以 .mp4 结尾: {path}"
    # skip_main_video 下文件不应存在 (manim 阶段才写入)
    assert not os.path.exists(path), f"skip_main_video=True 时 path 不应存在: {path}"


def test_path_naming_format(tmp_path, monkeypatch, workflow_module, fake_paper):
    """skip_main_video=True 时 path 文件名形如 `<YYYY-MM-DD>_<cn_title>.mp4`, 与默认行为一致。"""
    wf = workflow_module
    _install_common_mocks(monkeypatch, wf, fake_paper)
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "output", exist_ok=True)
    monkeypatch.setattr(wf, "VideoCreator", _make_video_creator_mock([]))

    path, *_ = wf.generate_daily_arxiv_summary(
        query="test",
        max_papers=1,
        date="2026-04-29",
        long_or_short="long",
        target_duration=60,
        paper_link="https://arxiv.org/abs/9999.00001",
        skip_main_video=True,
    )

    basename = os.path.basename(path)
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_.+\.mp4$")
    assert pattern.match(basename), (
        f"path basename 应形如 <YYYY-MM-DD>_<title>.mp4, 实际: {basename!r}"
    )
    # 且日期字段应当是今日 (`generate_daily_arxiv_summary` 里 `date_str=now()`)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    assert basename.startswith(today + "_"), f"path 应以今日日期开头: {basename}"
    # 且 cn_title 出现在文件名里
    assert "测试中文标题" in basename
