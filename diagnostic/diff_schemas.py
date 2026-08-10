"""
Reusable schema diff tool: fetches ONE sample vector from each data source
in Pinecone and compares their metadata keys side by side. Run this any
time you add a new data source, BEFORE assuming it matches the existing
schema.

Usage: edit SAMPLE_IDS below with one known-good ID per source, then run.

Run from repo root: poetry run python scripts/diff_schemas.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index("food-index")

# One known ID per source - update these as you add new sources
SAMPLE_IDS = {
    "sr_legacy": "sr_170320",
    "branded": "2723221",
    "fndds": "fndds-2706888",
}

fetched = index.fetch(ids=list(SAMPLE_IDS.values()))

schemas = {}
for source_name, vec_id in SAMPLE_IDS.items():
    vec = fetched.vectors.get(vec_id)
    if vec is None:
        print(f"WARNING: {source_name} sample ID {vec_id} not found")
        continue
    schemas[source_name] = set((vec.metadata or {}).keys())

print("=== Key counts per source ===")
for name, keys in schemas.items():
    print(f"{name}: {len(keys)} keys")

print("\n=== Keys present in ALL sources (the safe shared schema) ===")
if schemas:
    common = set.intersection(*schemas.values())
    print(sorted(common))

print("\n=== Keys unique to each source (potential inconsistencies) ===")
for name, keys in schemas.items():
    others = set.union(*(k for n, k in schemas.items() if n != name)) if len(schemas) > 1 else set()
    unique = keys - others
    print(f"{name} only: {sorted(unique) if unique else 'none'}")