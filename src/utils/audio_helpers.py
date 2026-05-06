"""
音频处理工具模块
提供安全的TTS音频生成、加载、合并和资源管理功能
"""

import os
import logging
import tempfile
import time
from typing import Optional, List, Tuple
from moviepy import AudioFileClip, concatenate_audioclips
from moviepy.audio.AudioClip import AudioArrayClip
import numpy as np


def get_tts_config() -> Tuple[str, str]:
    """统一的 TTS 模型/音色解析。

    优先级: 环境变量 (JSR_TTS_MODEL / JSR_TTS_VOICE)
            > src.config (TTS_MODEL / TTS_VOICE)
            > 默认 cosyvoice-v2 / longxiaochun_v2

    Returns:
        (model, voice) 元组，例如 ("cosyvoice-v2", "longxiaochun_v2")。
    """
    env_model = os.getenv("JSR_TTS_MODEL")
    env_voice = os.getenv("JSR_TTS_VOICE")
    if env_model and env_voice:
        return env_model, env_voice

    cfg_model = None
    cfg_voice = None
    try:  # 软依赖: 测试场景下 src.config 可能未加载
        try:
            from src.config import TTS_MODEL as _M, TTS_VOICE as _V  # type: ignore
        except ImportError:
            from config import TTS_MODEL as _M, TTS_VOICE as _V  # type: ignore
        cfg_model, cfg_voice = _M, _V
    except Exception:
        pass

    model = env_model or cfg_model or "cosyvoice-v2"
    voice = env_voice or cfg_voice or "longxiaochun_v2"
    return model, voice


# 配置专用音频日志记录器
audio_logger = logging.getLogger('audio_processing')
audio_logger.setLevel(logging.DEBUG)

# 检查是否已经有处理器，避免重复添加
if not audio_logger.handlers:
    audio_handler = logging.FileHandler('audio_processing.log', encoding='utf-8')
    audio_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    audio_handler.setFormatter(formatter)
    audio_logger.addHandler(audio_handler)


def safe_tts_save(
    ss,
    text: str,
    output_path: str,
    idx: int,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Optional[str]:
    """
    安全的TTS处理：验证数据、保存文件、验证音频

    Args:
        ss: SpeechSynthesizer实例
        text: 要转换的文本
        output_path: 输出文件路径
        idx: 处理索引，用于日志

    Returns:
        str: 成功时返回文件路径，失败时返回None
    """
    audio_logger.info(f"开始TTS处理 idx={idx}, 文本长度={len(text)}")

    attempts = max(1, max_retries)

    for attempt in range(1, attempts + 1):
        try:
            # 调用TTS
            data = ss.call(text=text)
            audio_logger.debug(f"TTS返回数据类型: {type(data)}")

            # 验证TTS返回数据
            if not data:
                audio_logger.error(f"TTS返回空数据 idx={idx} attempt={attempt}")
                if attempt < attempts:
                    time.sleep(retry_delay * attempt)
                    continue
                return None

            if len(data) < 100:
                audio_logger.warning(f"TTS返回数据过小 idx={idx}, size={len(data)} attempt={attempt}")
                if attempt < attempts:
                    time.sleep(retry_delay * attempt)
                    continue
                return None

            # 验证音频数据头部（WAV格式）
            if len(data) < 12:
                audio_logger.error(f"音频数据过短 idx={idx}, 长度={len(data)} attempt={attempt}")
                if attempt < attempts:
                    time.sleep(retry_delay * attempt)
                    continue
                return None

            # 检查可能的音频格式
            is_wav = data.startswith(b'RIFF') and b'WAVE' in data[:12]
            is_mp3 = data.startswith(b'ID3') or b'.mp3' in data[:10].lower()
            is_aac = data.startswith(b'ADIF') or data.startswith(b'ADTS')
            is_flac = data.startswith(b'fLaC')
            is_ogg = data.startswith(b'OggS')

            if not any([is_wav, is_mp3, is_aac, is_flac, is_ogg]):
                # 记录前20字节的十六进制用于调试
                hex_preview = ' '.join(f'{b:02x}' for b in data[:20])
                audio_logger.warning(f"未知音频格式 idx={idx}, 前20字节: {hex_preview}")
                # 不直接返回None，尝试保存看是否是有效音频

            # 确保目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # 原子写入（先写临时文件，再重命名）
            temp_path = output_path + '.tmp'
            with open(temp_path, 'wb') as f:
                f.write(data)
            os.replace(temp_path, output_path)

            audio_logger.info(f"TTS音频保存成功: {output_path}, 大小={len(data)}字节")

            # 验证生成的音频文件
            if not validate_audio_file(output_path):
                audio_logger.error(f"音频文件验证失败 idx={idx} attempt={attempt}")
                if attempt < attempts:
                    time.sleep(retry_delay * attempt)
                    continue
                return None

            return output_path

        except Exception as e:
            audio_logger.error(f"TTS处理异常 idx={idx} attempt={attempt}: {e}", exc_info=True)
            if attempt < attempts:
                time.sleep(retry_delay * attempt)
                continue
            return None

    return None


def validate_audio_file(file_path: str) -> bool:
    """
    验证音频文件是否有效

    Args:
        file_path: 音频文件路径

    Returns:
        bool: 文件有效返回True，否则返回False
    """
    try:
        if not os.path.exists(file_path):
            audio_logger.error(f"文件不存在: {file_path}")
            return False

        file_size = os.path.getsize(file_path)
        if file_size < 100:
            audio_logger.error(f"文件过小: {file_path}, 大小={file_size}字节")
            return False

        # 尝试加载音频文件
        clip = AudioFileClip(file_path)

        if clip.duration <= 0:
            audio_logger.error(f"音频时长无效: {file_path}")
            clip.close()
            return False

        audio_logger.debug(f"音频文件验证成功: {file_path}, 时长={clip.duration:.2f}秒")
        clip.close()
        return True

    except Exception as e:
        audio_logger.error(f"验证音频文件失败 {file_path}: {e}", exc_info=True)
        return False


def safe_audio_clip_loader(file_path: str) -> Optional[AudioFileClip]:
    """
    使用上下文管理器安全加载AudioFileClip

    Args:
        file_path: 音频文件路径

    Returns:
        AudioFileClip: 成功时返回AudioFileClip，失败时返回None
    """
    if not file_path or not os.path.exists(file_path):
        audio_logger.error(f"音频文件不存在: {file_path}")
        return None

    try:
        # 验证文件大小
        file_size = os.path.getsize(file_path)
        if file_size < 100:
            audio_logger.error(f"音频文件过小: {file_path}, 大小={file_size}字节")
            return None

        clip = AudioFileClip(file_path)

        # 验证音频属性
        if not hasattr(clip, 'duration') or clip.duration <= 0:
            audio_logger.error(f"音频时长无效: {file_path}")
            clip.close()
            return None

        audio_logger.debug(f"音频文件加载成功: {file_path}, 时长={clip.duration:.2f}秒")
        return clip

    except Exception as e:
        audio_logger.error(f"加载音频文件失败 {file_path}: {e}", exc_info=True)
        return None


def create_silent_audio(duration: float = 1.0, fps: int = 44100) -> Optional[AudioArrayClip]:
    """
    生成指定时长的静音音频

    Args:
        duration: 音频时长（秒）
        fps: 采样率

    Returns:
        AudioArrayClip: 成功时返回静音AudioArrayClip，失败时返回None
    """
    try:
        # 生成静音数据（立体声）
        samples = int(duration * fps)
        silent_data = np.zeros((samples, 2), dtype=np.float32)

        audio_logger.debug(f"创建静音音频: 时长={duration}秒, 采样率={fps}Hz")
        return AudioArrayClip(silent_data, fps=fps)

    except Exception as e:
        audio_logger.error(f"创建静音音频失败: {e}", exc_info=True)
        return None


def safe_concatenate_audio(audio_clips: List[Optional[AudioFileClip]],
                          fallback_duration: float = 0.5) -> Optional[AudioArrayClip]:
    """
    安全地合并音频序列，过滤无效clip

    Args:
        audio_clips: 音频clip列表
        fallback_duration: 失败时的静音时长

    Returns:
        AudioArrayClip: 成功时返回合并的音频，失败时返回静音
    """
    try:
        # 过滤有效的音频clip
        valid_clips = []
        for idx, clip in enumerate(audio_clips):
            if clip is not None and hasattr(clip, 'duration') and clip.duration > 0:
                valid_clips.append(clip)
            else:
                audio_logger.warning(f"跳过无效音频clip {idx}")

        # 如果没有有效clip，创建静音
        if not valid_clips:
            audio_logger.info("没有有效音频clip，创建静音")
            return create_silent_audio(fallback_duration)

        # 合并音频
        result = concatenate_audioclips(valid_clips)
        audio_logger.info(f"成功合并 {len(valid_clips)} 个音频片段, 总时长={result.duration:.2f}秒")
        return result

    except Exception as e:
        audio_logger.error(f"音频合并失败: {e}", exc_info=True)
        return create_silent_audio(fallback_duration)


class AudioResourceManager:
    """
    管理音频资源的上下文管理器
    """

    def __init__(self):
        self.clips: List[AudioFileClip] = []

    def add_clip(self, clip: Optional[AudioFileClip]):
        """添加音频clip到管理器"""
        if clip is not None:
            self.clips.append(clip)
            audio_logger.debug(f"添加音频clip到管理器, 当前总数={len(self.clips)}")

    def __enter__(self):
        """进入上下文"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时自动清理"""
        self.cleanup()

    def cleanup(self):
        """清理所有音频资源"""
        closed_count = 0
        for clip in self.clips:
            try:
                if clip is not None:
                    clip.close()
                    closed_count += 1
            except Exception as e:
                audio_logger.error(f"关闭音频clip失败: {e}")

        if closed_count > 0:
            audio_logger.info(f"成功关闭 {closed_count} 个音频资源")
        self.clips.clear()


def atomic_write(file_path: str, data: bytes) -> bool:
    """
    原子写入文件（先写临时文件，再重命名）

    Args:
        file_path: 目标文件路径
        data: 要写入的数据

    Returns:
        bool: 成功返回True，失败返回False
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # 创建临时文件
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(file_path))

        try:
            with os.fdopen(temp_fd, 'wb') as f:
                f.write(data)

            # 原子重命名
            os.replace(temp_path, file_path)
            audio_logger.debug(f"原子写入成功: {file_path}")
            return True

        except Exception as e:
            # 清理临时文件
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
            audio_logger.error(f"原子写入失败: {e}")
            return False

    except Exception as e:
        audio_logger.error(f"原子写入异常: {e}")
        return False


def safe_remove_file(file_path: str) -> bool:
    """
    安全删除文件

    Args:
        file_path: 要删除的文件路径

    Returns:
        bool: 成功返回True，失败返回False
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            audio_logger.debug(f"文件删除成功: {file_path}")
            return True
        return False
    except Exception as e:
        audio_logger.error(f"删除文件失败 {file_path}: {e}")
        return False


def get_audio_info(file_path: str) -> dict:
    """
    获取音频文件信息

    Args:
        file_path: 音频文件路径

    Returns:
        dict: 音频信息字典
    """
    info = {
        'exists': False,
        'size': 0,
        'duration': 0,
        'fps': 0,
        'valid': False
    }

    try:
        if os.path.exists(file_path):
            info['exists'] = True
            info['size'] = os.path.getsize(file_path)

            clip = AudioFileClip(file_path)
            info['duration'] = clip.duration
            info['fps'] = clip.fps
            info['valid'] = True
            clip.close()

    except Exception as e:
        audio_logger.error(f"获取音频信息失败 {file_path}: {e}")

    return info



# ---------------------------------------------------------------------------
# TTS 后端统一入口 (新加, 向前兼容老 dashscope 调用)
# ---------------------------------------------------------------------------

def _resolve_minimax_key() -> Optional[str]:
    """读取 MiniMax api_key, 优先 env 后 config."""
    k = os.getenv("JSR_MINIMAX_API_KEY")
    if k:
        return k
    try:
        try:
            from src.config import _config  # type: ignore
        except ImportError:
            from config import _config  # type: ignore
        return _config.get("minimax_api_key") or None
    except Exception:
        return None


def _resolve_minimax_voice() -> str:
    """读取 MiniMax voice_id, 优先 env > config > 默认 male-qn-qingse.
    JSR_TTS_VOICE 设了非 longxiaochun_v2 的值时也用作 voice_id."""
    v = os.getenv("JSR_MINIMAX_VOICE_ID") or os.getenv("JSR_TTS_VOICE")
    if v and v != "longxiaochun_v2":
        return v
    try:
        try:
            from src.config import _config  # type: ignore
        except ImportError:
            from config import _config  # type: ignore
        cv = _config.get("minimax_voice_id") or _config.get("tts_voice")
        if cv and cv != "longxiaochun_v2":
            return cv
    except Exception:
        pass
    return "male-qn-qingse"


def _is_minimax_model(model: str) -> bool:
    if not model:
        return False
    m = model.lower()
    return "speech" in m or "minimax" in m


def _synthesize_dashscope(text: str, model: str, voice: str) -> bytes:
    """老路径包装: dashscope.audio.tts_v2.SpeechSynthesizer."""
    import dashscope  # noqa: F401  保留 import 触发 SDK 全局 api_key 注入
    from dashscope.audio.tts_v2 import SpeechSynthesizer
    try:
        try:
            from src.config import _config  # type: ignore
        except ImportError:
            from config import _config  # type: ignore
        ds_key = _config.get("dashscope_api_key") or ""
        if ds_key:
            dashscope.api_key = ds_key
    except Exception:
        pass
    ss = SpeechSynthesizer(model=model, voice=voice)
    data = ss.call(text)
    if not data:
        raise RuntimeError(f"dashscope TTS 返回空 (model={model}, voice={voice})")
    return data


def synthesize_tts(text: str) -> bytes:
    """统一 TTS 入口, 按 model 路由 minimax / dashscope.

    返回 mp3 bytes (与 dashscope SpeechSynthesizer.call 兼容).
    失败 (含 minimax 失败 + dashscope fallback 也失败) raise RuntimeError.
    """
    model, voice = get_tts_config()
    if _is_minimax_model(model):
        from .tts_minimax import synthesize_minimax, MiniMaxTTSError  # type: ignore
        api_key = _resolve_minimax_key()
        voice_id = _resolve_minimax_voice()
        if not api_key:
            audio_logger.warning(
                "MiniMax model=%s 但 minimax_api_key 缺失, fallback dashscope", model
            )
            return _synthesize_dashscope(text, "cosyvoice-v2", "longxiaochun_v2")
        try:
            return synthesize_minimax(
                text, api_key=api_key, model=model, voice_id=voice_id
            )
        except MiniMaxTTSError as exc:
            audio_logger.warning(
                "MiniMax TTS 失败, fallback dashscope: %s", exc
            )
            return _synthesize_dashscope(text, "cosyvoice-v2", "longxiaochun_v2")
    # 默认老路径
    return _synthesize_dashscope(text, model, voice)



class _MiniMaxSynthesizerAdapter:
    """SS-like adapter, 给老调用方 ss.call(text) 模式用."""
    def __init__(self, model: str, voice_id: str, api_key: str):
        self._model = model
        self._voice_id = voice_id
        self._api_key = api_key

    def call(self, text: str):
        from .tts_minimax import synthesize_minimax, MiniMaxTTSError  # type: ignore
        try:
            return synthesize_minimax(
                text, api_key=self._api_key,
                model=self._model, voice_id=self._voice_id,
            )
        except MiniMaxTTSError as exc:
            audio_logger.warning("MiniMax adapter 调用失败: %s", exc)
            return None  # 模仿 dashscope 失败时返回空


def make_tts_synthesizer():
    """工厂方法: 返回 SS-like 对象 (有 .call(text) -> bytes 接口).

    按 get_tts_config() 选 minimax / dashscope; 默认仍 dashscope.
    给 video_creator 老链路 (safe_tts_save(ss, ...)) 用, 老接口 0 改动.
    """
    model, voice = get_tts_config()
    if _is_minimax_model(model):
        api_key = _resolve_minimax_key()
        if not api_key:
            audio_logger.warning(
                "MiniMax model=%s 但 minimax_api_key 缺失, factory 退化为 dashscope cosyvoice-v2",
                model,
            )
            from dashscope.audio.tts_v2 import SpeechSynthesizer
            return SpeechSynthesizer(model="cosyvoice-v2", voice="longxiaochun_v2")
        return _MiniMaxSynthesizerAdapter(
            model=model, voice_id=_resolve_minimax_voice(), api_key=api_key,
        )
    # 默认老路径
    import dashscope  # noqa: F401
    from dashscope.audio.tts_v2 import SpeechSynthesizer
    try:
        try:
            from src.config import _config  # type: ignore
        except ImportError:
            from config import _config  # type: ignore
        ds_key = _config.get("dashscope_api_key") or ""
        if ds_key:
            dashscope.api_key = ds_key
    except Exception:
        pass
    return SpeechSynthesizer(model=model, voice=voice)
