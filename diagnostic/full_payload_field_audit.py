"""
Full payload field audit -- scans a real sample from Qdrant and reports,
per field, whether it exists at all and what fraction of records have it
set to something meaningful (not missing, not "NONE").

Covers everything nutrition_service.py and query_match_rank.py actually
read, plus the full Tier 1/2 dietary schema from models.py, plus the
original 13 query modifiers built before this week's allergen work.

Run BEFORE building the re-embed/enrichment script, so it's built against
confirmed reality, not memory or a 3-record sample.
"""
from qdrant_client import QdrantClient
from collections import defaultdict

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"
SAMPLE_SIZE = 1000

client = QdrantClient(url=QDRANT_URL)

# Fields grouped by what they're for, so the report reads clearly
FIELD_GROUPS = {
    "Core nutrition/display (used by nutrition_service.py + query_match_rank.py)": [
        "description", "calories", "protein", "carbs", "fat",
        "serving_size_g", "brand_name", "brand_owner",
        "household_serving_fulltext", "portions_json",
    ],
    "Allergens (9 FDA majors + may_contain)": [
        "milk", "milk_may_contain", "egg", "egg_may_contain",
        "fish", "fish_may_contain", "shellfish", "shellfish_may_contain",
        "tree_nut", "tree_nut_may_contain", "peanut", "peanut_may_contain",
        "wheat", "wheat_may_contain", "soy", "soy_may_contain",
        "sesame", "sesame_may_contain",
    ],
    "Dietary Tier 1 non-allergen (models.py)": [
        "gluten_free", "lactose_free", "vegan", "vegetarian", "kosher", "halal",
    ],
    "Dietary Tier 2 preferences (models.py)": [
        "keto", "low_carb", "paleo", "organic", "non_gmo",
        "grass_fed", "pasture_raised", "cage_free",
    ],
    "Original 13 query modifiers (pre-allergen-work system)": [
        "cooking_method", "prep_form", "skin_status", "coating_status",
        "sodium_level", "sweetness", "fat_level", "fat_added", "fat_trim",
        "grain_type", "sauce_profile", "temperature",
        # NOTE: "source" was one of the original 13 categories in the modifier
        # system, but "source" is ALSO the separate field storing dataset
        # origin (sr_legacy/fndds/branded_foods) -- checked separately below
        # to avoid conflating the two.
    ],
    "Other confirmed-present fields": [
        "qdrant_id", "source",
    ],
}

print(f"Sampling {SAMPLE_SIZE} records from Qdrant...\n")
result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    limit=SAMPLE_SIZE,
    with_payload=True,
)
print(f"Actual sample size retrieved: {len(result)}\n")

for group_name, fields in FIELD_GROUPS.items():
    print("=" * 90)
    print(group_name)
    print("=" * 90)
    for field in fields:
        present_count = 0
        meaningful_count = 0  # present AND not None/""/"NONE"
        example_value = None
        for point in result:
            if field in point.payload:
                present_count += 1
                val = point.payload[field]
                if val not in (None, "", "NONE"):
                    meaningful_count += 1
                    if example_value is None:
                        example_value = val
        present_pct = 100 * present_count / len(result) if result else 0
        meaningful_pct = 100 * meaningful_count / len(result) if result else 0
        status = "OK" if present_count == len(result) else ("PARTIAL" if present_count > 0 else "MISSING")
        example_str = f" | example: {str(example_value)[:40]}" if example_value is not None else ""
        print(f"  [{status:7}] {field:32} present={present_pct:5.1f}%  meaningful={meaningful_pct:5.1f}%{example_str}")
    print()

print("=" * 90)
print("SUMMARY")
print("=" * 90)
print("OK      = field exists on every sampled record")
print("PARTIAL = field exists on some but not all sampled records (worth investigating why)")
print("MISSING = field never appears in the sample -- confirms it needs to be added")