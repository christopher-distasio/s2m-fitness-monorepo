"""
Import vectors from Pinecone export JSON into Qdrant.
"""

import json
import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

PINECONE_EXPORT = "diagnostic/pinecone_export.json"
QDRANT_URL = "http://192.168.1.227:6333"
QDRANT_API_KEY = None  # Set if you added one to docker-compose.yml
COLLECTION_NAME = "food-vectors"
VECTOR_DIM = 3072  # text-embedding-3-large dimension

def main():
    # Connect to Qdrant
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    
    print(f"Connecting to Qdrant at {QDRANT_URL}")
    print(f"Loading vectors from: {PINECONE_EXPORT}\n")
    
    # Create collection if it doesn't exist
    try:
        client.get_collection(COLLECTION_NAME)
        print(f"Collection '{COLLECTION_NAME}' already exists")
    except:
        print(f"Creating collection '{COLLECTION_NAME}'...")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
    
    # Load JSON and upsert
    print(f"\nLoading vectors from JSON...")
    with open(PINECONE_EXPORT, 'r') as f:
        vectors = json.load(f)
    
    print(f"Total vectors to import: {len(vectors):,}")
    
    # Convert to PointStruct for Qdrant
    points = []
    for i, vector_data in enumerate(vectors):
        point = PointStruct(
            id=hash(vector_data["id"]) & ((1 << 63) - 1),  # Convert string ID to int
            vector=vector_data["values"],
            payload={"qdrant_id": vector_data["id"], **vector_data.get("metadata", {})}
        )
        points.append(point)
        
        # Batch upsert every 1000 points
        if len(points) >= 1000 or i == len(vectors) - 1:
            print(f"Upserting {len(points)} points... ({i+1}/{len(vectors)})", end='\r')
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )
            points = []
    
    print(f"\n✅ Import complete!")
    
    # Verify
    collection_info = client.get_collection(COLLECTION_NAME)
    print(f"Collection '{COLLECTION_NAME}' now has {collection_info.points_count:,} vectors")


if __name__ == "__main__":
    main()
