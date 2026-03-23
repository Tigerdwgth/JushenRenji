import os
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _DummyClip:
    def __init__(self, duration=1.25):
        self.duration = duration

    def close(self):
        return None


def test_safe_tts_save_retries_after_empty_response(monkeypatch, tmp_path):
    from utils import audio_helpers

    output = tmp_path / "retry.wav"
    calls = {"count": 0}

    class FakeSynth:
        def call(self, text):
            calls["count"] += 1
            if calls["count"] == 1:
                return b""
            return b"RIFF1234WAVE" + b"x" * 256

    monkeypatch.setattr(audio_helpers, "validate_audio_file", lambda path: True)
    monkeypatch.setattr(audio_helpers.time, "sleep", lambda _: None)

    result = audio_helpers.safe_tts_save(
        FakeSynth(),
        "hello world",
        str(output),
        "summary_0",
        max_retries=2,
        retry_delay=0,
    )

    assert result == str(output)
    assert output.exists()
    assert calls["count"] == 2


def test_run_concurrent_tts_retries_failed_tasks_serially(monkeypatch, tmp_path):
    import video_creator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TTS_MAX_WORKERS", "2")
    monkeypatch.setenv("TTS_SERIAL_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(video_creator, "_split_into_sentences", lambda text: [text])
    monkeypatch.setattr(video_creator, "SpeechSynthesizer", lambda **kwargs: object())
    monkeypatch.setattr(video_creator, "safe_audio_clip_loader", lambda path: _DummyClip())

    call_counts = {}

    def fake_safe_tts_save(ss, text, output_path, tag, **kwargs):
        call_counts[tag] = call_counts.get(tag, 0) + 1
        if tag == "summary_1" and call_counts[tag] == 1:
            return None
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF1234WAVE" + b"x" * 256)
        return str(path)

    monkeypatch.setattr(video_creator, "safe_tts_save", fake_safe_tts_save)

    vc = video_creator.VideoCreator(
        images=[Image.new("RGB", (32, 32), "white")],
        text="unused",
        image_explanations=[{"detailed_explanation": "解释文本"}],
    )
    vc.texts = ["第一句摘要", "第二句摘要"]

    expl_files, summary_files, _ = vc._run_concurrent_tts(["解释文本"])

    assert call_counts["summary_1"] == 2
    assert len(summary_files) == 2
    assert len(expl_files) == 1
