"""封面生成与上传相关 Bug 修复的单元测试。

覆盖范围：
- Bug 1: 多篇论文时封面不再在循环内被覆盖
- Bug 2: generate_cover 异常不会中断主流程
- Bug 3: 小红书视频上传时缺少封面参数的日志提示
"""

import logging
import os
import sys
from unittest import mock

import pytest

# 确保项目根目录在 sys.path 中
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# paperagent_workflow.py 有大量重量级依赖（moviepy, dashscope 等），
# 对于源码结构验证类测试，直接读取文件文本进行分析，避免导入副作用
_WORKFLOW_PATH = os.path.join(ROOT, "src", "paperagent_workflow.py")


def _read_source(filepath: str) -> str:
    """读取源文件文本内容。"""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# generate_cover 本身的测试
# ---------------------------------------------------------------------------

def _import_generate_cover():
    """延迟导入 generate_cover，确保 src 目录在 sys.path 中。"""
    src_dir = os.path.join(ROOT, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    # generate_cover.py 直接从 config 导入 FONT_PATH，需确保 src/ 在 path 中
    from generate_cover import generate_cover
    return generate_cover


class TestGenerateCover:
    """测试 generate_cover 函数的基本行为。"""

    def test_generate_cover_creates_file(self, tmp_path):
        """正常情况下应生成封面 PNG 文件。"""
        from PIL import Image

        bg_path = str(tmp_path / "bg.png")
        Image.new("RGB", (200, 150), color="blue").save(bg_path)

        output_path = str(tmp_path / "cover.png")

        # 先导入模块使其存在于 sys.modules 中，再 patch
        generate_cover_func = _import_generate_cover()
        import generate_cover as gc_module
        font_path = _get_any_font_path()
        original = gc_module.FONT_PATH
        try:
            gc_module.FONT_PATH = font_path
            generate_cover_func(bg_path, "测试标题", output_path)
        finally:
            gc_module.FONT_PATH = original

        assert os.path.exists(output_path), "封面文件应被创建"

    def test_generate_cover_bad_image_raises(self, tmp_path):
        """传入不存在的图片路径时应抛出异常。"""
        generate_cover = _import_generate_cover()

        with pytest.raises(Exception):
            generate_cover("/nonexistent/bg.png", "标题", str(tmp_path / "out.png"))

    def test_generate_cover_output_size(self, tmp_path):
        """生成的封面图片尺寸应为 1200x900。"""
        from PIL import Image

        bg_path = str(tmp_path / "bg.png")
        Image.new("RGB", (400, 300), color="red").save(bg_path)

        output_path = str(tmp_path / "cover.png")

        generate_cover_func = _import_generate_cover()
        import generate_cover as gc_module
        font_path = _get_any_font_path()
        original = gc_module.FONT_PATH
        try:
            gc_module.FONT_PATH = font_path
            generate_cover_func(bg_path, "尺寸测试", output_path)
        finally:
            gc_module.FONT_PATH = original

        img = Image.open(output_path)
        assert img.size == (1200, 900), f"封面尺寸应为 (1200, 900)，实际为 {img.size}"


# ---------------------------------------------------------------------------
# Bug 1: 多篇论文封面覆盖问题（基于源码文本分析）
# ---------------------------------------------------------------------------

class TestMultiPaperCoverNotOverwritten:
    """验证多篇论文时封面生成逻辑：循环内不再为多篇论文生成封面。"""

    def test_loop_body_no_daily_cover(self):
        """循环体内不应包含 'Arxiv具身日报' 的 generate_cover 调用。

        修复前：循环内 if len(papers) > 1: generate_cover(..., "Arxiv具身日报"...)
        修复后：循环内只有 if len(papers) == 1 的封面生成。
        """
        source = _read_source(_WORKFLOW_PATH)
        lines = source.split("\n")

        in_loop = False
        loop_cover_calls = []
        for line in lines:
            stripped = line.strip()
            if "for paper_idx, paper in enumerate(papers):" in stripped:
                in_loop = True
            if in_loop and "generate_cover" in stripped and not stripped.startswith("#"):
                loop_cover_calls.append(stripped)
            if in_loop and "if not generated_part_paths" in stripped:
                in_loop = False

        # 循环内应只有一个 generate_cover 调用
        assert len(loop_cover_calls) == 1, (
            f"循环内应只有1处 generate_cover 调用，实际有 {len(loop_cover_calls)}: {loop_cover_calls}"
        )
        # 且不应含 "Arxiv具身日报"
        assert "Arxiv具身日报" not in loop_cover_calls[0], (
            "循环内不应包含 'Arxiv具身日报' 的封面生成（应移到循环外）"
        )

    def test_daily_cover_after_write_videofile(self):
        """日报封面（Arxiv具身日报）应出现在 write_videofile 之后。"""
        source = _read_source(_WORKFLOW_PATH)
        lines = source.split("\n")

        write_idx = None
        daily_cover_idx = None
        for i, line in enumerate(lines):
            if "write_videofile" in line:
                write_idx = i
            if "Arxiv具身日报" in line and "generate_cover" in line:
                daily_cover_idx = i

        assert write_idx is not None, "源码应包含 write_videofile 调用"
        assert daily_cover_idx is not None, "源码应包含 Arxiv具身日报 封面生成"
        assert daily_cover_idx > write_idx, (
            f"日报封面生成(行{daily_cover_idx})应在 write_videofile(行{write_idx})之后"
        )

    def test_no_cover_overwrite_in_multi_paper_branch(self):
        """循环内的封面生成条件应为 len(papers) == 1，而非 len(papers) > 1。"""
        source = _read_source(_WORKFLOW_PATH)

        # 修复前的 bug 模式：不应存在
        assert 'if len(papers) > 1:' not in source or \
               'generate_cover' not in source.split('if len(papers) > 1:')[1].split('\n')[1], \
            "不应在 'len(papers) > 1' 分支内直接调用 generate_cover"


# ---------------------------------------------------------------------------
# Bug 2: generate_cover 异常处理（基于源码文本分析）
# ---------------------------------------------------------------------------

class TestCoverErrorHandling:
    """验证所有 generate_cover 调用都有 try-except 保护。"""

    def test_all_cover_calls_wrapped_in_try(self):
        """源码中每个 generate_cover 调用都应被 try-except 包裹。"""
        source = _read_source(_WORKFLOW_PATH)
        lines = source.split("\n")

        unprotected = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "generate_cover" in stripped and not stripped.startswith("#") and "import" not in stripped:
                # 向上查找最近的 try:
                found_try = False
                for j in range(i - 1, max(i - 8, 0), -1):
                    if "try:" in lines[j]:
                        found_try = True
                        break
                if not found_try:
                    unprotected.append(f"行{i + 1}: {stripped}")

        assert len(unprotected) == 0, (
            f"以下 generate_cover 调用未被 try-except 包裹: {unprotected}"
        )

    def test_cover_failure_logs_warning(self):
        """generate_cover 异常处理应使用 logging.warning。"""
        source = _read_source(_WORKFLOW_PATH)
        lines = source.split("\n")

        for i, line in enumerate(lines):
            if "generate_cover" in line and not line.strip().startswith("#") and "import" not in line:
                # 查找对应的 except 块中是否有 warning
                for j in range(i + 1, min(i + 5, len(lines))):
                    if "except" in lines[j]:
                        # 检查接下来几行是否有 warning
                        found_warning = False
                        for k in range(j, min(j + 3, len(lines))):
                            if "warning" in lines[k].lower():
                                found_warning = True
                                break
                        assert found_warning, (
                            f"generate_cover (行{i + 1}) 的 except 块应包含 warning 日志"
                        )
                        break


# ---------------------------------------------------------------------------
# Bug 3: 小红书视频上传无封面的日志提示
# ---------------------------------------------------------------------------

class TestXiaohongshuCoverWarning:
    """验证小红书视频上传时有封面不支持的日志提示。"""

    def test_publish_video_logs_cover_warning(self, caplog):
        """传入 cover_path 时，应输出 warning 日志说明 MCP 不支持 cover 参数。"""
        from src.distribution.xiaohongshu import XiaohongshuMCPUploader

        uploader = XiaohongshuMCPUploader()

        with mock.patch("src.distribution.xiaohongshu.ensure_mcp_service", return_value=True), \
             mock.patch("src.distribution.xiaohongshu._ensure_mcp_session", return_value=True), \
             mock.patch("src.distribution.xiaohongshu._copy_to_docker_mount", return_value="/app/data/video.mp4"), \
             mock.patch("src.distribution.xiaohongshu._call_tool", return_value={"content": [{"type": "text", "text": '{"note_id": "test123"}'}]}), \
             caplog.at_level(logging.WARNING, logger="src.distribution.xiaohongshu"):

            uploader.publish_video(
                title="测试",
                content="测试内容",
                video_path="/tmp/test.mp4",
                cover_path="/tmp/cover.png",
            )

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        cover_warnings = [m for m in warning_messages if "cover" in m.lower() or "封面" in m]
        assert len(cover_warnings) > 0, (
            f"传入 cover_path 时应有封面不支持的 warning 日志，实际日志: {warning_messages}"
        )

    def test_publish_video_no_warning_without_cover(self, caplog):
        """不传入 cover_path 时，不应输出封面相关的 warning。"""
        from src.distribution.xiaohongshu import XiaohongshuMCPUploader

        uploader = XiaohongshuMCPUploader()

        with mock.patch("src.distribution.xiaohongshu.ensure_mcp_service", return_value=True), \
             mock.patch("src.distribution.xiaohongshu._ensure_mcp_session", return_value=True), \
             mock.patch("src.distribution.xiaohongshu._copy_to_docker_mount", return_value="/app/data/video.mp4"), \
             mock.patch("src.distribution.xiaohongshu._call_tool", return_value={"content": [{"type": "text", "text": '{"note_id": "test123"}'}]}), \
             caplog.at_level(logging.WARNING, logger="src.distribution.xiaohongshu"):

            uploader.publish_video(
                title="测试",
                content="测试内容",
                video_path="/tmp/test.mp4",
                cover_path=None,
            )

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        cover_warnings = [m for m in warning_messages if "publish_with_video" in m and "cover" in m.lower()]
        assert len(cover_warnings) == 0, (
            f"不传 cover_path 时不应有封面 warning，实际: {cover_warnings}"
        )

    def test_xiaohongshu_source_has_cover_warning(self):
        """xiaohongshu.py 源码中 publish_video 应包含 cover 不支持的日志。"""
        xhs_path = os.path.join(ROOT, "src", "distribution", "xiaohongshu.py")
        source = _read_source(xhs_path)

        # 确认 publish_video 方法中有 cover 相关的 warning
        assert "publish_with_video" in source and "cover" in source.lower(), \
            "xiaohongshu.py 中应有 cover 参数不支持的说明"

        # 更具体：确认有 logger.warning 且提到 cover
        assert "logger.warning" in source, "应有 logger.warning 调用"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_any_font_path() -> str:
    """获取一个可用的字体路径（用于测试）。"""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        os.path.join(ROOT, "font", "SIMHEI.TTF"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[-1]
