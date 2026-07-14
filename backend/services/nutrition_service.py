import json
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pinecone import Pinecone
# import httpx  # kept for potential future use — see commented fallback block below

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY").strip()
USDA_API_KEY = os.getenv("USDA_API_KEY")  # unused now, kept for the commented fallback below
INDEX_NAME = "food-index"
EMBEDDING_MODEL = "text-embedding-3-large"
SCORE_THRESHOLD = 0.3

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)

# Phrases that indicate a food's serving size = the whole container, not a
# single portion (e.g. "PER CAN"). Affects ~0.6% of branded foods — rare, but
# worth surfacing so the app/UI can note it rather than silently treating a
# whole-container amount as a typical single serving.
WHOLE_CONTAINER_PHRASES = ["per can", "per container", "per bottle", "per package", "per bag", "per jar"]


def is_whole_container_serving(household_serving_fulltext: str) -> bool:
    text = (household_serving_fulltext or "").strip().lower()
    return any(phrase in text for phrase in WHOLE_CONTAINER_PHRASES)


def get_serving_size_g(metadata: dict) -> tuple[float, str]:
    """
    Returns (serving_size_g, source_label). Handles both dataset shapes:
    - Branded foods: a single serving_size_g field directly in metadata.
    - SR Legacy foods: a portions_json field with multiple named portion
      options, none of which is "the" serving size the way a label declares
      one — so we pick a default (first available) portion.
    Falls back to 100 (i.e. return raw per-100g values, unscaled) only if
    neither is present, so behavior is at least predictable, not silently
    wrong, for any food this doesn't yet handle.
    """
    if metadata.get("serving_size_g"):
        return metadata["serving_size_g"], "branded_serving_size"

    portions_raw = metadata.get("portions_json")
    if portions_raw:
        try:
            portions = json.loads(portions_raw)
        except (json.JSONDecodeError, TypeError):
            portions = []
        for portion in portions:
            gram_weight = portion.get("gram_weight")
            if gram_weight:
                return gram_weight, "sr_legacy_default_portion"

    return 100, "no_serving_data_fallback"


async def lookup_food(query: str) -> dict | None:
    print("RAG query:", query)

    embedding_response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    )
    query_vector = embedding_response.data[0].embedding

    results = index.query(
        vector=query_vector,
        top_k=5,
        include_metadata=True,
    )

    matches = results.get("matches", [])
    if not matches:
        return None

    match = matches[0]
    if match.get("score", 0) < SCORE_THRESHOLD:
        return None

    metadata = match.get("metadata", {})
    fdc_id = match["id"]

    print(f"Top match: {metadata.get('name')} — score: {match['score']}")

    # Pinecone stores nutrient values per 100g. serving_size_g (branded) or
    # a default portion's gram_weight (SR Legacy) tells us the actual amount
    # to scale to, instead of returning raw per-100g values.
    serving_size_g, serving_source = get_serving_size_g(metadata)
    multiplier = serving_size_g / 100

    calories = (metadata.get("calories") or 0) * multiplier
    protein = (metadata.get("protein") or 0) * multiplier
    carbs = (metadata.get("carbs") or 0) * multiplier
    fat = (metadata.get("fat") or 0) * multiplier

    # --- Previous live-USDA-API fallback (replaced by the metadata-based
    # math above, now that serving_size_g is stored at embed time). Left here
    # commented out, not deleted, in case a live lookup is ever needed again
    # (e.g. for a food that predates the serving_size_g fix, or a field this
    # embed doesn't carry yet).
    #
    # try:
    #     async with httpx.AsyncClient(timeout=10) as http_client:
    #         usda_response = await http_client.get(
    #             f"https://api.nal.usda.gov/fdc/v1/food/{fdc_id}",
    #             params={"api_key": USDA_API_KEY},
    #         )
    #         usda_response.raise_for_status()
    #         response = usda_response.json()
    #
    #     label = response.get("labelNutrients", {})
    #     if label.get("calories"):
    #         calories = label.get("calories", {}).get("value")
    #         protein = label.get("protein", {}).get("value")
    #         carbs = label.get("carbohydrates", {}).get("value")
    #         fat = label.get("fat", {}).get("value")
    #     else:
    #         serving_size = response.get("servingSize") or 100
    #         unit = response.get("servingSizeUnit", "g")
    #         if unit in ["oz", "OZ"]:
    #             serving_size *= 28.3495
    #         multiplier = serving_size / 100
    #         calories = (metadata.get("calories") or 0) * multiplier
    #         protein = (metadata.get("protein") or 0) * multiplier
    #         carbs = (metadata.get("carbs") or 0) * multiplier
    #         fat = (metadata.get("fat") or 0) * multiplier
    # except Exception as e:
    #     print(f"USDA lookup failed for fdc_id {fdc_id}: {e}")

    print(f"fdc_id: {fdc_id}, serving_size_g: {serving_size_g} (source: {serving_source}), calories: {calories}")

    household_serving_fulltext = metadata.get("household_serving_fulltext", "")
    whole_container = is_whole_container_serving(household_serving_fulltext)

    return {
        "food_name": metadata.get("name"),
        "calories": round(calories, 2),
        "protein": round(protein, 2),
        "carbs": round(carbs, 2),
        "fat": round(fat, 2),
        "serving_size_g": serving_size_g,
        "serving_source": serving_source,
        "serving_note": "This serving size represents the entire container." if whole_container else None,
        "source": "usda_rag",
    }