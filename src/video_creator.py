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
from config import *
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
    def __init__(self, images, text, video_clips=None, image_explanations=None, target_duration=0):
        """images: list of PIL.Image
        text: full summary text
        video_clips: optional list of VideoFileClip (external video materials)
        image_explanations: optional list of dicts (from ImageAgent.explain_images)
        target_duration: 目标视频时长（秒），0 表示不限制
        """
        self.images = images
        self.text = text
        self.video_clips = video_clips or []
        self.image_explanations = image_explanations or []
        self.target_duration = target_duration
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
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)

        logging.info(f"视频脚本已保存到: {json_path}")
        return json_path

    def videocaption(self, subtitle_entries):
        """Overlay per-sentence subtitles.

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
            if len(txt) > 30:  # 如果文本超过30个字符，进行句子分割
                sentences = _split_into_sentences(txt)
                if len(sentences) > 1:
                    # 将时长平分到每个句子
                    per_sentence_dur = duration / len(sentences)
                    for i, sentence in enumerate(sentences):
                        sentence_start = start + i * per_sentence_dur
                        sentence = _wrap_text(sentence)
                        tclip = TextClip(text=sentence,
                                         font_size=48,
                                         size=(1920, 1080),
                                         font=FONT_PATH,
                                         color='white',
                                         stroke_color='black',
                                         stroke_width=2,
                                         method='caption',
                                         horizontal_align='center',
                                         vertical_align='bottom')
                        tclip = tclip.with_start(sentence_start).with_duration(per_sentence_dur)
                        txt_clips.append(tclip)
                    continue

            # 如果不需要分割或分割失败，直接创建clip
            txt = _wrap_text(txt)
            tclip = TextClip(text=txt,
                             font_size=48,
                             size=(1920, 1080),
                             font=FONT_PATH,
                             color='white',
                             stroke_color='black',
                             stroke_width=2,
                             method='caption',
                             horizontal_align='center',
                             vertical_align='bottom')
            tclip = tclip.with_start(start).with_duration(duration)
            txt_clips.append(tclip)

        if txt_clips:
            subtitles = CompositeVideoClip(txt_clips, size=(1920, 1080))
            self.video = CompositeVideoClip([self.video, subtitles])



    def create_video(self, output_filename):
        logging.info("开始生成摘要与图像解释的音频并组合到视频")
        # 1) split summary into sentences
        self.texts = _split_into_sentences(self.text)

        # 先测试音频生成是否正常
        logging.info("测试音频生成...")
        if self.texts:
            test_text = self.texts[0][:20]  # 取前20个字符测试
            if not test_audio_generation(test_text, 0):
                logging.error("音频生成测试失败，请检查TTS配置")
                raise RuntimeError("音频生成失败")
        logging.info("音频生成测试通过")

        model = "cosyvoice-v1"
        voice = "longxiaochun"

        # 2) prepare per-image explanation text
        expl_texts = []
        for i in range(len(self.images)):
            try:
                expl_obj = self.image_explanations[i] if i < len(self.image_explanations) else {}
            except Exception:
                expl_obj = {}
            expl = ''
            if isinstance(expl_obj, dict):
                # 优先使用transition字段（过渡语句）
                transition_value = expl_obj.get('transition')
                if transition_value:
                    if isinstance(transition_value, list):
                        expl = '；'.join(str(v) for v in transition_value)
                    else:
                        expl = str(transition_value)
                # 其次使用context字段（上下文说明）
                elif expl_obj.get('context'):
                    context_value = expl_obj.get('context')
                    if isinstance(context_value, list):
                        expl = '；'.join(str(v) for v in context_value)
                    else:
                        expl = str(context_value)
                # 再使用detailed_explanation字段
                elif expl_obj.get('detailed_explanation'):
                    detailed_value = expl_obj.get('detailed_explanation')
                    if isinstance(detailed_value, list):
                        expl = '；'.join(str(v) for v in detailed_value)
                    else:
                        expl = str(detailed_value)
                # 最后使用key_points字段
                elif expl_obj.get('key_points'):
                    key_points = expl_obj.get('key_points')
                    if isinstance(key_points, list):
                        expl = '；'.join(str(v) for v in key_points)
                    else:
                        expl = str(key_points)
                # 最最后使用caption字段
                elif expl_obj.get('caption'):
                    caption_value = expl_obj.get('caption')
                    if isinstance(caption_value, list):
                        expl = '；'.join(str(v) for v in caption_value)
                    else:
                        expl = str(caption_value)
            expl_texts.append((expl or '').strip())

        # 3) synthesize explanation audios - 为每个短句单独生成音频
        # 每张图片的每个句子单独生成语音，保存文件路径用于后续处理
        # expl_sentence_files[idx] = [(path, text, duration), ...]
        expl_sentence_files = []  # 每张图片的句子级音频文件列表
        for idx, et in enumerate(expl_texts):
            try:
                if not et:
                    audio_logger.info(f"图像 {idx} 没有解释文本，跳过")
                    expl_sentence_files.append([])
                    continue

                # 先分句
                all_sentences = _split_into_sentences(et)
                if not all_sentences:
                    all_sentences = [et]

                # 过滤空句子，只保留有效的句子
                sentences = [s.strip() for s in all_sentences if s.strip()]
                if not sentences:
                    sentences = [et.strip()]

                audio_logger.info(f"合成图像解释音频 {idx}: {len(sentences)} 个短句")

                sentence_files = []  # 该图片的句子音频文件列表

                for sent_idx, sentence in enumerate(sentences):
                    audio_logger.info(f"  短句 {sent_idx}: {sentence[:30]}...")
                    ss = SpeechSynthesizer(model=model, voice=voice)
                    audio_file = f'./cache/expl_{idx}_{sent_idx}.wav'

                    # 使用安全的TTS保存
                    result_path = safe_tts_save(ss, sentence, audio_file, f"{idx}_{sent_idx}")
                    if not result_path:
                        audio_logger.error(f"  短句 {sent_idx} 音频生成失败")
                        continue

                    # 验证文件存在且有效
                    if not os.path.exists(result_path):
                        audio_logger.error(f"  短句 {sent_idx} 音频文件不存在")
                        continue

                    file_size = os.path.getsize(result_path)
                    if file_size < 100:
                        audio_logger.error(f"  短句 {sent_idx} 音频文件过小: {file_size}字节")
                        continue

                    # 加载音频clip获取时长
                    clip = safe_audio_clip_loader(result_path)
                    if clip:
                        duration = clip.duration
                        clip.close()  # 关闭clip，只保留文件路径
                        audio_logger.info(f"  短句 {sent_idx} 音频生成成功，时长: {duration:.2f}秒")
                        sentence_files.append((result_path, sentence, duration))
                    else:
                        audio_logger.error(f"  短句 {sent_idx} 音频加载失败")

                expl_sentence_files.append(sentence_files)
                total_dur = sum(f[2] for f in sentence_files)
                audio_logger.info(f"图像 {idx} 解释音频生成完成，{len(sentence_files)} 个句子，总时长: {total_dur:.2f}秒")

            except Exception as e:
                audio_logger.error(f"合成图像解释音频失败 idx={idx}: {e}", exc_info=True)
                expl_sentence_files.append([])

        # 4) synthesize summary sentence audios and keep mapping
        # 注意：不要使用 AudioResourceManager，这里只存储文件路径，不是AudioFileClip
        summary_sentence_files = []
        for idx, txt in enumerate(self.texts):
            audio_logger.info(f"合成摘要音频 {idx}: {txt[:50]}...")

            ss = SpeechSynthesizer(model=model, voice=voice)
            path = f'./cache/summary{idx}.wav'

            # 使用安全的TTS保存
            result_path = safe_tts_save(ss, txt, path, idx)
            if result_path:
                summary_sentence_files.append((result_path, txt))
                audio_logger.info(f"摘要音频 {idx} 生成成功")
            else:
                audio_logger.error(f"摘要音频 {idx} 生成失败，跳过此句")

        # 5) group summary sentences into per-image groups (contiguous chunks)
        n_images = max(1, len(self.images))
        total_sent = len(summary_sentence_files)
        groups = [[] for _ in range(n_images)]
        if total_sent > 0:
            per = max(1, (total_sent + n_images - 1) // n_images)
            for i in range(n_images):
                start = i * per
                end = min(start + per, total_sent)
                groups[i] = summary_sentence_files[start:end]

        # 5.5) TTS 后兜底裁剪
        if self.target_duration > 0:
            segments = []
            for i in range(n_images):
                expl_sents = expl_sentence_files[i] if i < len(expl_sentence_files) else []
                expl_dur = sum(f[2] for f in expl_sents)
                if expl_dur > 0:
                    segments.append({"type": "expl", "duration": expl_dur, "image_idx": i})
                for (path, txt) in groups[i]:
                    clip = safe_audio_clip_loader(path)
                    dur = clip.duration if clip else 2.0
                    if clip:
                        clip.close()
                    segments.append({"type": "summary", "duration": dur, "image_idx": i})

            trimmed = trim_segments_to_duration(segments, self.target_duration)
            # 根据裁剪结果过滤 expl 和 summary
            trimmed_expl_indices = set()
            trimmed_summary_indices = set()
            for seg in trimmed:
                if seg["type"] == "expl":
                    trimmed_expl_indices.add(seg["image_idx"])
                elif seg["type"] == "summary":
                    trimmed_summary_indices.add(seg["image_idx"])

            for i in range(len(expl_sentence_files)):
                if i not in trimmed_expl_indices:
                    expl_sentence_files[i] = []
            for i in range(len(groups)):
                if i not in trimmed_summary_indices:
                    groups[i] = []

        # 6) build per-image clips and subtitle entries (音频在步骤7统一加载)
        clips = []
        subtitle_entries = []

        # add external video clips first (if any)
        cumulative_time = 0
        if self.video_clips:
            for vc in self.video_clips:
                try:
                    vc = vc.resized(width=1920, height=1080)
                except Exception:
                    pass
                clips.append(vc)
                if getattr(vc, 'duration', None):
                    cumulative_time += vc.duration

        target_size = (1920, 1080)
        for i, img in enumerate(self.images):
            # 1) 先处理该图片的所有解释句子 - 每个句子单独处理
            expl_sentences = expl_sentence_files[i] if i < len(expl_sentence_files) else []
            image_duration = 0.0  # 该图片的总时长

            # 处理每个解释句子 - 只添加字幕条目，音频在步骤7统一加载
            for (path, text, duration) in expl_sentences:
                subtitle_entries.append({
                    'text': text,
                    'start': cumulative_time,
                    'duration': duration
                })
                cumulative_time += duration
                image_duration += duration

            # 2) 处理该图片的摘要句子
            summary_texts_for_img = []
            for (path, txt) in groups[i]:
                summary_texts_for_img.append((path, txt))

            # 添加摘要字幕
            for (path, txt) in summary_texts_for_img:
                subtitle_entries.append({
                    'text': txt,
                    'start': cumulative_time,
                    'duration': 2.0  # 使用默认时长，音频实际时长会在步骤7使用
                })
                cumulative_time += 2.0
                image_duration += 2.0

            # 确保图片至少有最小时长
            if image_duration <= 0:
                image_duration = 0.5

            # 3) 创建图片视觉部分
            scale_factor = min(target_size[0] / img.width, target_size[1] / img.height)
            new_size = (int(img.width * scale_factor), int(img.height * scale_factor))
            img2 = img.resize(new_size, Image.Resampling.LANCZOS)
            new_img = Image.new("RGB", target_size, (0, 0, 0))
            paste_position = ((target_size[0] - img2.size[0]) // 2, (target_size[1] - img2.size[1]) // 2)
            new_img.paste(img2, paste_position)
            img_array = np.array(new_img)
            clip = ImageClip(img_array).with_duration(image_duration)
            clips.append(clip)

        # 7) build final audio sequence - 使用 AudioArrayClip 安全合并音频
        all_audio_arrays = []  # 存储 (audio_array, fps)

        # 使用独立的资源管理器处理临时音频文件
        with AudioResourceManager() as temp_audio_manager:
            # 添加外部视频音频
            if self.video_clips:
                for vc in self.video_clips:
                    if vc.audio and hasattr(vc.audio, 'duration') and vc.audio.duration > 0:
                        try:
                            # 转换为数组
                            audio_array = vc.audio.to_soundarray(fps=44100)
                            all_audio_arrays.append((audio_array, 44100))
                            temp_audio_manager.add_clip(vc.audio)
                        except Exception as e:
                            audio_logger.warning(f"处理视频音频失败: {e}")

            # 从解释句子文件加载音频并转换为数组
            for sentences in expl_sentence_files:
                for (path, text, duration) in sentences:
                    clip = safe_audio_clip_loader(path)
                    if clip:
                        try:
                            audio_array = clip.to_soundarray(fps=44100)
                            all_audio_arrays.append((audio_array, 44100))
                            temp_audio_manager.add_clip(clip)
                        except Exception as e:
                            audio_logger.warning(f"处理解释音频失败: {e}")
                        finally:
                            try:
                                clip.close()
                            except:
                                pass
                    else:
                        audio_logger.error(f"重新加载解释音频失败: {path}")

            # 加载摘要音频
            for (path, txt) in summary_sentence_files:
                clip = safe_audio_clip_loader(path)
                if clip:
                    try:
                        audio_array = clip.to_soundarray(fps=44100)
                        all_audio_arrays.append((audio_array, 44100))
                        temp_audio_manager.add_clip(clip)
                    except Exception as e:
                        audio_logger.warning(f"处理摘要音频失败: {e}")
                    finally:
                        try:
                            clip.close()
                        except:
                            pass
                else:
                    audio_logger.error(f"重新加载摘要音频失败: {path}")

        # 在资源管理器外部创建最终音频
        # 合并所有音频数组
        if not all_audio_arrays:
            raise RuntimeError("没有有效音频")

        # 拼接所有音频
        final_array = np.concatenate([arr for arr, _ in all_audio_arrays])
        audio_logger.info(f"音频数组形状: {final_array.shape}, 大小: {final_array.size}")

        if final_array.size == 0:
            raise RuntimeError("音频数据为空")

        # 创建 AudioArrayClip
        final_audio = AudioArrayClip(final_array, fps=44100)
        if not hasattr(final_audio, 'duration') or final_audio.duration is None:
            # 计算 duration
            expected_duration = len(final_array) / 44100
            final_audio = final_audio.with_duration(expected_duration)
        audio_logger.info(f"最终音频生成成功，时长: {final_audio.duration:.2f}秒")

        # 8) merge video clips and attach final audio
        logging.info("合并所有视频剪辑")
        self.video = concatenate_videoclips(clips, method="compose")

        # 使用合并后的音频
        self.video = self.video.with_audio(final_audio)
        logging.info(f"视频时长: {self.video.duration:.2f}秒, 音频时长: {final_audio.duration:.2f}秒")
        audio_logger.info(f"视频音频合并成功 - 视频时长: {self.video.duration:.2f}秒, 音频时长: {final_audio.duration:.2f}秒")

        # 9) add subtitles overlay (per-sentence entries)
        self.videocaption(subtitle_entries)

        logging.info("视频剪辑合并完成")
        logging.info(f"导出视频到 {output_filename}")

        # 保存视频脚本JSON
        self._save_video_script(output_filename)

        # 在写入前，确保视频音频的duration正确
        if self.video.audio is not None:
            # 显式设置音频的duration，防止写入时丢失
            expected_audio_duration = final_audio.duration
            if self.video.audio.duration is None:
                self.video.audio = self.video.audio.with_duration(expected_audio_duration)
                audio_logger.info(f"修复音频duration: {expected_audio_duration:.2f}秒")

        self.video.write_videofile(output_filename, fps=24, codec='libx264', preset='ultrafast')
        logging.info("视频导出完成")

        # 关闭音频
        if final_audio:
            try:
                final_audio.close()
            except:
                pass

        return output_filename
