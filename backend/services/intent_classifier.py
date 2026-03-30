import os
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You are an intent classifier for a voice-first food logging app.
Classify the user's input as exactly one of these intents:
- "log" — logging food or drink
- "delete_last" — delete or remove their last entry
- "read_today" — wants to hear what they've eaten today
- "calories_today" — wants to know their calorie total
- "correct_last" — correcting or editing their last entry
- "unknown" — none of the above

Return ONLY valid JSON, no explanation:
{"intent": "log", "text": "<original input>"}
"""

async def classify_intent(text: str) -> dict:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ],
        temperature=0,
        max_tokens=50,
    )
    content = response.choices[0].message.content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"intent": "unknown", "text": text}