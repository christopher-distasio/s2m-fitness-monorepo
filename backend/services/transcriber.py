import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Bias Whisper toward short clarification answers (numbers / brand words).
_CLARIFY_PROMPT = (
    "one two three four five six seven eight nine ten "
    "number option general specific brand generic"
)


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    *,
    clarification: bool = False,
) -> str:
    print(f"Audio filename: {filename}, size: {len(audio_bytes)} bytes")
    lower = (filename or "").lower()
    if lower.endswith(".wav"):
        content_type = "audio/wav"
    elif lower.endswith(".mp4") or lower.endswith(".m4a"):
        content_type = "audio/mp4"
    else:
        content_type = "audio/webm"
    print(f"Content type: {content_type}, clarification={clarification}")
    kwargs: dict = {
        "model": "whisper-1",
        "file": (filename, audio_bytes, content_type),
        "language": "en",
    }
    if clarification:
        kwargs["prompt"] = _CLARIFY_PROMPT
    response = await client.audio.transcriptions.create(**kwargs)
    print(f"Whisper result: {response.text!r}")
    return (response.text or "").strip()
