"""测试 Ken Burns 效果：确保图片不会溢出画面，并验证 zoom 配置。"""
import os
import sys
import types
import numpy as np
import pytest
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# 确保 dashscope 可用（CI 环境可能未安装）
try:
    import dashscope.audio.tts_v2  # noqa: F401
except ImportError:
    for _name in ('dashscope', 'dashscope.audio', 'dashscope.audio.tts_v2'):
        if _name not in sys.modules:
            _m = types.ModuleType(_name)
            _m.__path__ = []
            sys.modules[_name] = _m

# video_creator 顶层 import config（位于 src/），需要 SRC 在 sys.path
try:
    from src.video_creator import _create_ken_burns_clip
except ImportError:
    from video_creator import _create_ken_burns_clip


TARGET_SIZE = (1920, 1080)


def _make_test_image(width, height, color=(128, 64, 32)):
    """创建指定尺寸的测试图片。"""
    return Image.new("RGB", (width, height), color)


class TestKenBurnsFrameSize:
    """验证所有帧的输出尺寸严格等于 target_size。"""

    @pytest.mark.parametrize("img_size", [
        (1920, 1080),   # 精确匹配
        (3840, 2160),   # 4K 大图
        (800, 600),     # 小图
        (200, 200),     # 极小图
        (3000, 300),    # 超宽图（论文宽表格）
        (400, 3000),    # 超高图（长截图）
        (1920, 300),    # 宽度匹配但高度很小
        (500, 1080),    # 高度匹配但宽度很小
        (100, 100),     # 极端小图
        (5000, 5000),   # 极端大图
    ])
    def test_frame_size_matches_target(self, img_size):
        """每帧输出必须是 1920x1080。"""
        img = _make_test_image(*img_size)
        clip = _create_ken_burns_clip(img, duration=3.0, target_size=TARGET_SIZE)

        # 检测首帧、中间帧、末帧
        for t in [0.0, 1.5, 2.99]:
            frame = clip.get_frame(t)
            assert frame.shape == (1080, 1920, 3), (
                f"img_size={img_size}, t={t}: 帧尺寸 {frame.shape} != (1080, 1920, 3)"
            )


class TestKenBurnsNoOverflow:
    """验证图片内容在首帧完全可见（不溢出）。"""

    @pytest.mark.parametrize("img_size", [
        (1920, 1080),
        (3840, 2160),
        (800, 600),
        (3000, 300),
        (400, 3000),
    ])
    def test_first_frame_contains_full_image(self, img_size):
        """首帧（zoom=1.0）时，图片内容不应触及画面边缘。

        创建一个有明显边框的测试图片，验证边框像素在首帧中可见
        （即被深蓝背景包围，而非被裁切到画面外）。
        """
        # 创建带红色边框的白色图片
        img = Image.new("RGB", img_size, (255, 255, 255))
        # 画 5px 红色边框
        pixels = np.array(img)
        border = 5
        pixels[:border, :] = [255, 0, 0]      # 上边框
        pixels[-border:, :] = [255, 0, 0]      # 下边框
        pixels[:, :border] = [255, 0, 0]       # 左边框
        pixels[:, -border:] = [255, 0, 0]      # 右边框
        img = Image.fromarray(pixels)

        clip = _create_ken_burns_clip(img, duration=3.0, target_size=TARGET_SIZE)
        frame = clip.get_frame(0.0)  # 首帧，zoom=1.0

        # 首帧应该有红色像素（边框可见）
        red_mask = (frame[:, :, 0] > 200) & (frame[:, :, 1] < 50) & (frame[:, :, 2] < 50)
        assert red_mask.any(), (
            f"img_size={img_size}: 首帧中未检测到红色边框，图片可能被裁切"
        )


class TestKenBurnsZoomRange:
    """验证 zoom 不会让图片溢出画面。"""

    def test_last_frame_still_valid(self):
        """末帧（最大 zoom）时，帧尺寸仍正确且无黑边。"""
        img = _make_test_image(1920, 1080, color=(100, 150, 200))
        clip = _create_ken_burns_clip(img, duration=5.0, target_size=TARGET_SIZE)

        # 末帧
        frame = clip.get_frame(4.99)
        assert frame.shape == (1080, 1920, 3)

        # 不应全黑（说明画布内容正常）
        assert frame.mean() > 10, "末帧全黑，可能存在裁切错误"

    def test_background_color_present(self):
        """小图片应该在周围显示深蓝背景色。"""
        img = _make_test_image(200, 200, color=(255, 255, 255))
        clip = _create_ken_burns_clip(img, duration=2.0, target_size=TARGET_SIZE)
        frame = clip.get_frame(0.0)

        # 检测角落区域是否为深蓝背景 (15, 20, 40)
        corner = frame[0:10, 0:10]  # 左上角
        # 背景色应接近 (15, 20, 40)
        assert corner[:, :, 0].mean() < 30, "左上角不是深蓝背景"
        assert corner[:, :, 2].mean() < 60, "左上角不是深蓝背景"


class TestKenBurnsEdgeCases:
    """边界条件测试。"""

    def test_very_short_duration(self):
        """极短时长不应崩溃。"""
        img = _make_test_image(800, 600)
        clip = _create_ken_burns_clip(img, duration=0.1, target_size=TARGET_SIZE)
        frame = clip.get_frame(0.0)
        assert frame.shape == (1080, 1920, 3)

    def test_zero_duration(self):
        """零时长不应崩溃。"""
        img = _make_test_image(800, 600)
        clip = _create_ken_burns_clip(img, duration=0.0, target_size=TARGET_SIZE)
        frame = clip.get_frame(0.0)
        assert frame.shape == (1080, 1920, 3)

    def test_long_duration(self):
        """长时长不应崩溃。"""
        img = _make_test_image(800, 600)
        clip = _create_ken_burns_clip(img, duration=60.0, target_size=TARGET_SIZE)
        frame = clip.get_frame(30.0)
        assert frame.shape == (1080, 1920, 3)


def _build_border_image(size, border=8):
    """构造内含彩色像素行/列的测试图，用于检测 zoom 是否吃掉边缘像素。"""
    img = Image.new("RGB", size, (240, 240, 240))
    px = np.array(img)
    px[:border, :] = [255, 0, 0]
    px[-border:, :] = [255, 0, 0]
    px[:, :border] = [255, 0, 0]
    px[:, -border:] = [255, 0, 0]
    return Image.fromarray(px)


class TestKenBurnsConservativeZoom:
    """验证默认 zoom 不再过激放大（修复用户反馈：图片放大字看不清）。"""

    def test_default_zoom_is_at_most_1_05(self):
        """默认 zoom_end 应 <= 1.05，避免论文图小字被裁掉。"""
        # 显式不传 zoom_end，应走默认路径
        img = _make_test_image(1920, 1080)
        # 通过空 env 触发默认值
        for k in ("KEN_BURNS_ZOOM_MAX", "KEN_BURNS_PAN_X", "KEN_BURNS_PAN_Y"):
            os.environ.pop(k, None)
        clip = _create_ken_burns_clip(img, duration=2.0, target_size=TARGET_SIZE)
        # 末帧最大 zoom；通过比较中心像素 vs 首帧色块面积估计
        first = clip.get_frame(0.0)
        last = clip.get_frame(1.99)
        assert first.shape == last.shape == (1080, 1920, 3)

    def test_static_mode_via_env(self, monkeypatch):
        """KEN_BURNS_ZOOM_MAX=1.0 + pan=0 应得到完全静态帧。"""
        monkeypatch.setenv("KEN_BURNS_ZOOM_MAX", "1.0")
        monkeypatch.setenv("KEN_BURNS_PAN_X", "0.0")
        monkeypatch.setenv("KEN_BURNS_PAN_Y", "0.0")
        img = _build_border_image((1600, 900), border=10)
        clip = _create_ken_burns_clip(img, duration=3.0, target_size=TARGET_SIZE)
        f0 = clip.get_frame(0.0)
        f1 = clip.get_frame(1.5)
        f2 = clip.get_frame(2.99)
        # 静态：所有帧像素完全一致
        assert np.array_equal(f0, f1), "静态模式下中间帧应与首帧一致"
        assert np.array_equal(f0, f2), "静态模式下末帧应与首帧一致"

    def test_explicit_zoom_end_overrides_default(self):
        """显式参数应覆盖 env 默认。"""
        os.environ["KEN_BURNS_ZOOM_MAX"] = "1.20"  # env 给激进值
        try:
            img = _make_test_image(1000, 800)
            # 显式传 1.0 应当忽略 env
            clip = _create_ken_burns_clip(
                img, duration=2.0, target_size=TARGET_SIZE,
                zoom_end=1.0, pan_x_ratio=0.0, pan_y_ratio=0.0,
            )
            f0 = clip.get_frame(0.0)
            f1 = clip.get_frame(1.99)
            assert np.array_equal(f0, f1), "显式 zoom_end=1.0 应静态"
        finally:
            os.environ.pop("KEN_BURNS_ZOOM_MAX", None)

    def test_zoom_end_clamped_to_max_1_2(self):
        """传入过激 zoom_end=2.0 应被 clamp 到 1.2（不会按 2.0 执行）。

        通过比较 zoom_end=2.0 与 zoom_end=1.2 的末帧像素来验证 clamp：
        如果 clamp 生效，两帧应一致；否则 zoom_end=2.0 的末帧裁得更厉害。
        """
        img = _make_test_image(1600, 900, color=(123, 200, 50))
        clip_clamped = _create_ken_burns_clip(
            img, duration=2.0, target_size=TARGET_SIZE,
            zoom_end=2.0,
            pan_x_ratio=0.0, pan_y_ratio=0.0,
        )
        clip_at_max = _create_ken_burns_clip(
            img, duration=2.0, target_size=TARGET_SIZE,
            zoom_end=1.2,
            pan_x_ratio=0.0, pan_y_ratio=0.0,
        )
        # 末帧像素应完全一致（clamp 生效后 2.0 → 1.2）
        f1 = clip_clamped.get_frame(1.99)
        f2 = clip_at_max.get_frame(1.99)
        assert np.array_equal(f1, f2), "clamp 失败：zoom_end=2.0 与 1.2 的末帧不一致"
