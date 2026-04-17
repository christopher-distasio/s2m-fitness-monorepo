from openai import AsyncOpenAI
import os
import json
from pydantic import BaseModel, Field

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class FoodAlternative(BaseModel):
    food: str
    confidence: float

class NutritionParse(BaseModel):
    food: str
    quantity: str
    confidence: float
    reasoning: str
    alternatives: list[FoodAlternative] = Field(default_factory=list)
    estimated_calories: int

async def parse_nutrition(transcript: str) -> list[NutritionParse]:
    prompt = f"""Parse food from transcript. Return valid JSON array only, no markdown.

Transcript: "{transcript}"

[{{"food": "...", "quantity": "...", "confidence": 0.0, "reasoning": "...", "alternatives": [...], "estimated_calories": 0}}]"""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    text = response.choices[0].message.content.strip()
    data = json.loads(text)
    
    return [NutritionParse(**item) for item in (data if isinstance(data, list) else [data])]