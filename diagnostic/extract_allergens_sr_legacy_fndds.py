"""
Standalone fix: extend allergen extraction to SR Legacy + FNDDS (~13,225
records combined), which were confirmed to have 0% allergen coverage --
the original extraction only ever touched Branded Foods.

Reuses the validated logic from allergen_extraction_logic.py, applied to
each food's `description` field instead of `ingredients` (SR Legacy/FNDDS
have no ingredient list -- generic whole foods, e.g. "Chicken, broiler or
fryers, breast, meat only, cooked, grilled"). Same term-scanning, same
modifier-gating (almond milk, crab apple, etc.), same compound exclusions --
just a different, shorter source text.

Every result will be CONTAINS or UNKNOWN, never FREE -- there's no ingredient
statement to source a FREE determination from. Consistent with the existing
design (FREE only ever comes from an explicit statement).

may_contain is always False for these two datasets -- no packaging-based
cross-contamination warnings exist for raw agricultural commodities.

Uses the same proven ID-resolve-then-write pattern as extract_allergens_to_qdrant.py.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from allergen_extraction_logic import scan_ingredients_for_terms, ALLERGEN_TERMS

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

DATASETS = {
    "SR Legacy": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    "FNDDS": "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv",
}

BATCH_SIZE = 200
TEST_MODE = True
TEST_LIMIT = 50


def build_payload_for_description(description: str) -> dict:
    """
    Same three-state model as Branded Foods, but sourced from description
    text (no ingredient list available for these datasets). CONTAINS if a
    term is found via scan; otherwise UNKNOWN. FREE is never asserted here
    -- no explicit statement exists to source it from. may_contain is always
    False -- no cross-contamination warnings exist for whole/generic foods.
    """
    found = scan_ingredients_for_terms(description or "")
    payload = {}
    for allergen in ALLERGEN_TERMS.keys():
        payload[allergen] = "CONTAINS" if allergen in found else "UNKNOWN"
        payload[f"{allergen}_may_contain"] = False
    return payload


def resolve_point_ids(client: QdrantClient, fdc_ids: list) -> dict:
    str_ids = [str(f) for f in fdc_ids]
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=str_ids))]
        ),
        limit=len(str_ids),
        with_payload=["qdrant_id"],
    )
    return {point.payload["qdrant_id"]: point.id for point in result}


def write_batch(client: QdrantClient, id_payload_pairs: list) -> None:
    operations = [
        models.SetPayloadOperation(
            set_payload=models.SetPayload(payload=payload, points=[point_id])
        )
        for point_id, payload in id_payload_pairs
    ]
    client.batch_update_points(
        collection_name=COLLECTION_NAME, update_operations=operations, wait=False
    )


def main():
    client = QdrantClient(url=QDRANT_URL, timeout=60)

    print(f"Connecting to Qdrant at {QDRANT_URL}")
    print(f"TEST_MODE: {TEST_MODE}" + (f" (limit {TEST_LIMIT})" if TEST_MODE else ""))
    print(f"BATCH_SIZE: {BATCH_SIZE}\n")

    total_processed = 0
    total_updated = 0
    total_not_found = 0

    batch_fdc_ids = []
    batch_payloads = {}

    for dataset_label, csv_path in DATASETS.items():
        print(f"\n--- Processing {dataset_label} ---")
        df = pd.read_csv(csv_path, usecols=["fdc_id", "description"], low_memory=False)

        for _, row in df.iterrows():
            total_processed += 1
            fdc_id = row["fdc_id"]
            description = row["description"] if pd.notna(row["description"]) else ""

            payload = build_payload_for_description(description)
            batch_fdc_ids.append(fdc_id)
            batch_payloads[str(fdc_id)] = payload

            if len(batch_fdc_ids) >= BATCH_SIZE:
                id_map = resolve_point_ids(client, batch_fdc_ids)
                pairs = [(point_id, batch_payloads[fdc_str]) for fdc_str, point_id in id_map.items()]
                total_not_found += len(batch_fdc_ids) - len(pairs)
                if pairs:
                    write_batch(client, pairs)
                total_updated += len(pairs)
                print(f"Updated {total_updated:,} / processed {total_processed:,} (not found: {total_not_found})", end="\r")
                batch_fdc_ids = []
                batch_payloads = {}

            if TEST_MODE and total_processed >= TEST_LIMIT:
                break
        if TEST_MODE and total_processed >= TEST_LIMIT:
            break

    # flush remaining
    if batch_fdc_ids:
        id_map = resolve_point_ids(client, batch_fdc_ids)
        pairs = [(point_id, batch_payloads[fdc_str]) for fdc_str, point_id in id_map.items()]
        total_not_found += len(batch_fdc_ids) - len(pairs)
        if pairs:
            write_batch(client, pairs)
        total_updated += len(pairs)

    print(f"\n\n✅ Extraction complete.")
    print(f"Total processed: {total_processed:,}")
    print(f"Total records updated: {total_updated:,}")
    print(f"Total not found in Qdrant: {total_not_found:,}")

    if TEST_MODE:
        print(f"\nTEST_MODE was on -- only {TEST_LIMIT} records were updated.")
        print("Verify a few results look right, then set TEST_MODE = False for the full run.")


if __name__ == "__main__":
    main()
