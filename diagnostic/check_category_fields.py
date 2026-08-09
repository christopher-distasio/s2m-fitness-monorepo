"""
Queue item 4: confirm whether wweia_food_category (FNDDS) and
branded_food_category (Branded Foods) are present in the Qdrant payload.

Neither was part of the original embed script's payload (qdrant_id,
description, source, modifiers only) -- checking to confirm before deciding
whether/how to add them during the real enrichment build.
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"
SAMPLE_SIZE = 300

client = QdrantClient(url=QDRANT_URL)

result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    limit=SAMPLE_SIZE,
    with_payload=True,
)

has_wweia = sum(1 for p in result if "wweia_food_category" in p.payload)
has_branded_cat = sum(1 for p in result if "branded_food_category" in p.payload)

print(f"Sample size: {len(result)}")
print(f"Records with 'wweia_food_category': {has_wweia} ({100*has_wweia/len(result):.1f}%)")
print(f"Records with 'branded_food_category': {has_branded_cat} ({100*has_branded_cat/len(result):.1f}%)")

# Sample is likely dominated by branded_foods (2M of ~2.02M total records),
# so also specifically try to find an FNDDS or sr_legacy record to check
# wweia_food_category against, since a general random sample may contain zero.
non_branded = [p for p in result if p.payload.get("source") != "branded_foods"]
print(f"\nNon-branded_foods records in this sample: {len(non_branded)}")
if non_branded:
    example = non_branded[0]
    print(f"Example non-branded record source: {example.payload.get('source')}")
    print(f"Its keys: {sorted(example.payload.keys())}")
else:
    print("(none in this random sample -- expected, since sr_legacy/fndds are "
          "~13k of ~2.02M total, roughly 0.6% of the collection)")
