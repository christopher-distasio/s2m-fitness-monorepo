from pydantic import BaseModel
from openai import AsyncOpenAI
import os
import json
from ..models import Correction


client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class FoodAlternative(BaseModel):
    food: str
    confidence: float
class NutritionParse(BaseModel):
    food: str
    quantity: str
    confidence: float
    reasoning: str
    alternatives: list[FoodAlternative]
    estimated_calories: int

async def get_user_corrections(user_id: str, limit: int = 5) -> list:
    corrections = await Correction.find({"user_id": user_id}).sort("-timestamp").limit(limit).to_list()
    return corrections or []

async def parse_nutrition(transcript: str) -> list[NutritionParse]:
    prompt = f"""Parse this food transcript and return confidence scores.

Confidence Scoring Rules:
- If transcript contains "maybe", "I think", "probably", "around", "possibly": confidence <= 0.7
- "Some" or "a bit" (vague quantifiers): max confidence 0.65
- Specific units ("6 oz", "cup", "palm-sized"): confidence 0.8+
- User explicitly confident ("definitely", "I had"): 0.85+
- Direct measurement ("size of my palm"): 0.8+

Transcript: "{transcript}"

For each food mentioned, return JSON:
{{
  "food": "item name",
  "quantity": "amount with unit" as a string
  "confidence": 0.0-1.0,
  "reasoning": "why this confidence level",
  "alternatives": [
    {{"food": "alt1", "confidence": 0.X}},
    {{"food": "alt2", "confidence": 0.Y}}
  ],
  "estimated_calories": 000
}}

Only include alternatives if confidence is 0.5-0.8. Return array of items."""

    response = await client.chat.completions.create(        
        model="gpt-4o-mini",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    
    text = response.choices[0].message.content.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    data = json.loads(text)
    return [NutritionParse(**item) for item in (data if isinstance(data, list) else [data])]