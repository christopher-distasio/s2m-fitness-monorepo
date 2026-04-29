import dotenv
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI()

VALID_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}

async def generate_speech(text: str, voice: str = "alloy") -> bytes:
    if voice not in VALID_VOICES:
        voice = "alloy"
    response = await client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
    )
    return response.content