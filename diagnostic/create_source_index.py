"""
Create a payload index on 'source' -- this field is filtered on constantly
(SOURCE_GROUPS in nutrition_service.py, plus diagnostic scripts like this
week's allergen-coverage check) but, unlike qdrant_id, was never explicitly
indexed. Without an index, filtering for a rare value like 'sr_legacy'
(~7,800 of ~2M records) requires a full collection scan -- exactly what
caused the ReadTimeout on the previous check.
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

print("Creating payload index on 'source'...")
client.create_payload_index(
    collection_name=COLLECTION_NAME,
    field_name="source",
    field_schema=models.PayloadSchemaType.KEYWORD,
)
print("✅ Index created. Filtering on 'source' should now be fast (indexed lookup, not a full scan).")
