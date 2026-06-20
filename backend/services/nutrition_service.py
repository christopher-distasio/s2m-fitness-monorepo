import os

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pinecone import Pinecone

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY").strip()
USDA_API_KEY = os.getenv("USDA_API_KEY")
INDEX_NAME = "food-index"
EMBEDDING_MODEL = "text-embedding-3-large"
SCORE_THRESHOLD = 0.3

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)


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

    print(f"Top match: {match['metadata']['name']} — score: {match['score']}")

    # TODO: This per-request USDA call is a temporary stopgap. Serving-size
    # translation ideally belongs in the embedding/data-prep step so it's
    # baked into the stored Pinecone metadata once, instead of a live API
    # call on every lookup. It lives here for now only because re-embedding
    # costs at the moment, and for the sake of learning. When that changes, move the
    # serving-size math back to embed_foods.py / process_branded.py and drop
    # this block (and reconsider httpx as a main dependency).
    # Default to Pinecone metadata; refine with USDA data if the lookup succeeds.
    calories = metadata.get("calories")
    protein = metadata.get("protein")
    carbs = metadata.get("carbs")
    fat = metadata.get("fat")

    try:
        async with httpx.AsyncClient(timeout=10) as http_client:
            usda_response = await http_client.get(
                f"https://api.nal.usda.gov/fdc/v1/food/{fdc_id}",
                params={"api_key": USDA_API_KEY},
            )
            usda_response.raise_for_status()
            response = usda_response.json()

        label = response.get("labelNutrients", {})
        if label.get("calories"):
            calories = label.get("calories", {}).get("value")
            protein = label.get("protein", {}).get("value")
            carbs = label.get("carbohydrates", {}).get("value")
            fat = label.get("fat", {}).get("value")
        else:
            serving_size = response.get("servingSize") or 100
            unit = response.get("servingSizeUnit", "g")
            if unit in ["oz", "OZ"]:
                serving_size *= 28.3495
            multiplier = serving_size / 100
            calories = (metadata.get("calories") or 0) * multiplier
            protein = (metadata.get("protein") or 0) * multiplier
            carbs = (metadata.get("carbs") or 0) * multiplier
            fat = (metadata.get("fat") or 0) * multiplier
    except Exception as e:
        print(f"USDA lookup failed for fdc_id {fdc_id}: {e}")

    print(f"USDA fdc_id: {fdc_id}, calories: {calories}")

    return {
        "food_name": metadata["name"],
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "source": "usda_rag",
    }
