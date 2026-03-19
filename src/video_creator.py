import dashscope
from dashscope.audio.tts_v2 import *
from moviepy import *
from moviepy.audio.AudioClip import AudioArrayClip
from PIL import Image
import numpy as np
import os
import re
import io
import base64
import logging
import json
from config import DASHSCOPE_API_KEY, FONT_PATH
import nltk
nltk.download('punkt_tab')
from nltk.tokenize import sent_tokenize

# 设置DashScope API密钥
try:
    dashscope.api_key = DASHSCOPE_API_KEY
except Exception:
    # 如果无法从config导入，使用环境变量
    pass

# 导入音频处理工具模块
try:
    from src.utils.audio_helpers import (
        safe_tts_save,
        safe_audio_clip_loader,
        safe_concatenate_audio,
        create_silent_audio,
        AudioResourceManager,
        audio_logger
    )
except ImportError:
    # 如果src不在路径中，尝试直接导入
    try:
        from utils.audio_helpers import (
            safe_tts_save,
            safe_audio_clip_loader,
            safe_concatenate_audio,
            create_silent_audio,
            AudioResourceManager,
            audio_logger
        )
    except ImportError:
        # 如果都失败，使用本地实现
        audio_logger = logging.getLogger('audio_processing')
        audio_logger.setLevel(logging.DEBUG)

# 配置日志记录
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)

_PUNKT_READY = False


def test_audio_generation(text, idx):
    """测试音频生成是否正常"""
    logging.info(f"测试音频生成 {idx}: {text[:30]}...")

    ss = SpeechSynthesizer(model="cosyvoice-v1", voice="longxiaochun")
    data = ss.call(text=text)

    if not data:
        logging.error(f"TTS返回空数据 idx={idx}")
        return False

    logging.info(f"TTS返回数据大小: {len(data)} 字节")

    # 保存并测试
    path = f'./cache/test_audio_{idx}.wav'
    with open(path, 'wb') as f:
        f.write(data)

    clip = AudioFileClip(path)
    logging.info(f"音频文件时长: {clip.duration:.2f}秒")
    clip.close()

    return True


def _ensure_punkt_tokenizer():
    global _PUNKT_READY
    if _PUNKT_READY:
        return
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt', quiet=True)
    _PUNKT_READY = True


def _split_into_sentences(text, max_chars=30):
    """按句子标点符号分割文本，返回完整句子列表
    如果单个句子超过max_chars，会进一步按分号/逗号/冒号分割
    """
    if not text:
        return []
    _ensure_punkt_tokenizer()
    sentences = []
    try:
        sentences = sent_tokenize(text)
    except Exception as exc:
        logging.warning("NLTK sent_tokenize 失败，回退正则: %s", exc)
        sentences = []
    if not sentences:
        sentences = re.split(r'[。？，,！.!?\n]+', text)

    result = []
    for seg in sentences:
        seg = seg.strip()
        if not seg:
            continue

        # 如果句子太长，按分号、逗号、冒号进一步分割
        if len(seg) > max_chars:
            sub_parts = re.split(r'[；;，,：:]', seg)
            for sub in sub_parts:
                sub = sub.strip()
                if sub:
                    result.append(sub)
        else:
            result.append(seg)

    return result


def _create_ken_burns_clip(img, duration, target_size=(1920, 1080)):
    """为静态图片创建 Ken Burns 效果（缓慢 zoom-in + 平移），增加动态感。

    图片先完全适配画面（contain，无溢出），然后缓慢放大到 1.08x，
    确保初始帧图片内容完全可见，避免重要内容（坐标轴、图例等）被裁掉。

    Args:
        img: PIL.Image 对象
        duration: 显示时长（秒）
        target_size: 输出分辨率 (width, height)

    Returns:
        moviepy VideoClip 对象
    """
    tw, th = target_size

    # contain：图片完全适配画面，加 5% 内边距保证边缘内容不贴边
    padding_factor = 0.95
    scale_factor = min(tw / img.width, th / img.height) * padding_factor
    new_w = int(img.width * scale_factor)
    new_h = int(img.height * scale_factor)
    img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 放到深蓝底色画布上居中
    canvas = Image.new("RGB", (tw, th), (15, 20, 40))
    paste_x = (tw - new_w) // 2
    paste_y = (th - new_h) // 2
    canvas.paste(img_resized, (paste_x, paste_y))
    base_pil = canvas  # 保留 PIL 对象，避免每帧重复转换

    # Ken Burns 参数：从 1.0x 缓慢 zoom-in 到 zoom_end
    zoom_end = 1.08
    # 平移方向：向图片中心偏右下缓慢移动
    pan_x_ratio = 0.02  # 水平平移比例（相对于画面宽度）
    pan_y_ratio = 0.01  # 垂直平移比例（相对于画面高度）

    def make_frame(t):
        progress = t / max(duration, 0.01)
        # 缓和曲线：ease-in-out 让动画更自然
        smooth = progress * progress * (3.0 - 2.0 * progress)

        zoom = 1.0 + (zoom_end - 1.0) * smooth
        # 缩放后的裁切区域大小
        crop_w = tw / zoom
        crop_h = th / zoom

        # 中心点随时间缓慢平移
        center_x = tw / 2.0 + tw * pan_x_ratio * smooth
        center_y = th / 2.0 + th * pan_y_ratio * smooth

        # 裁切区域的左上角坐标，clamp 到画布边界
        x1 = max(0.0, min(center_x - crop_w / 2.0, tw - crop_w))
        y1 = max(0.0, min(center_y - crop_h / 2.0, th - crop_h))
        x2 = x1 + crop_w
        y2 = y1 + crop_h

        # 从预存 PIL 对象裁切并缩放到目标尺寸
        crop_img = base_pil.crop((int(x1), int(y1), int(x2), int(y2)))
        crop_img = crop_img.resize((tw, th), Image.Resampling.LANCZOS)
        return np.array(crop_img)

    return VideoClip(make_frame, duration=duration)


def _wrap_text(text, max_chars=20):
    """在每max_chars个字符后添加换行符，防止字幕溢出"""
    if not text or len(text) <= max_chars:
        return text
    result = []
    for i in range(0, len(text), max_chars):
        result.append(text[i:i+max_chars])
    return '\n'.join(result)


def trim_segments_to_duration(segments: list, target_duration: float,
                               overflow_ratio: float = 1.1) -> list:
    """TTS 后兜底裁剪：从尾部移除整段直到总时长在弹性范围内。

    Args:
        segments: [{"type": "expl"|"summary", "duration": float, "image_idx": int}, ...]
        target_duration: 目标时长（秒）
        overflow_ratio: 允许的弹性比例

    Returns:
        裁剪后的 segments 列表
    """
    max_duration = target_duration * overflow_ratio
    total = sum(s["duration"] for s in segments)

    if total <= max_duration:
        return segments[:]

    logging.info(f"TTS 总时长 {total:.1f}s 超过目标 {max_duration:.1f}s，开始裁剪")

    result = segments[:]

    # 第一轮：从尾部移除 expl 类型
    while sum(s["duration"] for s in result) > max_duration:
        removed = False
        for i in range(len(result) - 1, -1, -1):
            if result[i]["type"] == "expl":
                removed_seg = result.pop(i)
                logging.info(f"移除图片解释段 image_idx={removed_seg['image_idx']}, duration={removed_seg['duration']:.1f}s")
                removed = True
                break
        if not removed:
            break

    # 第二轮：如果仍超标，从尾部移除 summary 类型
    while sum(s["duration"] for s in result) > max_duration:
        removed = False
        for i in range(len(result) - 1, -1, -1):
            if result[i]["type"] == "summary":
                removed_seg = result.pop(i)
                logging.info(f"移除摘要段 image_idx={removed_seg['image_idx']}, duration={removed_seg['duration']:.1f}s")
                removed = True
                break
        if not removed:
            break

    final_total = sum(s["duration"] for s in result)
    logging.info(f"裁剪后总时长: {final_total:.1f}s")
    return result


class VideoCreator:
    def __init__(self, images, text, video_clips=None, image_explanations=None,
                 target_duration=0, structured_plan=None):
        """images: list of PIL.Image
        text: full summary text
        video_clips: optional list of VideoFileClip (external video materials)
        image_explanations: optional list of dicts (from ImageAgent.explain_images)
        target_duration: 目标视频时长（秒），0 表示不限制
        structured_plan: optional dict (结构化脚本，包含 opening/intro/method/results 各段)
        """
        self.images = images
        self.text = text
        self.video_clips = video_clips or []
        self.image_explanations = image_explanations or []
        self.target_duration = target_duration
        self.structured_plan = structured_plan or {}
        self.texts = []
        self.time = []
        self.texts_starts = []
        self.audioclips = []
        self.video = None
        logging.info("VideoCreator实例已创建")

    def _save_video_script(self, output_filename):
        """保存完整视频脚本到JSON文件"""
        script_data = {
            "title": self.text[:200] if self.text else "",
            "images": []
        }

        for i, img in enumerate(self.images):
            # 图片转base64
            img_buffer = io.BytesIO()
            img.convert("RGB").save(img_buffer, format="JPEG", quality=85)
            img_b64 = base64.b64encode(img_buffer.getvalue()).decode()

            # 获取该图片的解释
            expl_obj = self.image_explanations[i] if i < len(self.image_explanations) else {}

            script_data["images"].append({
                "image_index": i,
                "image_base64": img_b64,
                "transition": expl_obj.get('transition', ''),
                "context": expl_obj.get('context', ''),
                "detailed_explanation": expl_obj.get('detailed_explanation', ''),
                "key_points": expl_obj.get('key_points', []),
                "caption": expl_obj.get('caption', '')
            })

        # 保存到 .json 文件（与视频同名）
        json_path = output_filename.replace(".mp4", "_script.json")
        os.makedirs(os.path.dirname(json_path) or '.', exist_ok=True)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)

        logging.info(f"视频脚本已保存到: {json_path}")
        return json_path

    def _get_chapter_name_for_image(self, image_idx):
        """根据 image_explanations 获取图片的章节显示名称。

        优先使用 figure_role，其次 recommended_section，最后回退到默认名称。

        Args:
            image_idx: 图片索引

        Returns:
            str: 章节显示名称（中文）
        """
        # section -> 中文显示名称映射
        section_display = {
            "opening": "开场引入",
            "intro": "背景介绍",
            "introduction": "背景介绍",
            "method": "核心方法",
            "methods": "核心方法",
            "results": "实验结果",
            "result": "实验结果",
            "experiment": "实验结果",
            "experiments": "实验结果",
            "conclusion": "总结展望",
            "other": "补充说明",
        }

        if image_idx >= len(self.image_explanations):
            return ""
        expl = self.image_explanations[image_idx]
        if not isinstance(expl, dict):
            return ""

        # 优先使用 figure_role（如 "总览图"、"方法架构图"、"实验对比"）
        figure_role = expl.get("figure_role", "")
        if figure_role and isinstance(figure_role, str) and len(figure_role.strip()) > 0:
            role = figure_role.strip()
            # 如果 figure_role 本身就是中文描述性名称，直接使用
            if any('\u4e00' <= ch <= '\u9fff' for ch in role):
                return role
            # 英文 figure_role 尝试映射
            role_lower = role.lower()
            role_mapping = {
                "overview": "总览图",
                "method": "核心方法",
                "architecture": "模型架构",
                "result": "实验结果",
                "comparison": "对比分析",
                "ablation": "消融实验",
                "visualization": "可视化展示",
            }
            for key, display in role_mapping.items():
                if key in role_lower:
                    return display

        # 其次使用 recommended_section
        rec_section = expl.get("recommended_section", "")
        if rec_section and isinstance(rec_section, str):
            sec = rec_section.strip().lower()
            # 处理 "opening/intro" 格式
            if "/" in sec:
                sec = sec.split("/")[0].strip()
            if sec in section_display:
                return section_display[sec]

        return ""

    def _add_chapter_overlay(self, clips_durations):
        """在视频右上角叠加章节标题和底部进度条。

        优先从 image_explanations 的 figure_role/recommended_section 获取章节名称，
        如果不存在则回退到基于图片数量的硬编码分配。

        Args:
            clips_durations: list of (image_index, duration) 每张图片的时长
        """
        if not self.video or not clips_durations:
            return

        n = len(clips_durations)

        # 尝试从 image_explanations 获取真实章节名称
        chapter_names = []
        has_real_names = False
        for idx, (img_idx, _) in enumerate(clips_durations):
            name = self._get_chapter_name_for_image(img_idx)
            if name:
                has_real_names = True
            chapter_names.append(name)

        # 如果没有真实章节名称，回退到硬编码逻辑
        if not has_real_names:
            logging.info("image_explanations 中无 section 信息，回退到硬编码章节名称")
            chapter_names = []
            if n <= 2:
                chapter_names = ["方法讲解"] * n
            elif n <= 4:
                chapter_names = ["背景介绍"] + ["核心方法"] * (n - 2) + ["实验结果"]
            else:
                chapter_names = (
                    ["开场引入"]
                    + ["背景介绍"]
                    + ["核心方法"] * max(1, n - 4)
                    + ["实验结果"]
                    + ["总结展望"]
                )
            chapter_names = chapter_names[:n]
        else:
            # 填充空名称：使用前一个非空名称或默认名称
            last_valid = "方法讲解"
            for i in range(len(chapter_names)):
                if chapter_names[i]:
                    last_valid = chapter_names[i]
                else:
                    chapter_names[i] = last_valid

        overlay_clips = []
        cumulative = 0

        # 先跳过外部视频时长
        for vc in self.video_clips:
            if getattr(vc, 'duration', None):
                cumulative += vc.duration

        total_duration = self.video.duration if self.video.duration else 1

        for idx, (_, dur) in enumerate(clips_durations):
            if idx >= len(chapter_names):
                break
            name = chapter_names[idx]

            # 章节标题（右上角半透明背景）
            try:
                txt = TextClip(
                    text=f"  {name}  ",
                    font_size=28,
                    font=FONT_PATH,
                    color='white',
                    bg_color='rgba(0,0,0,0.5)',
                    size=(None, None),
                    method='label'
                )
                txt = txt.with_start(cumulative).with_duration(dur).with_position((1580, 30))
                overlay_clips.append(txt)
            except Exception:
                pass  # 字幕样式不支持时静默跳过

            # 底部进度条
            try:
                progress_ratio = (cumulative + dur) / total_duration
                bar_width = int(1920 * progress_ratio)
                bar = ColorClip(size=(bar_width, 4), color=(80, 180, 255))
                bar = bar.with_start(cumulative).with_duration(dur).with_position((0, 1076))
                overlay_clips.append(bar)
            except Exception:
                pass

            cumulative += dur

        if overlay_clips:
            self.video = CompositeVideoClip([self.video] + overlay_clips)

    def _make_subtitle_clip(self, text, start, duration):
        """创建带半透明背景的字幕片段。"""
        text = _wrap_text(text)
        # 字幕文字
        tclip = TextClip(
            text=text,
            font_size=42,
            size=(1800, None),
            font=FONT_PATH,
            color='white',
            stroke_color='black',
            stroke_width=2,
            method='caption',
            horizontal_align='center',
        )
        # 半透明黑色背景条（文字高度 + 上下内边距）
        txt_h = tclip.size[1] if tclip.size[1] else 60
        bg_height = txt_h + 20
        bg_clip = ColorClip(
            size=(1920, bg_height),
            color=(0, 0, 0),
        ).with_opacity(0.55).with_duration(duration)

        # 背景定位到底部偏上
        bg_y = 1080 - bg_height - 40
        bg_clip = bg_clip.with_position((0, bg_y))
        # 字幕文字居中于背景之上
        tclip = tclip.with_duration(duration).with_position(('center', bg_y + 10))

        # 组合背景 + 文字
        combined = CompositeVideoClip(
            [bg_clip, tclip],
            size=(1920, 1080),
        ).with_start(start).with_duration(duration)
        return combined

    def videocaption(self, subtitle_entries):
        """Overlay per-sentence subtitles with semi-transparent background.

        subtitle_entries: list of dicts {text: str, start: float, duration: float}
        Each entry is rendered as a separate TextClip. Long text is wrapped for display.
        """
        txt_clips = []
        for entry in subtitle_entries:
            txt = entry.get('text', '')
            start = entry.get('start', 0)
            duration = entry.get('duration', 2)
            if not txt or duration <= 0:
                continue

            # 如果文本过长，先按句子分割
            if len(txt) > 30:
                sentences = _split_into_sentences(txt)
                if len(sentences) > 1:
                    per_sentence_dur = duration / len(sentences)
                    for i, sentence in enumerate(sentences):
                        sentence_start = start + i * per_sentence_dur
                        clip = self._make_subtitle_clip(sentence, sentence_start, per_sentence_dur)
                        txt_clips.append(clip)
                    continue

            clip = self._make_subtitle_clip(txt, start, duration)
            txt_clips.append(clip)

        if txt_clips:
            subtitles = CompositeVideoClip(txt_clips, size=(1920, 1080))
            self.video = CompositeVideoClip([self.video, subtitles])



    def _extract_explanation_text(self, expl_obj):
        """从图片解释对象中提取最佳文本，按优先级尝试多个字段。"""
        if not isinstance(expl_obj, dict):
            return ''
        for field in ('transition', 'context', 'detailed_explanation', 'key_points', 'caption'):
            value = expl_obj.get(field)
            if not value:
                continue
            if isinstance(value, list):
                return '；'.join(str(v) for v in value)
            return str(value)
        return ''

    def _prepare_expl_texts(self):
        """为每张图片提取解释文本列表。"""
        expl_texts = []
        for i in range(len(self.images)):
            try:
                expl_obj = self.image_explanations[i] if i < len(self.image_explanations) else {}
            except Exception:
                expl_obj = {}
            expl_texts.append(self._extract_explanation_text(expl_obj).strip())
        return expl_texts

    def _run_concurrent_tts(self, expl_texts):
        """并发合成所有 TTS 音频，返回 (expl_sentence_files, summary_sentence_files, expl_sentence_map)。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time as _time

        tts_model = "cosyvoice-v1"
        tts_voice = "longxiaochun"
        TTS_MAX_WORKERS = 6

        def _tts_single(text, audio_file, tag):
            try:
                ss = SpeechSynthesizer(model=tts_model, voice=tts_voice)
                result_path = safe_tts_save(ss, text, audio_file, tag)
                if not result_path or not os.path.exists(result_path):
                    return None
                if os.path.getsize(result_path) < 100:
                    return None
                clip = safe_audio_clip_loader(result_path)
                if clip:
                    duration = clip.duration
                    clip.close()
                    return (result_path, text, duration)
                return None
            except Exception as e:
                audio_logger.error(f"TTS worker 失败 [{tag}]: {e}")
                return None

        tts_tasks = []
        expl_sentence_map = {}

        # 收集解释音频任务
        for idx, et in enumerate(expl_texts):
            if not et:
                expl_sentence_map[idx] = []
                continue
            all_sentences = _split_into_sentences(et)
            if not all_sentences:
                all_sentences = [et]
            sentences = [s.strip() for s in all_sentences if s.strip()] or [et.strip()]
            expl_sentence_map[idx] = list(enumerate(sentences))
            for sent_idx, sentence in enumerate(sentences):
                audio_file = f'./cache/expl_{idx}_{sent_idx}.wav'
                tts_tasks.append((sentence, audio_file, f"expl_{idx}_{sent_idx}", "expl", idx, sent_idx))

        # 收集摘要音频任务
        for idx, txt in enumerate(self.texts):
            path = f'./cache/summary{idx}.wav'
            tts_tasks.append((txt, path, f"summary_{idx}", "summary", idx, 0))

        audio_logger.info(f"TTS 并发合成: 共 {len(tts_tasks)} 个任务, 并发数 {TTS_MAX_WORKERS}")
        tts_start_time = _time.time()

        tts_results = {}
        with ThreadPoolExecutor(max_workers=TTS_MAX_WORKERS) as executor:
            future_map = {}
            for (text, audio_file, tag, task_type, idx, sent_idx) in tts_tasks:
                future = executor.submit(_tts_single, text, audio_file, tag)
                future_map[future] = (task_type, idx, sent_idx, text)

            for future in as_completed(future_map):
                task_type, idx, sent_idx, text = future_map[future]
                try:
                    result = future.result()
                    if result:
                        tts_results[(task_type, idx, sent_idx)] = result
                except Exception as e:
                    audio_logger.error(f"TTS 并发异常 [{task_type}_{idx}_{sent_idx}]: {e}")

        tts_elapsed = _time.time() - tts_start_time
        audio_logger.info(f"TTS 并发合成完成: {len(tts_results)}/{len(tts_tasks)} 成功, 耗时 {tts_elapsed:.1f}s")

        # 按原始顺序重组结果
        expl_sentence_files = []
        for idx in range(len(expl_texts)):
            sentence_list = expl_sentence_map.get(idx, [])
            sentence_files = []
            for sent_idx, sentence in sentence_list:
                key = ("expl", idx, sent_idx)
                if key in tts_results:
                    sentence_files.append(tts_results[key])
            expl_sentence_files.append(sentence_files)
            if sentence_files:
                total_dur = sum(f[2] for f in sentence_files)
                audio_logger.info(f"图像 {idx} 解释音频: {len(sentence_files)} 句, 总时长 {total_dur:.2f}s")

        summary_sentence_files = []
        for idx in range(len(self.texts)):
            key = ("summary", idx, 0)
            if key in tts_results:
                summary_sentence_files.append(tts_results[key])
                audio_logger.info(f"摘要音频 {idx} 成功, 时长 {tts_results[key][2]:.2f}s")
            else:
                audio_logger.error(f"摘要音频 {idx} 失败，跳过")

        return expl_sentence_files, summary_sentence_files, expl_sentence_map

    def _build_section_sentence_map(self):
        """从结构化脚本构建 section -> 句子列表 的映射。

        利用 structured_plan 中各 section 的 script 字段，将每个句子
        关联到其所属的 section（opening/intro/method/results）。

        Returns:
            dict: {section_name: [sentence_text, ...]}，如果无结构化脚本则返回空字典
        """
        if not self.structured_plan:
            return {}

        section_order = ["opening", "intro", "method", "results"]
        section_sentence_map = {}

        for section in section_order:
            section_data = self.structured_plan.get(section, {})
            if isinstance(section_data, dict):
                script = section_data.get("script", "")
            elif isinstance(section_data, str):
                script = section_data
            else:
                script = ""
            if script:
                sentences = _split_into_sentences(script)
                section_sentence_map[section] = sentences
            else:
                section_sentence_map[section] = []

        return section_sentence_map

    def _get_image_section(self, image_idx):
        """获取指定图片的 recommended_section，用于语义匹配。

        Args:
            image_idx: 图片索引

        Returns:
            str: section 名称（opening/intro/method/results/other），
                 如果不存在则返回空字符串
        """
        if image_idx >= len(self.image_explanations):
            return ""
        expl = self.image_explanations[image_idx]
        if not isinstance(expl, dict):
            return ""
        return expl.get("recommended_section", "")

    def _semantic_group_sentences(self, summary_sentence_files):
        """基于 section 语义匹配将摘要句子分配到图片。

        核心逻辑：
        1. 从 structured_plan 解析每个 section 包含哪些句子
        2. 根据每张图片的 recommended_section 确定其所属 section
        3. 将同一 section 的句子均匀分配到该 section 的所有图片上

        如果 structured_plan 或 recommended_section 不存在，回退到均分逻辑。

        Args:
            summary_sentence_files: [(path, text, duration), ...] TTS 后的摘要音频列表

        Returns:
            list[list]: groups[i] = 分配给图片 i 的 [(path, text, duration), ...]
        """
        n_images = max(1, len(self.images))
        total_sent = len(summary_sentence_files)
        groups = [[] for _ in range(n_images)]

        if total_sent == 0:
            return groups

        # 检查是否有足够的语义信息进行匹配
        section_sentence_map = self._build_section_sentence_map()
        has_sections = bool(section_sentence_map) and any(
            len(sents) > 0 for sents in section_sentence_map.values()
        )
        has_image_sections = any(
            self._get_image_section(i) for i in range(n_images)
        )

        # 如果缺少语义信息，回退到均分逻辑
        if not has_sections or not has_image_sections:
            logging.info("语义匹配信息不足，回退到均分逻辑")
            return self._fallback_even_group(summary_sentence_files, n_images)

        # --- 语义匹配逻辑 ---
        logging.info("使用基于 section 的语义匹配分配摘要句子到图片")

        # 步骤1：为每张图片确定所属 section
        # section -> [image_idx, ...]
        section_images = {}
        unmatched_images = []
        for i in range(n_images):
            sec = self._get_image_section(i)
            # 标准化 section 名称（"opening/intro" 映射到 "opening" 或 "intro"）
            sec_normalized = self._normalize_section(sec)
            if sec_normalized:
                section_images.setdefault(sec_normalized, []).append(i)
            else:
                unmatched_images.append(i)

        # 步骤2：为每个 TTS 音频确定其所属 section
        # 通过文本匹配：TTS 的 text 应该能在某个 section 的 sentences 中找到
        section_audio_map = {sec: [] for sec in section_sentence_map}
        unmatched_audio = []

        for audio_item in summary_sentence_files:
            _, text, _ = audio_item
            matched_section = self._match_audio_to_section(
                text, section_sentence_map
            )
            if matched_section:
                section_audio_map[matched_section].append(audio_item)
            else:
                unmatched_audio.append(audio_item)

        # 步骤3：将每个 section 的音频均匀分配到该 section 的图片
        section_order = ["opening", "intro", "method", "results"]
        for section in section_order:
            audio_list = section_audio_map.get(section, [])
            image_list = section_images.get(section, [])

            if not audio_list:
                continue

            if not image_list:
                # 该 section 没有对应图片，放入未匹配池
                unmatched_audio.extend(audio_list)
                continue

            # 均匀分配该 section 的音频到该 section 的图片
            per_image = max(1, (len(audio_list) + len(image_list) - 1) // len(image_list))
            for img_offset, img_idx in enumerate(image_list):
                start = img_offset * per_image
                end = min(start + per_image, len(audio_list))
                groups[img_idx] = audio_list[start:end]

        # 步骤4：将未匹配的音频均匀分配到未匹配的图片（或所有图片）
        if unmatched_audio:
            target_images = unmatched_images if unmatched_images else list(range(n_images))
            if target_images:
                per_img = max(1, (len(unmatched_audio) + len(target_images) - 1) // len(target_images))
                for offset, img_idx in enumerate(target_images):
                    start = offset * per_img
                    end = min(start + per_img, len(unmatched_audio))
                    groups[img_idx].extend(unmatched_audio[start:end])

        matched_count = sum(len(g) for g in groups)
        logging.info(
            f"语义匹配完成: {matched_count}/{total_sent} 句已分配, "
            f"sections={list(section_images.keys())}, "
            f"未匹配图片={len(unmatched_images)}"
        )
        return groups

    @staticmethod
    def _normalize_section(section_name):
        """标准化 section 名称，兼容多种写法。

        Args:
            section_name: 原始 section 名称

        Returns:
            str: 标准化后的 section 名称，无法识别返回空字符串
        """
        if not section_name:
            return ""
        sec = section_name.strip().lower()
        # 处理 "opening/intro" 等复合格式
        if "/" in sec:
            sec = sec.split("/")[0].strip()
        # 映射到标准 section 名
        mapping = {
            "opening": "opening",
            "intro": "intro",
            "introduction": "intro",
            "method": "method",
            "methods": "method",
            "results": "results",
            "result": "results",
            "experiment": "results",
            "experiments": "results",
            "conclusion": "results",
            "other": "",
        }
        return mapping.get(sec, "")

    @staticmethod
    def _match_audio_to_section(audio_text, section_sentence_map):
        """通过文本相似度将音频匹配到最佳 section。

        优先精确子串匹配，回退到字符重叠率比较。

        Args:
            audio_text: TTS 音频的文本内容
            section_sentence_map: {section: [sentence, ...]} 映射

        Returns:
            str: 匹配到的 section 名称，无法匹配返回空字符串
        """
        if not audio_text:
            return ""
        audio_clean = audio_text.strip()

        # 精确子串匹配：音频文本是否是某个 section 句子的子串（或反向）
        for section, sentences in section_sentence_map.items():
            for sent in sentences:
                sent_clean = sent.strip()
                if not sent_clean:
                    continue
                # 双向子串匹配（TTS 分句后可能是原句的一部分）
                if audio_clean in sent_clean or sent_clean in audio_clean:
                    return section

        # 回退：字符重叠率（取最大重叠的 section）
        best_section = ""
        best_overlap = 0.0
        audio_chars = set(audio_clean)

        for section, sentences in section_sentence_map.items():
            section_text = "".join(sentences)
            if not section_text:
                continue
            section_chars = set(section_text)
            overlap = len(audio_chars & section_chars) / max(len(audio_chars), 1)
            if overlap > best_overlap:
                best_overlap = overlap
                best_section = section

        # 要求最低重叠率 0.5 以避免误匹配
        if best_overlap >= 0.5:
            return best_section
        return ""

    @staticmethod
    def _fallback_even_group(summary_sentence_files, n_images):
        """回退逻辑：将摘要句子按数量均匀分配到图片上。

        Args:
            summary_sentence_files: [(path, text, duration), ...]
            n_images: 图片数量

        Returns:
            list[list]: groups[i] = 分配给图片 i 的音频列表
        """
        total_sent = len(summary_sentence_files)
        groups = [[] for _ in range(n_images)]
        if total_sent > 0:
            per = max(1, (total_sent + n_images - 1) // n_images)
            for i in range(n_images):
                start = i * per
                end = min(start + per, total_sent)
                groups[i] = summary_sentence_files[start:end]
        return groups

    def _group_and_trim(self, expl_sentence_files, summary_sentence_files):
        """将摘要音频分组到图片，并按目标时长裁剪。返回 (expl_sentence_files, groups)。

        优先使用基于 section 的语义匹配（需要 structured_plan 和 image_explanations
        中的 recommended_section 字段），不满足条件时回退到均分逻辑。
        """
        n_images = max(1, len(self.images))

        # 使用语义匹配分组（内部含回退逻辑）
        groups = self._semantic_group_sentences(summary_sentence_files)

        if self.target_duration > 0:
            segments = []
            for i in range(n_images):
                expl_sents = expl_sentence_files[i] if i < len(expl_sentence_files) else []
                expl_dur = sum(f[2] for f in expl_sents)
                if expl_dur > 0:
                    segments.append({"type": "expl", "duration": expl_dur, "image_idx": i})
                for (path, txt, dur) in groups[i]:
                    segments.append({"type": "summary", "duration": dur, "image_idx": i})

            trimmed = trim_segments_to_duration(segments, self.target_duration)
            trimmed_expl_indices = {seg["image_idx"] for seg in trimmed if seg["type"] == "expl"}
            trimmed_summary_indices = {seg["image_idx"] for seg in trimmed if seg["type"] == "summary"}

            for i in range(len(expl_sentence_files)):
                if i not in trimmed_expl_indices:
                    expl_sentence_files[i] = []
            for i in range(len(groups)):
                if i not in trimmed_summary_indices:
                    groups[i] = []

        return expl_sentence_files, groups

    def _build_clips_and_subtitles(self, expl_sentence_files, groups):
        """构建视频片段和字幕条目。返回 (clips, subtitle_entries)。"""
        clips = []
        subtitle_entries = []
        cumulative_time = 0
        target_size = (1920, 1080)
        crossfade_duration = 0.5  # 图片间淡入淡出时长（秒）

        # 外部视频片段
        if self.video_clips:
            for vc in self.video_clips:
                try:
                    vc = vc.resized(width=1920, height=1080)
                except Exception:
                    pass
                clips.append(vc)
                if getattr(vc, 'duration', None):
                    cumulative_time += vc.duration

        for i, img in enumerate(self.images):
            expl_sentences = expl_sentence_files[i] if i < len(expl_sentence_files) else []
            image_duration = 0.0

            for (path, text, duration) in expl_sentences:
                subtitle_entries.append({'text': text, 'start': cumulative_time, 'duration': duration})
                cumulative_time += duration
                image_duration += duration

            for (path, txt, duration) in groups[i]:
                subtitle_entries.append({'text': txt, 'start': cumulative_time, 'duration': duration})
                cumulative_time += duration
                image_duration += duration

            if image_duration <= 0:
                image_duration = 0.5
                audio_logger.warning(f"图片 {i} 无音频内容，使用 {image_duration}s 静音填充")

            try:
                clip = _create_ken_burns_clip(img, image_duration, target_size)
            except Exception as e:
                logging.warning(f"Ken Burns 效果创建失败，回退静态图片: {e}")
                # contain + 5% 内边距，与 Ken Burns 保持一致
                scale_factor = min(target_size[0] / img.width, target_size[1] / img.height) * 0.95
                new_size = (int(img.width * scale_factor), int(img.height * scale_factor))
                img2 = img.resize(new_size, Image.Resampling.LANCZOS)
                new_img = Image.new("RGB", target_size, (15, 20, 40))
                paste_position = ((target_size[0] - img2.size[0]) // 2, (target_size[1] - img2.size[1]) // 2)
                new_img.paste(img2, paste_position)
                clip = ImageClip(np.array(new_img)).with_duration(image_duration)

            # 添加淡入淡出转场（首个片段仅淡入，末尾片段仅淡出，中间两者都加）
            if image_duration > crossfade_duration * 2:
                try:
                    effects = []
                    if i > 0 or self.video_clips:
                        effects.append(vfx.CrossFadeIn(crossfade_duration))
                    if i < len(self.images) - 1:
                        effects.append(vfx.CrossFadeOut(crossfade_duration))
                    if effects:
                        clip = clip.with_effects(effects)
                except Exception as e:
                    logging.warning(f"添加转场效果失败: {e}")

            clips.append(clip)

        return clips, subtitle_entries

    def _build_final_audio(self, expl_sentence_files, groups):
        """加载所有音频文件并拼接为最终音频。返回 AudioArrayClip。"""
        all_audio_arrays = []

        with AudioResourceManager() as temp_audio_manager:
            if self.video_clips:
                for vc in self.video_clips:
                    if vc.audio and hasattr(vc.audio, 'duration') and vc.audio.duration > 0:
                        try:
                            audio_array = vc.audio.to_soundarray(fps=44100)
                            all_audio_arrays.append((audio_array, 44100))
                            temp_audio_manager.add_clip(vc.audio)
                        except Exception as e:
                            audio_logger.warning(f"处理视频音频失败: {e}")

            for i in range(len(self.images)):
                expl_sentences = expl_sentence_files[i] if i < len(expl_sentence_files) else []
                for (path, text, duration) in expl_sentences:
                    aclip = safe_audio_clip_loader(path)
                    if aclip:
                        try:
                            all_audio_arrays.append((aclip.to_soundarray(fps=44100), 44100))
                            temp_audio_manager.add_clip(aclip)
                        except Exception as e:
                            audio_logger.warning(f"处理解释音频失败: {e}")
                        finally:
                            try:
                                aclip.close()
                            except Exception:
                                pass

                for (path, txt, duration) in groups[i]:
                    aclip = safe_audio_clip_loader(path)
                    if aclip:
                        try:
                            all_audio_arrays.append((aclip.to_soundarray(fps=44100), 44100))
                            temp_audio_manager.add_clip(aclip)
                        except Exception as e:
                            audio_logger.warning(f"处理摘要音频失败: {e}")
                        finally:
                            try:
                                aclip.close()
                            except Exception:
                                pass

        if not all_audio_arrays:
            raise RuntimeError("没有有效音频")

        final_array = np.concatenate([arr for arr, _ in all_audio_arrays])
        if final_array.size == 0:
            raise RuntimeError("音频数据为空")

        final_audio = AudioArrayClip(final_array, fps=44100)
        if not hasattr(final_audio, 'duration') or final_audio.duration is None:
            final_audio = final_audio.with_duration(len(final_array) / 44100)
        audio_logger.info(f"最终音频生成成功，时长: {final_audio.duration:.2f}秒")
        return final_audio

    def _verify_sync(self, final_audio, subtitle_entries, clips):
        """验证音画同步偏差。"""
        subtitle_total = sum(e['duration'] for e in subtitle_entries) if subtitle_entries else 0
        audio_total = final_audio.duration if hasattr(final_audio, 'duration') and final_audio.duration else 0
        video_total = sum(c.duration for c in clips if hasattr(c, 'duration') and c.duration)
        sync_diff = abs(audio_total - subtitle_total)
        if sync_diff > 0.5:
            audio_logger.warning(
                f"音画同步偏差较大: 音频={audio_total:.2f}s, 字幕={subtitle_total:.2f}s, "
                f"视频={video_total:.2f}s, 偏差={sync_diff:.2f}s"
            )
        else:
            audio_logger.info(
                f"音画同步验证通过: 音频={audio_total:.2f}s, 字幕={subtitle_total:.2f}s, "
                f"视频={video_total:.2f}s, 偏差={sync_diff:.2f}s"
            )

    def _compose_and_export(self, clips, final_audio, subtitle_entries,
                            expl_sentence_files, groups, output_filename):
        """合并视频、叠加字幕和章节标题、导出文件。"""
        logging.info("合并所有视频剪辑")
        self.video = concatenate_videoclips(clips, method="compose")
        self.video = self.video.with_audio(final_audio)
        logging.info(f"视频时长: {self.video.duration:.2f}秒, 音频时长: {final_audio.duration:.2f}秒")

        # 章节标题叠加
        try:
            clips_durations = []
            for i in range(len(self.images)):
                expl_dur = sum(f[2] for f in (expl_sentence_files[i] if i < len(expl_sentence_files) else []))
                summ_dur = sum(f[2] for f in groups[i])
                clips_durations.append((i, expl_dur + summ_dur))
            self._add_chapter_overlay(clips_durations)
        except Exception as e:
            logging.warning(f"章节标题叠加失败，跳过: {e}")

        # 字幕叠加
        self.videocaption(subtitle_entries)

        # 保存视频脚本
        self._save_video_script(output_filename)

        # 确保音频 duration 正确
        if self.video.audio is not None and self.video.audio.duration is None:
            self.video.audio = self.video.audio.with_duration(final_audio.duration)
            audio_logger.info(f"修复音频duration: {final_audio.duration:.2f}秒")

        logging.info(f"导出视频到 {output_filename}")
        self.video.write_videofile(output_filename, fps=24, codec='libx264', preset='ultrafast')
        logging.info("视频导出完成")

        try:
            final_audio.close()
        except Exception:
            pass

        return output_filename

    def create_video(self, output_filename):
        """主入口：生成 TTS 音频 → 构建视频片段 → 合并导出。"""
        logging.info("开始生成摘要与图像解释的音频并组合到视频")

        # 1) 分句
        self.texts = _split_into_sentences(self.text)

        # 测试 TTS
        logging.info("测试音频生成...")
        if self.texts:
            if not test_audio_generation(self.texts[0][:20], 0):
                raise RuntimeError("音频生成失败")
        logging.info("音频生成测试通过")

        # 2) 提取解释文本
        expl_texts = self._prepare_expl_texts()

        # 3-4) 并发 TTS
        expl_sentence_files, summary_sentence_files, _ = self._run_concurrent_tts(expl_texts)

        # 5) 分组 + 裁剪
        expl_sentence_files, groups = self._group_and_trim(expl_sentence_files, summary_sentence_files)

        # 6) 构建视频片段和字幕
        clips, subtitle_entries = self._build_clips_and_subtitles(expl_sentence_files, groups)

        # 7) 构建最终音频
        final_audio = self._build_final_audio(expl_sentence_files, groups)

        # 7.5) 同步验证
        self._verify_sync(final_audio, subtitle_entries, clips)

        # 8-9) 合成导出
        return self._compose_and_export(
            clips, final_audio, subtitle_entries,
            expl_sentence_files, groups, output_filename
        )
