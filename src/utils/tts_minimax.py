"""MiniMax T2A v2 TTS 后端.

API: POST https://api.minimaxi.com/v1/t2a_v2
Auth: Authorization: Bearer <api_key>
Response: {"data": {"audio": "<hex 字符串>"}, "base_resp": {"status_code": 0}}

直接走 HTTP 不依赖 SDK, 输出与 dashscope SpeechSynthesizer.call() 兼容的
bytes (mp3) 给上层 generate_tts.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"
DEFAULT_VOICE_ID = "male-qn-qingse"
DEFAULT_SAMPLE_RATE = 32000
DEFAULT_BITRATE = 128000
DEFAULT_FORMAT = "mp3"


class MiniMaxTTSError(RuntimeError):
    pass


def synthesize_minimax(
    text: str,
    *,
    api_key: str,
    model: str = "speech-2.8-hd",
    voice_id: str = DEFAULT_VOICE_ID,
    speed: float = 1.0,
    vol: float = 1.0,
    pitch: int = 0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    bitrate: int = DEFAULT_BITRATE,
    audio_format: str = DEFAULT_FORMAT,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: int = 60,
    retries: int = 1,
    _post_fn=None,  # 测试注入
) -> bytes:
    """同步合成单段文本; 失败 raise MiniMaxTTSError.

    Returns:
        bytes: ``mp3`` 二进制 (audio_format='mp3' 时), 与 dashscope 老接口
        ``synthesizer.call(text)`` 返回兼容.
    """
    if not text or not text.strip():
        raise MiniMaxTTSError("text 为空")
    if not api_key:
        raise MiniMaxTTSError("MiniMax api_key 缺失")

    payload = {
        "model": model,
        "text": text,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": vol,
            "pitch": pitch,
        },
        "audio_setting": {
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": audio_format,
            "channel": 1,
        },
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _do_post():
        if _post_fn is not None:
            return _post_fn(endpoint, payload, headers, timeout)
        import requests
        return requests.post(endpoint, json=payload, headers=headers, timeout=timeout)

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = _do_post()
            status = getattr(resp, "status_code", 0)
            if status != 200:
                raise MiniMaxTTSError(
                    f"HTTP {status}: {getattr(resp, 'text', '')[:200]}"
                )
            body = resp.json()
            base = body.get("base_resp") or {}
            if base.get("status_code") not in (0, None):
                raise MiniMaxTTSError(
                    f"MiniMax 业务错误 status={base.get('status_code')} msg={base.get('status_msg')}"
                )
            data = body.get("data") or {}
            hex_str = data.get("audio")
            if not hex_str:
                raise MiniMaxTTSError(f"返回缺 data.audio, 原始: {str(body)[:300]}")
            try:
                return bytes.fromhex(hex_str)
            except ValueError as exc:
                raise MiniMaxTTSError(f"hex 解码失败: {exc}") from exc
        except MiniMaxTTSError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                logger.warning(
                    "[minimax-tts] 调用失败 (第 %d 次, 共 %d): %s, 重试中",
                    attempt + 1, retries + 1, exc,
                )
                time.sleep(1)
                continue
            raise MiniMaxTTSError(f"网络/未知错误: {exc}") from exc
    raise MiniMaxTTSError(f"重试 {retries + 1} 次后仍失败: {last_err}")
