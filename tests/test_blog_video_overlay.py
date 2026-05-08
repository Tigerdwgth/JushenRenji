"""blog_video_overlay 单元测试 (全程 mock subprocess + ffprobe, 不真跑 ffmpeg)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from src.blog_video_overlay import (
    DEFAULT_XFADE_DUR,
    METHOD_SCENE_IDX,
    MIN_PLAYBACK_SPEED,
    RESULTS_SCENE_IDX,
    SOFT_MAX_VIDEO_S,
    _build_alignment_plan,
    _build_scale_filter,
    align_video_to_tts,
    assign_blog_clips_to_scenes,
    concat_with_xfade,
)


# ============================================================
# _build_alignment_plan: 三档策略决策 (纯函数, 无 subprocess)
# ============================================================

def test_plan_trim_when_video_longer_than_target():
    strategy, K = _build_alignment_plan(
        video_dur=30.0, target_dur=10.0, min_speed=MIN_PLAYBACK_SPEED
    )
    assert strategy == "trim"


def test_plan_setpts_when_gap_small_and_video_long_enough():
    """gap=0.5s, video=12s, K=12.5/12=1.04, 在 1/0.7=1.43 内 → setpts."""
    strategy, K = _build_alignment_plan(
        video_dur=12.0, target_dur=12.5, min_speed=0.7
    )
    assert strategy == "setpts"
    assert abs(K - 12.5 / 12.0) < 1e-6


def test_plan_loop_when_gap_too_large():
    """gap=10s 太大, 即使 video 长也走 loop."""
    strategy, K = _build_alignment_plan(
        video_dur=5.0, target_dur=15.0, min_speed=0.7
    )
    assert strategy == "loop"


def test_plan_loop_when_video_too_short():
    """video < 3s 即使 gap 小也 loop (减速会卡顿)."""
    strategy, K = _build_alignment_plan(
        video_dur=2.0, target_dur=2.5, min_speed=0.7
    )
    assert strategy == "loop"


def test_plan_loop_when_K_exceeds_min_speed_limit():
    """K=2.0 超出 1/0.7=1.43 上限, 切 loop."""
    strategy, K = _build_alignment_plan(
        video_dur=5.0, target_dur=10.0, min_speed=0.7
    )
    # gap=5s 也 >= 1s 直接 loop, 这里同时验证多个分支
    assert strategy == "loop"


# ============================================================
# _build_scale_filter
# ============================================================

def test_scale_filter_skipped_when_resolution_matches():
    """1280x720 完全匹配, 不加 scale."""
    f = _build_scale_filter(1280, 720)
    assert "scale=" not in f
    assert "format=yuv420p" in f


def test_scale_filter_uses_lanczos_when_mismatch():
    """1920x1080 不匹配, 加 lanczos scale."""
    f = _build_scale_filter(1920, 1080)
    assert "scale=" in f
    assert "lanczos" in f
    assert "1280:720" in f


def test_scale_filter_unknown_resolution_falls_back():
    """0x0 (probe 失败) 退回不 scale."""
    f = _build_scale_filter(0, 0)
    assert "scale=" not in f


# ============================================================
# align_video_to_tts: 三档策略最终命令格式
# ============================================================

def _make_runner_capture():
    """返回 (mock_runner, captured_cmds): 截获所有 ffmpeg 调用命令."""
    captured = []
    def runner(cmd, **kw):
        captured.append(list(cmd))
        return MagicMock(returncode=0)
    return runner, captured


def test_align_short_audio_triggers_trim(monkeypatch, tmp_path):
    """video=30s, tts=10s → trim. 命令含 -t 10.000, 不含 stream_loop / setpts."""
    monkeypatch.setattr("src.blog_video_overlay._probe_duration",
                        lambda p: 30.0 if p.endswith(".mp4") else 10.0)
    monkeypatch.setattr("src.blog_video_overlay._probe_resolution",
                        lambda p: (1280, 720))
    runner, captured = _make_runner_capture()

    out = align_video_to_tts(
        str(tmp_path / "v.mp4"),
        str(tmp_path / "tts.mp3"),
        str(tmp_path / "out.mp4"),
        _runner=runner,
    )
    assert out.endswith("out.mp4")
    cmd = " ".join(captured[0])
    assert "-t 10.000" in cmd, cmd
    assert "stream_loop" not in cmd
    assert "setpts" not in cmd


def test_align_long_audio_triggers_loop(monkeypatch, tmp_path):
    """video=5s, tts=15s → loop. 命令含 -stream_loop -1, 不含 setpts."""
    monkeypatch.setattr("src.blog_video_overlay._probe_duration",
                        lambda p: 5.0 if p.endswith(".mp4") else 15.0)
    monkeypatch.setattr("src.blog_video_overlay._probe_resolution",
                        lambda p: (1280, 720))
    runner, captured = _make_runner_capture()

    align_video_to_tts(
        str(tmp_path / "v.mp4"),
        str(tmp_path / "tts.mp3"),
        str(tmp_path / "out.mp4"),
        _runner=runner,
    )
    cmd = captured[0]
    cmd_str = " ".join(cmd)
    assert "-stream_loop" in cmd
    assert "-1" in cmd
    assert "setpts" not in cmd_str
    assert "-t 15.000" in cmd_str


def test_align_close_audio_triggers_setpts(monkeypatch, tmp_path):
    """video=12s, tts=12.5s → setpts K=1.0417 (gap<1, video>=3, K<=1.43)."""
    monkeypatch.setattr("src.blog_video_overlay._probe_duration",
                        lambda p: 12.0 if p.endswith(".mp4") else 12.5)
    monkeypatch.setattr("src.blog_video_overlay._probe_resolution",
                        lambda p: (1280, 720))
    runner, captured = _make_runner_capture()

    align_video_to_tts(
        str(tmp_path / "v.mp4"),
        str(tmp_path / "tts.mp3"),
        str(tmp_path / "out.mp4"),
        _runner=runner,
    )
    cmd_str = " ".join(captured[0])
    assert "setpts=" in cmd_str
    # K = 12.5/12 = 1.04167, 4 位精度
    assert "1.0417" in cmd_str
    assert "stream_loop" not in cmd_str


def test_align_soft_max_caps_long_video(monkeypatch, tmp_path, caplog):
    """video=600s, tts=300s, soft_max=120 → 截到 min(300, 120)=120s + warning."""
    monkeypatch.setattr("src.blog_video_overlay._probe_duration",
                        lambda p: 600.0 if p.endswith(".mp4") else 300.0)
    monkeypatch.setattr("src.blog_video_overlay._probe_resolution",
                        lambda p: (1280, 720))
    runner, captured = _make_runner_capture()

    with caplog.at_level(logging.WARNING):
        align_video_to_tts(
            str(tmp_path / "v.mp4"),
            str(tmp_path / "tts.mp3"),
            str(tmp_path / "out.mp4"),
            soft_max_s=120.0,
            _runner=runner,
        )
    cmd_str = " ".join(captured[0])
    # target_dur = min(audio=300, soft_max=120) = 120
    assert "-t 120.000" in cmd_str
    assert any("soft_max" in r.message for r in caplog.records), \
        f"soft_max warning 缺失: {[r.message for r in caplog.records]}"


def test_align_invalid_audio_dur_raises(monkeypatch, tmp_path):
    """TTS 时长 0 → ValueError."""
    monkeypatch.setattr("src.blog_video_overlay._probe_duration", lambda p: 0.0)
    monkeypatch.setattr("src.blog_video_overlay._probe_resolution",
                        lambda p: (1280, 720))
    runner, _ = _make_runner_capture()

    with pytest.raises(ValueError, match="TTS 音频时长"):
        align_video_to_tts(
            str(tmp_path / "v.mp4"),
            str(tmp_path / "tts.mp3"),
            str(tmp_path / "out.mp4"),
            _runner=runner,
        )


def test_align_replaces_audio_with_tts(monkeypatch, tmp_path):
    """命令必须 -map 0:v:0 + -map 1:a:0 (TTS 在 input1, mute 视频 audio)."""
    monkeypatch.setattr("src.blog_video_overlay._probe_duration",
                        lambda p: 10.0 if p.endswith(".mp4") else 8.0)
    monkeypatch.setattr("src.blog_video_overlay._probe_resolution",
                        lambda p: (1280, 720))
    runner, captured = _make_runner_capture()

    align_video_to_tts(
        str(tmp_path / "v.mp4"),
        str(tmp_path / "tts.mp3"),
        str(tmp_path / "out.mp4"),
        _runner=runner,
    )
    cmd = captured[0]
    assert "-map" in cmd
    map_indices = [i for i, x in enumerate(cmd) if x == "-map"]
    map_args = [cmd[i + 1] for i in map_indices]
    assert "0:v:0" in map_args, f"应 map 视频流 from input 0: {map_args}"
    assert "1:a:0" in map_args, f"应 map TTS audio from input 1: {map_args}"


def test_align_preserves_resolution_when_matched(monkeypatch, tmp_path):
    """1280x720 时不应加 scale filter (保留原画质)."""
    monkeypatch.setattr("src.blog_video_overlay._probe_duration",
                        lambda p: 10.0 if p.endswith(".mp4") else 5.0)
    monkeypatch.setattr("src.blog_video_overlay._probe_resolution",
                        lambda p: (1280, 720))
    runner, captured = _make_runner_capture()

    align_video_to_tts(
        str(tmp_path / "v.mp4"),
        str(tmp_path / "tts.mp3"),
        str(tmp_path / "out.mp4"),
        _runner=runner,
    )
    cmd_str = " ".join(captured[0])
    assert "scale=1280:720" not in cmd_str  # 不该 scale
    assert "format=yuv420p" in cmd_str


def test_align_uses_lanczos_when_mismatch(monkeypatch, tmp_path):
    """1920x1080 → scale lanczos 到 1280x720."""
    monkeypatch.setattr("src.blog_video_overlay._probe_duration",
                        lambda p: 10.0 if p.endswith(".mp4") else 5.0)
    monkeypatch.setattr("src.blog_video_overlay._probe_resolution",
                        lambda p: (1920, 1080))
    runner, captured = _make_runner_capture()

    align_video_to_tts(
        str(tmp_path / "v.mp4"),
        str(tmp_path / "tts.mp3"),
        str(tmp_path / "out.mp4"),
        _runner=runner,
    )
    cmd_str = " ".join(captured[0])
    assert "scale=1280:720" in cmd_str
    assert "lanczos" in cmd_str


# ============================================================
# assign_blog_clips_to_scenes
# ============================================================

def test_assign_zero_clips_returns_empty():
    assert assign_blog_clips_to_scenes([]) == {}


def test_assign_one_clip_to_method():
    out = assign_blog_clips_to_scenes([{"path": "a.mp4", "duration": 10.0}])
    assert out == {METHOD_SCENE_IDX: "a.mp4"}


def test_assign_two_clips_to_method_and_results():
    out = assign_blog_clips_to_scenes([
        {"path": "a.mp4", "duration": 10.0},
        {"path": "b.mp4", "duration": 8.0},
    ])
    assert out == {METHOD_SCENE_IDX: "a.mp4", RESULTS_SCENE_IDX: "b.mp4"}


def test_assign_three_clips_drops_extra(caplog):
    """3 clip 仍按 method/results 分配, 第 3 个 logger.info 丢弃."""
    with caplog.at_level(logging.INFO):
        out = assign_blog_clips_to_scenes([
            {"path": "a.mp4"}, {"path": "b.mp4"}, {"path": "c.mp4"},
        ])
    assert out == {METHOD_SCENE_IDX: "a.mp4", RESULTS_SCENE_IDX: "b.mp4"}
    assert any("丢弃" in r.message for r in caplog.records)


# ============================================================
# concat_with_xfade
# ============================================================

def test_concat_single_clip_uses_copy_codec(tmp_path):
    """单 clip 直接 -c copy, 不走 filter_complex."""
    runner_calls = []
    def runner(cmd, **kw):
        runner_calls.append(list(cmd))
        return MagicMock()
    out = concat_with_xfade(
        ["clip0.mp4"],
        str(tmp_path / "out.mp4"),
        _runner=runner,
        _probe=lambda p: 10.0,
    )
    assert out.endswith("out.mp4")
    cmd = runner_calls[0]
    assert "-c" in cmd and "copy" in cmd
    assert "-filter_complex" not in cmd


def test_concat_two_clips_xfade_offset():
    """2 clip durations [10, 8] xfade 0.5s → offset = 10-0.5 = 9.5."""
    runner_calls = []
    def runner(cmd, **kw):
        runner_calls.append(list(cmd))
        return MagicMock()
    concat_with_xfade(
        ["a.mp4", "b.mp4"],
        "out.mp4",
        xfade_dur=0.5,
        _runner=runner,
        _probe=lambda p: {"a.mp4": 10.0, "b.mp4": 8.0}[p],
    )
    cmd = runner_calls[0]
    fc_idx = cmd.index("-filter_complex")
    filter_str = cmd[fc_idx + 1]
    assert "xfade=transition=fade:duration=0.5:offset=9.500" in filter_str
    assert "acrossfade=d=0.5" in filter_str
    # 输出 map 应是最后的 v1 / a1 (1 个 transition 后的标签)
    assert "[v1]" in " ".join(cmd) and "[a1]" in " ".join(cmd)


def test_concat_three_clips_cumulative_offsets():
    """3 clip durations [5, 7, 4] xfade 0.5 → offsets [4.5, 11.0]."""
    runner_calls = []
    def runner(cmd, **kw):
        runner_calls.append(list(cmd))
        return MagicMock()
    durs = {"a.mp4": 5.0, "b.mp4": 7.0, "c.mp4": 4.0}
    concat_with_xfade(
        ["a.mp4", "b.mp4", "c.mp4"],
        "out.mp4",
        xfade_dur=0.5,
        _runner=runner,
        _probe=lambda p: durs[p],
    )
    cmd = runner_calls[0]
    filter_str = cmd[cmd.index("-filter_complex") + 1]
    # offset 1: cum_after_clip0 - 0.5 = 5 - 0.5 = 4.5
    # offset 2: cum_after_xfade1 - 0.5 = (5 + 7 - 0.5) - 0.5 = 11.0
    assert "offset=4.500" in filter_str
    assert "offset=11.000" in filter_str
    # 应有 2 个 xfade + 2 个 acrossfade
    assert filter_str.count("xfade=") == 2
    assert filter_str.count("acrossfade=") == 2
    # 最终输出 map 应是 v2/a2
    assert "[v2]" in " ".join(cmd) and "[a2]" in " ".join(cmd)


def test_concat_empty_list_raises():
    with pytest.raises(ValueError, match="为空"):
        concat_with_xfade([], "out.mp4", _runner=MagicMock(), _probe=lambda p: 0.0)


def test_concat_zero_duration_raises():
    """clip 时长 0 (probe 失败) → ValueError."""
    with pytest.raises(ValueError, match="时长 0"):
        concat_with_xfade(
            ["a.mp4", "b.mp4"], "out.mp4",
            _runner=MagicMock(), _probe=lambda p: 0.0,
        )
