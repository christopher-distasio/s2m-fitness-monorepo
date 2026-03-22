import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, audio_bytes),
    )
    return response.text