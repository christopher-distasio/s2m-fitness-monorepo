import json
import os

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

from ..models import Correction

load_dotenv()

USDA_API_KEY = os.getenv("USDA_API_KEY")
USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

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


def _energy_kcal(food_nutrients: list) -> float | None:
    for nutrient in food_nutrients:
        if nutrient.get("nutrientName") == "Energy" and nutrient.get("unitName") == "kcal":
            value = nutrient.get("value")
            if value is not None:
                return value
    return None


def _nutrient_value(food_nutrients: list, nutrient_name: str) -> float | None:
    for nutrient in food_nutrients:
        if nutrient.get("nutrientName") == nutrient_name:
            return nutrient.get("value")
    return None


def _map_food_item(item: dict) -> dict | None:
    food_nutrients = item.get("foodNutrients", [])
    calories = _energy_kcal(food_nutrients)
    if calories is None:
        return None

    return {
        "food_name": item.get("description"),
        "calories": calories,
        "protein": _nutrient_value(food_nutrients, "Protein"),
        "carbs": _nutrient_value(food_nutrients, "Carbohydrate, by difference"),
        "fat": _nutrient_value(food_nutrients, "Total lipid (fat)"),
        "source": "usda",
    }


async def lookup_food(query: str) -> dict | None:
    """
    Look up a food by natural language query via USDA FoodData Central.
    Returns the first match with Energy (kcal), or None if not found.
    """
    if not USDA_API_KEY:
        return None

    params = [
        ("query", query),
        ("api_key", USDA_API_KEY),
        ("pageSize", 5),
        ("dataType", "Branded"),
        ("dataType", "Foundation"),
        ("dataType", "SR Legacy"),
    ]

    async with httpx.AsyncClient() as http_client:
        res = await http_client.get(USDA_SEARCH_URL, params=params)
        if res.status_code != 200:
            return None

        data = res.json()
        foods = data.get("foods", [])
        if not foods:
            return None

        for item in foods:
            mapped = _map_food_item(item)
            if mapped is not None:
                return mapped

    return None


async def get_user_corrections(user_id: str, limit: int = 5) -> list:
    corrections = (
        await Correction.find({"user_id": user_id})
        .sort("-timestamp")
        .limit(limit)
        .to_list()
    )
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
