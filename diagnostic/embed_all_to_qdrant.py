"""
Re-embed all food datasets (SR Legacy, FNDDS, Branded Foods) directly to Qdrant.

Loads descriptions, embeds via OpenAI, extracts modifiers, upserts to Qdrant.
Supports resume on interrupt via RESUME_OFFSET.

Runtime: ~6-8 hours for 474k records
"""

import os
import json
import csv
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import sys

# Import modifier extractor (same as in extract_modifiers_branded.py)
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

# ============================================================================
# CONFIG
# ============================================================================

QDRANT_URL = "http://192.168.1.227:6333"
QDRANT_API_KEY = None
COLLECTION_NAME = "food-vectors"
VECTOR_DIM = 3072  # text-embedding-3-large

EMBEDDING_MODEL = "text-embedding-3-large"
BATCH_SIZE = 100  # Vectors per API call
UPSERT_BATCH = 200  # Points per Qdrant upsert

RESUME_OFFSET = 0  # Set to resume from a specific record number
TEST_MODE = False
TEST_LIMIT = 50

# Dataset paths
DATASETS = [
    {
        "name": "SR Legacy",
        "path": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
        "columns": {"id": "fdc_id", "description": "description"},
    },
    {
        "name": "FNDDS",
        "path": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
        "columns": {"id": "fdc_id", "description": "description"},
    },
    {
        "name": "Branded Foods",
        "path": "data/raw/FoodData_Central_branded_food_csv_2026-04-30/food.csv",
        "columns": {"id": "fdc_id", "description": "description"},
    },
]

# ============================================================================
# MODIFIER EXTRACTION (inline, simplified)
# ============================================================================

MODIFIER_PATTERNS = {
    "vegan": [r"\bvegan\b"],
    "vegetarian": [r"\bvegetarian\b"],
    "kosher": [r"\bkosher\b"],
    "halal": [r"\bhalal\b"],
    "gluten_free": ["gluten-?free", "gluten free"],
    "organic": [r"\borganic\b"],
    "keto": [r"\bketo\b"],
}

def extract_modifiers(description: str) -> dict:
    """Quick modifier extraction."""
    import re
    desc_lower = (description or "").lower()
    modifiers = {}
    for mod_name, patterns in MODIFIER_PATTERNS.items():
        found = False
        for pattern in patterns:
            try:
                if re.search(pattern, desc_lower, re.IGNORECASE):
                    found = True
                    break
            except:
                pass
        modifiers[mod_name] = mod_name if found else "NONE"
    return modifiers

# ============================================================================
# MAIN
# ============================================================================

def load_all_records():
    """Load all descriptions from all datasets."""
    records = []
    
    for dataset in DATASETS:
        path = dataset["path"]
        if not os.path.exists(path):
            print(f"⚠️  Dataset not found: {path}")
            continue
        
        print(f"Loading {dataset['name']}...")
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    record = {
                        "id": row[dataset["columns"]["id"]],
                        "description": row[dataset["columns"]["description"]],
                        "source": dataset["name"].lower().replace(" ", "_"),
                    }
                    records.append(record)
                except KeyError:
                    continue
        
        print(f"  ✓ Loaded {len([r for r in records if r['source'] == dataset['name'].lower().replace(' ', '_')])} records")
    
    return records


def main():
    # Connect to Qdrant
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    
    print(f"Connecting to Qdrant at {QDRANT_URL}")
    print(f"Loading datasets...\n")
    
    # Load all records
    all_records = load_all_records()
    
    if TEST_MODE:
        all_records = all_records[:TEST_LIMIT]
    
    total_records = len(all_records)
    print(f"\nTotal records to embed: {total_records:,}")
    
    # Apply resume offset
    records = all_records[RESUME_OFFSET:]
    print(f"Starting from offset: {RESUME_OFFSET}")
    print(f"Records to process: {len(records):,}\n")
    
    # Create collection if not exists
    try:
        client.get_collection(COLLECTION_NAME)
        print(f"Collection '{COLLECTION_NAME}' already exists\n")
    except:
        print(f"Creating collection '{COLLECTION_NAME}'...")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
        print()
    
    # Embed and upsert in batches
    points_batch = []
    embedded_count = 0
    
    for batch_start in range(0, len(records), BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, len(records))
        batch_records = records[batch_start:batch_end]
        
        # Extract descriptions for embedding
        descriptions = [r["description"] for r in batch_records]
        
        # Embed via OpenAI
        print(f"Embedding batch {batch_start // BATCH_SIZE + 1}: {len(descriptions)} records...", end='')
        try:
            embeddings = openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=descriptions
            )
            print(f" ✓")
        except Exception as e:
            print(f" ✗ Error: {e}")
            continue
        
        # Build PointStruct for each record
        for i, record in enumerate(batch_records):
            embedding = embeddings.data[i].embedding
            modifiers = extract_modifiers(record["description"])
            
            point = PointStruct(
                id=hash(record["id"]) & ((1 << 63) - 1),
                vector=embedding,
                payload={
                    "qdrant_id": record["id"],
                    "description": record["description"],
                    "source": record["source"],
                    **modifiers
                }
            )
            points_batch.append(point)
            embedded_count += 1
            
            # Upsert when batch is full
            if len(points_batch) >= UPSERT_BATCH or embedded_count == len(records):
                print(f"  Upserting {len(points_batch)} points to Qdrant...", end='')
                try:
                    client.upsert(
                        collection_name=COLLECTION_NAME,
                        points=points_batch
                    )
                    print(f" ✓ (total: {RESUME_OFFSET + embedded_count:,})")
                except Exception as e:
                    print(f" ✗ Error: {e}")
                points_batch = []
    
    # Final stats
    print(f"\n✅ Embedding complete!")
    collection_info = client.get_collection(COLLECTION_NAME)
    print(f"Collection '{COLLECTION_NAME}' now has {collection_info.points_count:,} vectors")


if __name__ == "__main__":
    main()