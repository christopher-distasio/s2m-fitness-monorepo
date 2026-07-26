"""
Direct check: what does the McDonald's Cheeseburger vector's metadata
actually say for "source"? If it's not "usda_branded_foods", that's the bug.

Run from repo root: poetry run python scripts/check_mcdonalds_source.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index("food-index")
client = OpenAI()

# Re-run the same query "cheeseburger" with NO filter, to surface the same
# McDonald's match you saw, then print its raw metadata.
resp = client.embeddings.create(model="text-embedding-3-large", input="cheeseburger")
vector = resp.data[0].embedding

results = index.query(vector=vector, top_k=10, include_metadata=True)

for match in results.matches:
    md = match.metadata or {}
    print("---")
    print("id:", match.id)
    print("description:", md.get("description") or md.get("name"))
    print("source field value:", md.get("source"))
    print("data_type field value:", md.get("data_type"))
    print("full metadata:", md)