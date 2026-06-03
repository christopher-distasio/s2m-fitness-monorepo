import os

import httpx
from dotenv import load_dotenv

load_dotenv()

USDA_API_KEY = os.getenv("USDA_API_KEY")
USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"


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

    print("USDA query:", query)
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
