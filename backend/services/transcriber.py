import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    print(f"Audio filename: {filename}, size: {len(audio_bytes)} bytes")
    content_type = "audio/mp4" if filename.endswith(".mp4") else "audio/webm"
    print(f"Content type: {content_type}")
    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, audio_bytes, content_type),
    )
    print(f"Whisper result: {response.text}")
    return response.text