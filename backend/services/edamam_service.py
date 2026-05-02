import os
import httpx
from dotenv import load_dotenv

load_dotenv()

EDAMAM_APP_ID = os.getenv("EDAMAM_APP_ID")
EDAMAM_APP_KEY = os.getenv("EDAMAM_APP_KEY")
EDAMAM_BASE_URL = "https://api.edamam.com/api/food-database/v2/parser"


async def lookup_food(query: str) -> dict | None:
    """
    Look up a food by natural language query.
    Returns the best match with calories and macros, or None if not found.
    """
    params = {
        "app_id": EDAMAM_APP_ID,
        "app_key": EDAMAM_APP_KEY,
        "ingr": query,
        "nutrition-type": "cooking",
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(EDAMAM_BASE_URL, params=params)
        if res.status_code != 200:
            return None

        data = res.json()
        hints = data.get("hints", [])
        if not hints:
            return None

        # Take the best match
        food = hints[0]["food"]
        nutrients = food.get("nutrients", {})

        return {
            "food_name": food.get("label"),
            "calories": nutrients.get("ENERC_KCAL"),
            "protein": nutrients.get("PROCNT"),
            "carbs": nutrients.get("CHOCDF"),
            "fat": nutrients.get("FAT"),
            "source": "edamam",
        }