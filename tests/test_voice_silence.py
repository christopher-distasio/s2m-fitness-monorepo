"""A silent voice clip is silence, not speech the app failed to catch.

Values measured 2026-11-27 against whisper-1: 8s of silence came back as
'you' with no_speech_prob 0.94; 'Three eggs.' scored 0.01.
"""

from fastapi.testclient import TestClient

import backend.routes.food as food_routes
from backend.main import app
from backend.services.transcriber import TranscriptResult, is_silence


def test_whisper_invention_on_silence_is_silence():
    assert is_silence(TranscriptResult(text="you", asr=-0.51, no_speech_prob=0.94))
    assert is_silence(TranscriptResult(text="Thank you.", asr=-0.6, no_speech_prob=0.8))
    assert is_silence(TranscriptResult(text="", asr=None, no_speech_prob=None))


def test_real_speech_is_not_silence():
    assert not is_silence(TranscriptResult(text="Three eggs.", asr=-0.71, no_speech_prob=0.01))
    # No signal from Whisper: keep the text.
    assert not is_silence(TranscriptResult(text="you", asr=None, no_speech_prob=None))
    # A long sentence is kept even if the no-speech score is high (quiet voice).
    assert not is_silence(
        TranscriptResult(text="a bowl of oatmeal with blueberries", asr=-0.5, no_speech_prob=0.7)
    )


def test_voice_route_returns_silence_without_parsing(monkeypatch):
    async def fake_transcribe(*_a, **_k):
        return TranscriptResult(text="you", asr=-0.51, no_speech_prob=0.94)

    async def must_not_parse(*_a, **_k):
        raise AssertionError("silence must not reach the food parser")

    monkeypatch.setattr(food_routes, "transcribe_audio_detailed", fake_transcribe)
    monkeypatch.setattr(food_routes, "dispatch_voice_utterance", must_not_parse)
    monkeypatch.setattr(food_routes, "_parse_log_utterance", must_not_parse)
    client = TestClient(app)
    res = client.post(
        "/food/voice",
        data={"user_id": "u1", "conversation_history": "[]"},
        files={"audio": ("recording.webm", b"\0" * 9000, "audio/webm")},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"transcription": "", "silence": True}
