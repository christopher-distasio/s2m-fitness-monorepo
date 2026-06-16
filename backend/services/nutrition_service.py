import os

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pinecone import Pinecone

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
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
    return {
        "food_name": metadata["name"],
        "calories": metadata["calories"],
        "protein": metadata["protein"],
        "carbs": metadata["carbs"],
        "fat": metadata["fat"],
        "source": "usda_rag",
    }
