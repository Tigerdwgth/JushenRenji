"""测试 Qwen3-TTS 后端接入 (audio_helpers)。

覆盖:
- _is_qwen_model 路由判定
- _synthesize_qwen: POST 拿 url -> 下载 / base64 data 两种返回
- synthesize_tts 对 qwen model 的路由
- MiniMax 失败回退到 Qwen 男声 (Ethan), 而非旧的 longxiaochun 女声 (防变声)
"""
import os
import sys
import base64

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
for p in (ROOT, SRC):
    if p not in sys.path:
        sys.path.insert(0, p)

from utils import audio_helpers as ah  # noqa: E402


class _Resp:
    def __init__(self, json_data=None, content=b""):
        self._j = json_data
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._j


def test_is_qwen_model():
    assert ah._is_qwen_model("qwen3-tts-flash")
    assert ah._is_qwen_model("qwen-tts")
    assert ah._is_qwen_model("qwen3-tts-instruct-flash")
    assert not ah._is_qwen_model("cosyvoice-v2")
    assert not ah._is_qwen_model("speech-2.8-hd")
    assert not ah._is_qwen_model("")


def test_synthesize_qwen_post_then_download(monkeypatch):
    calls = {}

    def fake_post(self, url, headers=None, json=None, timeout=None):
        calls["body"] = json
        calls["auth"] = headers["Authorization"]
        calls["session_trust_env"] = self.trust_env  # 确认对 dashscope 强制直连
        return _Resp(json_data={"output": {"audio": {"url": "http://oss/x.wav"}}})

    def fake_get(self, url, timeout=None):
        calls["get_url"] = url
        return _Resp(content=b"RIFFxxxxWAVE")

    monkeypatch.setattr(ah, "_resolve_dashscope_key", lambda: "sk-test")
    import requests
    monkeypatch.setattr(requests.Session, "post", fake_post)
    monkeypatch.setattr(requests.Session, "get", fake_get)

    out = ah._synthesize_qwen("你好", model="qwen3-tts-flash", voice="Ethan")
    assert out == b"RIFFxxxxWAVE"
    assert calls["body"]["model"] == "qwen3-tts-flash"
    assert calls["body"]["input"]["voice"] == "Ethan"
    assert calls["body"]["input"]["text"] == "你好"
    assert calls["auth"] == "Bearer sk-test"
    assert calls["get_url"] == "http://oss/x.wav"
    assert calls["session_trust_env"] is False, "Qwen-TTS session 必须 trust_env=False 强制直连"


def test_synthesize_qwen_base64_data(monkeypatch):
    payload = base64.b64encode(b"audiobytes").decode()

    def fake_post(self, url, headers=None, json=None, timeout=None):
        return _Resp(json_data={"output": {"audio": {"data": payload}}})

    monkeypatch.setattr(ah, "_resolve_dashscope_key", lambda: "sk-test")
    import requests
    monkeypatch.setattr(requests.Session, "post", fake_post)
    assert ah._synthesize_qwen("hi") == b"audiobytes"


def test_synthesize_qwen_missing_key_raises(monkeypatch):
    monkeypatch.setattr(ah, "_resolve_dashscope_key", lambda: "")
    with pytest.raises(RuntimeError):
        ah._synthesize_qwen("hi")


def test_synthesize_tts_routes_qwen(monkeypatch):
    monkeypatch.setattr(ah, "get_tts_config", lambda: ("qwen3-tts-flash", "Ethan"))
    seen = {}

    def fake_qwen(text, model="qwen3-tts-flash", voice="Ethan", **k):
        seen["model"] = model
        seen["voice"] = voice
        return b"WAV"

    monkeypatch.setattr(ah, "_synthesize_qwen", fake_qwen)
    assert ah.synthesize_tts("文本") == b"WAV"
    assert seen == {"model": "qwen3-tts-flash", "voice": "Ethan"}


def test_minimax_fallback_uses_qwen_male(monkeypatch):
    """MiniMax 失败时必须回退到 Qwen 男声 Ethan, 不能是 longxiaochun 女声。"""
    monkeypatch.setattr(ah, "get_tts_config", lambda: ("speech-2.8-hd", "male-qn-qingse"))
    monkeypatch.setattr(ah, "_resolve_minimax_key", lambda: "sk-mm")
    monkeypatch.setattr(ah, "_resolve_minimax_voice", lambda: "male-qn-qingse")

    import importlib
    tm = importlib.import_module("utils.tts_minimax")

    def boom(*a, **k):
        raise tm.MiniMaxTTSError("usage limit exceeded")

    monkeypatch.setattr(tm, "synthesize_minimax", boom)

    captured = {}

    def fake_qwen(text, model="qwen3-tts-flash", voice="Ethan", **k):
        captured["voice"] = voice
        return b"WAVMALE"

    monkeypatch.setattr(ah, "_synthesize_qwen", fake_qwen)

    out = ah.synthesize_tts("文本")
    assert out == b"WAVMALE"
    assert captured["voice"] == "Ethan"


def test_make_tts_synthesizer_qwen_adapter(monkeypatch):
    monkeypatch.setattr(ah, "get_tts_config", lambda: ("qwen3-tts-flash", "Ethan"))
    ss = ah.make_tts_synthesizer()
    assert isinstance(ss, ah._QwenSynthesizerAdapter)
    monkeypatch.setattr(ah, "_synthesize_qwen", lambda text, model=None, voice=None: b"WAV")
    assert ss.call("hi") == b"WAV"


def test_make_tts_synthesizer_dashscope_uses_resolve_key(monkeypatch):
    """工厂的 dashscope 分支必须复用 _resolve_dashscope_key (与 _synthesize_dashscope 一致),
    不能再绕过 env 只读 _config —— 否则 env-only key 时两条链路行为不一致 (review #2)。"""
    monkeypatch.setattr(ah, "get_tts_config", lambda: ("cosyvoice-v2", "longxiaochun_v2"))
    monkeypatch.setattr(ah, "_resolve_dashscope_key", lambda: "sk-from-env")

    class _FakeSS:
        def __init__(self, model, voice):
            self.model = model; self.voice = voice

    import dashscope
    monkeypatch.setattr(dashscope, "api_key", "", raising=False)
    import sys
    # mock SpeechSynthesizer (dashscope.audio.tts_v2)
    fake_mod = type(sys)("dashscope.audio.tts_v2")
    fake_mod.SpeechSynthesizer = _FakeSS
    monkeypatch.setitem(sys.modules, "dashscope.audio.tts_v2", fake_mod)

    ss = ah.make_tts_synthesizer()
    assert isinstance(ss, _FakeSS)
    # 工厂应已通过 _resolve_dashscope_key 注入全局 key
    assert dashscope.api_key == "sk-from-env"


def test_synthesize_qwen_download_5xx_does_not_return_error_page(monkeypatch):
    """OSS 下载返回 5xx 错误页时,不能把错误页 bytes 当音频返回 (review #3: 下载需 raise_for_status)。"""
    class _Err5xx:
        status_code = 503
        text = "<html>service unavailable</html>"
        content = b"<html>service unavailable</html>"
        def raise_for_status(self):
            raise __import__("requests").HTTPError("503 Server Error")
        def json(self):
            return {}

    def fake_post(self, url, headers=None, json=None, timeout=None):
        return _Resp(json_data={"output": {"audio": {"url": "http://oss/x.wav"}}})

    def fake_get(self, url, timeout=None):
        return _Err5xx()

    monkeypatch.setattr(ah, "_resolve_dashscope_key", lambda: "sk-test")
    import requests
    monkeypatch.setattr(requests.Session, "post", fake_post)
    monkeypatch.setattr(requests.Session, "get", fake_get)
    # attempts=1 避免重试拖时间; 该错应让函数最终 raise RuntimeError 而非返回错误页 bytes
    with pytest.raises(RuntimeError):
        ah._synthesize_qwen("hi", attempts=1)
