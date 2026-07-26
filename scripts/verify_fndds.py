"""
Quick check that the FNDDS test batch landed in Pinecone correctly.
Run from repo root: poetry run python scripts/verify_fndds.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index("food-index")

# Check namespace stats
stats = index.describe_index_stats()
print("Namespaces:", stats.namespaces)

# Fetch a few sample vectors by known ID pattern
# (fdc_id values will differ - just grabbing whatever landed)
import random
sample = index.query(
    vector=[random.random() for _ in range(3072)],
    top_k=5,
    namespace="fndds",
    include_metadata=True,
)

for match in sample.matches:
    print("---")
    print("id:", match.id)
    print("metadata:", match.metadata)
