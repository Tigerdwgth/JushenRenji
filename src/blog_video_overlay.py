"""blog 视频与 TTS 解说对齐 + scene 间 xfade 转场.

为 manim 的 method/results scene 提供"用 blog 视频替代 manim 渲染"的能力:
- 完整保留 blog 原画 (libx264 CRF 18 视觉无损)
- 替换原音轨为中文 TTS 解说 (mute 原 audio)
- 视频时长与 TTS 时长智能对齐 (trim / setpts 减速 / loop)
- scene 间 0.5s xfade 转场

不破坏 paper-link 路径: 仅当 ./cache/blog_meta.json 存在 + 含 clip_meta 时才被调用.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---- 常量 ----
SOFT_MAX_VIDEO_S = 120.0  # 单 scene blog 视频长度软上限 (防 10 分钟产品发布会爆 scene)
MIN_PLAYBACK_SPEED = 0.7  # setpts 减速下限, 低于此会画面卡顿
DEFAULT_XFADE_DUR = 0.5
LIBX264_CRF = 18  # 视觉无损
LIBX264_PRESET = "veryfast"
TARGET_W, TARGET_H = 1280, 720
TARGET_FPS = 30
METHOD_SCENE_IDX = 2
RESULTS_SCENE_IDX = 3


# ---- ffprobe 工具 ----

def _probe_duration(path: str) -> float:
    """ffprobe 读 file 时长 (秒). 失败返回 0.0."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return float(out.stdout.strip() or 0.0)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError) as e:
        logger.warning("[blog-overlay] ffprobe duration %s 失败: %s", path, e)
        return 0.0


def _probe_resolution(path: str) -> Tuple[int, int]:
    """返回 video (width, height); 失败返回 (0, 0)."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0", path,
            ],
            capture_output=True, text=True, timeout=15, check=True,
        )
        wh = (out.stdout.strip() or "0,0").split(",")
        return int(wh[0] or 0), int(wh[1] or 0)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError, IndexError) as e:
        logger.warning("[blog-overlay] ffprobe resolution %s 失败: %s", path, e)
        return (0, 0)


# ---- 视频对齐策略 ----

def _build_alignment_plan(
    video_dur: float, target_dur: float, min_speed: float,
) -> Tuple[str, float]:
    """决定对齐策略 (trim / setpts / loop) + 计算减速系数 K.

    返回 (strategy, K). K 仅在 setpts 策略下有意义.
    """
    if video_dur >= target_dur:
        return "trim", 1.0
    gap = target_dur - video_dur
    K = target_dur / max(video_dur, 0.01)
    # gap 不大 (< 1s) 且视频本身不太短 (>=3s) 且减速幅度可接受时, 用 setpts 更平滑
    if gap < 1.0 and video_dur >= 3.0 and K <= 1.0 / min_speed:
        return "setpts", K
    return "loop", K


def _build_scale_filter(src_w: int, src_h: int) -> str:
    """仅在分辨率不等于目标 (1280x720) 时加 scale (lanczos), 否则只 format yuv420p."""
    if (src_w, src_h) == (TARGET_W, TARGET_H) or src_w <= 0 or src_h <= 0:
        return "format=yuv420p"
    return (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )


# ---- 主接口: 单 scene 视频对齐 ----

def align_video_to_tts(
    video_path: str,
    tts_audio_path: str,
    out_path: str,
    *,
    soft_max_s: float = SOFT_MAX_VIDEO_S,
    min_speed: float = MIN_PLAYBACK_SPEED,
    _runner=subprocess.run,
) -> str:
    """把 blog video 与 TTS 解说对齐, 输出 mp4 (替换原音轨为 TTS).

    三档对齐策略:
      - 视频 >= TTS: trim 到 TTS 时长
      - 视频 <  TTS:
        gap < 1s 且 video >= 3s 且 K <= 1/min_speed: setpts 减速 (gap 平滑)
        否则: stream_loop 循环填满 TTS 时长

    soft_max_s 软上限: 视频比 soft_max_s 长时, 强制截到 min(TTS_dur, soft_max_s).

    画面: libx264 CRF 18 preset veryfast (视觉无损); 分辨率不等于 1280x720 时 lanczos scale.
    音轨: -map TTS:a -c:a aac (完全 mute 原视频音轨).

    _runner 参数仅供测试 mock subprocess.run 用.
    返回 out_path.
    """
    audio_dur = _probe_duration(tts_audio_path)
    video_dur_raw = _probe_duration(video_path)
    if audio_dur <= 0:
        raise ValueError(f"TTS 音频时长 0: {tts_audio_path}")
    if video_dur_raw <= 0:
        raise ValueError(f"video 时长 0: {video_path}")

    # soft_max 保护
    if video_dur_raw > soft_max_s:
        target_dur = min(audio_dur, soft_max_s)
        logger.warning(
            "[blog-overlay] %s video_dur=%.1fs > soft_max=%.0fs, 截到 target=%.1fs",
            os.path.basename(video_path), video_dur_raw, soft_max_s, target_dur,
        )
        # 强制 trim: 把 video_dur 视为 target_dur 让 plan 落在 trim 分支
        video_dur_for_plan = target_dur
    else:
        target_dur = audio_dur
        video_dur_for_plan = video_dur_raw

    src_w, src_h = _probe_resolution(video_path)
    strategy, K = _build_alignment_plan(video_dur_for_plan, target_dur, min_speed)
    scale_filter = _build_scale_filter(src_w, src_h)

    if strategy == "setpts":
        vfilter = f"setpts={K:.4f}*PTS,{scale_filter}"
    else:
        vfilter = scale_filter

    pre_input: List[str] = []
    if strategy == "loop":
        pre_input = ["-stream_loop", "-1"]

    logger.info(
        "[blog-overlay] %s strategy=%s video_dur=%.1fs tts_dur=%.1fs target=%.1fs K=%.2f src=%dx%d",
        os.path.basename(video_path), strategy, video_dur_raw, audio_dur, target_dur, K, src_w, src_h,
    )

    cmd = ["ffmpeg", "-v", "warning", "-y"]
    cmd.extend(pre_input)
    cmd.extend(["-i", video_path, "-i", tts_audio_path])
    cmd.extend(["-t", f"{target_dur:.3f}"])
    cmd.extend(["-vf", vfilter])
    cmd.extend([
        "-r", str(TARGET_FPS),
        "-c:v", "libx264", "-preset", LIBX264_PRESET, "-crf", str(LIBX264_CRF),
        "-pix_fmt", "yuv420p",
        "-map", "0:v:0", "-map", "1:a:0",  # video from input 0, audio from TTS (input 1)
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        out_path,
    ])
    logger.debug("[blog-overlay] ffmpeg cmd: %s", " ".join(cmd))
    _runner(cmd, check=True)
    return out_path


# ---- scene 分配 ----

def _locate_scene_idx(scene_defs, scene_name: str, section: str):
    """在 scene_defs 中按真实位置定位某 scene 的 idx.

    优先按 scene_name 精确匹配 (MethodScene / ResultsScene),
    再退而按 section 匹配该 section 的第一个 scene.
    找不到返回 None.
    """
    for j, sdef in enumerate(scene_defs):
        if sdef.get("scene_name") == scene_name:
            return j
    for j, sdef in enumerate(scene_defs):
        if sdef.get("section") == section:
            return j
    return None


def assign_blog_clips_to_scenes(
    clip_metas: List[Dict],
    total_scenes: int = 4,
    scene_defs: List[Dict] = None,
) -> Dict[int, str]:
    """把 N 个 blog clip 分配到 method 和 results scene.

    每 scene 至多 1 clip (简化 xfade 复杂度).
      - 0 clip: {} (manim 正常渲染)
      - 1 clip: {method_idx: clip0}
      - 2+ clip: {method_idx: clip0, results_idx: clip1} (多余 clip logger.info 丢弃)

    scene 真实 idx 的确定:
      - 传入 scene_defs 时, 按真实位置定位 MethodScene / ResultsScene 的 idx
        (先按 scene_name, 再按 section), 兼容引言后插入 AnimScene 等导致 idx 漂移的情况;
      - 未传 scene_defs (旧调用点) 时, 回退到固定 idx 2/3 (旧行为, 保证兼容).

    返回 {scene_idx: clip_path}.
    """
    if not clip_metas:
        return {}

    # 确定 method / results 的真实 idx
    method_idx = METHOD_SCENE_IDX
    results_idx = RESULTS_SCENE_IDX
    if scene_defs:
        m = _locate_scene_idx(scene_defs, "MethodScene", "method")
        r = _locate_scene_idx(scene_defs, "ResultsScene", "results")
        if m is not None:
            method_idx = m
        else:
            logger.warning("[blog-overlay] scene_defs 中未找到 MethodScene/method, "
                           "回退固定 idx %d", METHOD_SCENE_IDX)
        if r is not None:
            results_idx = r
        else:
            logger.warning("[blog-overlay] scene_defs 中未找到 ResultsScene/results, "
                           "回退固定 idx %d", RESULTS_SCENE_IDX)

    out: Dict[int, str] = {}
    if len(clip_metas) >= 1:
        out[method_idx] = clip_metas[0]["path"]
    if len(clip_metas) >= 2:
        out[results_idx] = clip_metas[1]["path"]
    if len(clip_metas) > 2:
        logger.info(
            "[blog-overlay] %d clip 超过 method+results 容量, 丢弃 %d 个",
            len(clip_metas), len(clip_metas) - 2,
        )
    logger.info("[blog-overlay] scene_assignments=%s (method_idx=%d, results_idx=%d)",
                out, method_idx, results_idx)
    return out


# ---- xfade 转场拼接 ----

def concat_with_xfade(
    clip_paths: List[str],
    out_path: str,
    *,
    xfade_dur: float = DEFAULT_XFADE_DUR,
    _runner=subprocess.run,
    _probe=_probe_duration,
) -> str:
    """用 ffmpeg xfade=transition=fade 串接多 clip, 音频用 acrossfade.

    每相邻两 clip 间 1 个 xfade transition, offset = 累计时长 - xfade_dur.
    单 clip 直接 copy 不转场.

    _runner / _probe 参数仅供测试 mock 用. 返回 out_path.
    """
    if not clip_paths:
        raise ValueError("clip_paths 为空")
    if len(clip_paths) == 1:
        _runner(
            [
                "ffmpeg", "-v", "warning", "-y", "-i", clip_paths[0],
                "-c", "copy", "-movflags", "+faststart", out_path,
            ],
            check=True,
        )
        return out_path

    durations = [_probe(p) for p in clip_paths]
    if any(d <= 0 for d in durations):
        raise ValueError(f"某 clip 时长 0: {list(zip(clip_paths, durations))}")

    cmd = ["ffmpeg", "-v", "warning", "-y"]
    for p in clip_paths:
        cmd.extend(["-i", p])

    filter_parts: List[str] = []
    cum = durations[0]
    cur_v = "0:v"
    cur_a = "0:a"
    for i in range(1, len(clip_paths)):
        offset = cum - xfade_dur
        filter_parts.append(
            f"[{cur_v}][{i}:v]xfade=transition=fade:duration={xfade_dur}:offset={offset:.3f}[v{i}]"
        )
        filter_parts.append(
            f"[{cur_a}][{i}:a]acrossfade=d={xfade_dur}[a{i}]"
        )
        cur_v = f"v{i}"
        cur_a = f"a{i}"
        cum += durations[i] - xfade_dur

    filter_str = ";".join(filter_parts)
    cmd.extend([
        "-filter_complex", filter_str,
        "-map", f"[{cur_v}]", "-map", f"[{cur_a}]",
        "-c:v", "libx264", "-preset", LIBX264_PRESET, "-crf", str(LIBX264_CRF),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        out_path,
    ])
    logger.info(
        "[blog-overlay] xfade concat n=%d total≈%.1fs out=%s",
        len(clip_paths), cum, out_path,
    )
    logger.debug("[blog-overlay] filter_complex: %s", filter_str)
    _runner(cmd, check=True)
    return out_path
