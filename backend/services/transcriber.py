import logging
import os
from dataclasses import dataclass

from openai import AsyncOpenAI
from dotenv import load_dotenv

from backend.services.confidence import extract_asr_logprob

load_dotenv()

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Bias Whisper toward short clarification answers (numbers / brand words).
_CLARIFY_PROMPT = (
    "one two three four five six seven eight nine ten "
    "number option general specific brand generic"
)


@dataclass
class TranscriptResult:
    text: str
    asr: float | None = None
    no_speech_prob: float | None = None


# Whisper invents short words ("you", "Thank you.") for a clip with no
# speech, and reports no_speech_prob ~0.94 for it vs ~0.01 for real speech
# (measured 2026-11-27). Only short text is dropped, so a quiet speaker whose
# real sentence scores high is still heard.
NO_SPEECH_PROB_SILENCE = 0.6
SILENCE_MAX_WORDS = 3


def is_silence(result: "TranscriptResult") -> bool:
    """True when the clip had no speech and the text is a Whisper invention."""
    if not (result.text or "").strip():
        return True
    if result.no_speech_prob is None:
        return False
    return (
        result.no_speech_prob >= NO_SPEECH_PROB_SILENCE
        and len(result.text.split()) <= SILENCE_MAX_WORDS
    )


def _content_type(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".mp4") or lower.endswith(".m4a"):
        return "audio/mp4"
    return "audio/webm"


async def transcribe_audio_detailed(
    audio_bytes: bytes,
    filename: str,
    *,
    clarification: bool = False,
) -> TranscriptResult:
    """Whisper with verbose_json so ASR confidence can be captured.

    Hard rule 1: if verbose_json / logprob extraction fails, return the
    transcript anyway with asr=None (layer skipped) rather than blocking.
    """
    print(f"Audio filename: {filename}, size: {len(audio_bytes)} bytes")
    content_type = _content_type(filename)
    print(f"Content type: {content_type}, clarification={clarification}")
    kwargs: dict = {
        "model": "whisper-1",
        "file": (filename, audio_bytes, content_type),
        "language": "en",
    }
    if clarification:
        kwargs["prompt"] = _CLARIFY_PROMPT

    try:
        response = await client.audio.transcriptions.create(
            **kwargs,
            response_format="verbose_json",
        )
        text = (getattr(response, "text", None) or "").strip()
        asr = None
        no_speech = None
        try:
            asr = extract_asr_logprob(response)
            segments = getattr(response, "segments", None) or []
            probs = []
            for segment in segments:
                nsp = getattr(segment, "no_speech_prob", None)
                if nsp is not None:
                    probs.append(float(nsp))
            if probs:
                no_speech = sum(probs) / len(probs)
        except Exception:
            logger.exception("ASR confidence extraction failed; skipping asr layer")
            asr = None
        print(f"Whisper result: {text!r}")
        return TranscriptResult(text=text, asr=asr, no_speech_prob=no_speech)
    except Exception:
        logger.exception("verbose_json transcription failed; falling back to text")
        response = await client.audio.transcriptions.create(**kwargs)
        text = (getattr(response, "text", None) or "").strip()
        print(f"Whisper result: {text!r}")
        return TranscriptResult(text=text, asr=None, no_speech_prob=None)


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    *,
    clarification: bool = False,
) -> str:
    result = await transcribe_audio_detailed(
        audio_bytes, filename, clarification=clarification
    )
    return result.text
