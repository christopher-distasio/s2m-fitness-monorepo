"""
SR Legacy + FNDDS allergen extraction -- text scan + GPT-4o-mini semantic
inference, combined.

Text scanning alone misses indirect cases: "Cheese, cheddar" doesn't contain
the word "milk"; "Tofu, raw, firm" doesn't contain "soy"; "Pasta, cooked,
enriched" doesn't contain "wheat". GPT's food knowledge catches these.

SAFETY DESIGN (unchanged from the rest of this project):
  - GPT can only ever ADD a CONTAINS determination, never assert FREE.
  - A record is CONTAINS if EITHER the text scan OR GPT says so (belt and
    suspenders -- either signal is enough to flag it).
  - Anything neither approach flags stays UNKNOWN, same as before.
  - FREE is never asserted anywhere in this script -- consistent with the
    existing rule that FREE only ever comes from an explicit ingredient
    statement, which these two datasets don't have.

Cost: confirmed against current OpenAI pricing (GPT-4o-mini, $0.15/M input,
$0.60/M output) -- ~13,225 records, batched 20-per-call, estimated under $2
total for the full run. Negligible, not a factor in any decision here.

Uses the same proven ID-resolve-then-write Qdrant pattern as the other
allergen extraction scripts in this project.

PASTA/NOODLE WHEAT FIX (2026-08-09): spot-check of the first full run found
41/113 pasta or noodle records left UNKNOWN for wheat (e.g. "Macaroni or
pasta salad", "Beef, noodles, and vegetables..."). The prompt already had a
"Pasta, cooked, enriched -> wheat" example but GPT still under-flagged dish
names that don't literally contain "pasta" (macaroni, noodles). Prompt
strengthened below with explicit examples and a default-to-wheat rule for
pasta/macaroni/noodle dishes. This run also picks up the text-scan-side fix
in allergen_extraction_logic.py (dish-name wheat terms added there), so the
gap is closed at both layers -- re-running is safe since payload writes are
idempotent.
"""
import pandas as pd
import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from allergen_extraction_logic import scan_ingredients_for_terms, ALLERGEN_TERMS

load_dotenv()

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"
OPENAI_MODEL = "gpt-4o-mini"

DATASETS = {
    "SR Legacy": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    "FNDDS": "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv",
}

QDRANT_BATCH_SIZE = 200
GPT_BATCH_SIZE = 20  # foods per GPT call -- balances prompt clarity vs. call count

TEST_MODE = False
TEST_LIMIT = 50

ALLERGEN_LIST = list(ALLERGEN_TERMS.keys())  # ["milk", "egg", "fish", "shellfish", "tree_nut", "peanut", "wheat", "soy", "sesame"]

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

GPT_SYSTEM_PROMPT = f"""You are checking whether food descriptions inherently contain any of these 9 allergens, based on general food knowledge -- NOT just literal words in the description.

Examples of what you should catch: "Cheese, cheddar" contains milk. "Tofu, raw, firm" contains soy. "Pasta, cooked, enriched" contains wheat. "Mayonnaise" contains egg. "Macaroni salad" contains wheat. "Beef and noodles with gravy" contains wheat. "Shrimp and noodles" contains wheat and shellfish.

Any dish named "pasta", "macaroni", or "noodles" contains wheat by default -- unless the description explicitly names a non-wheat base (e.g. "rice noodles", "mung bean noodles", "chickpea pasta", "gluten-free"). Spaghetti squash is a vegetable, not pasta, and does not contain wheat.

Allergens to check: {', '.join(ALLERGEN_LIST)}

For each food, return ONLY the allergens you are confident it inherently contains. If uncertain, leave it out -- do not guess. Never say a food is "free" of anything; only report what it likely CONTAINS.

Return a JSON object with this exact shape:
{{
  "results": [
    {{"index": 0, "contains": ["milk", "wheat"]}},
    {{"index": 1, "contains": []}},
    ...
  ]
}}
One entry per food, in the same order given, using the food's index number."""


def gpt_infer_allergens_batch(descriptions: list[str]) -> tuple[dict[int, set[str]], bool]:
    """
    Send a batch of food descriptions to GPT-4o-mini, get back which
    allergens each one likely contains (semantic inference, not text match).
    Returns ({index: set(allergen_names)}, success_flag). On any parsing/API
    failure, returns ({}, False) -- fails safe to "no GPT signal" for this
    batch (records fall back to scan-only, landing on UNKNOWN for anything
    scan alone can't catch -- the safe direction to fail, per the existing
    severity design). success_flag lets the caller log exactly which fdc_ids
    were affected, so a targeted patch run is possible later.
    """
    numbered = "\n".join(f"{i}: {desc}" for i, desc in enumerate(descriptions))
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": GPT_SYSTEM_PROMPT},
                {"role": "user", "content": numbered},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        parsed = json.loads(response.choices[0].message.content)
        result = {}
        for entry in parsed.get("results", []):
            idx = entry.get("index")
            contains = set(entry.get("contains", []))
            contains = contains & set(ALLERGEN_LIST)
            if idx is not None:
                result[idx] = contains
        return result, True
    except Exception as e:
        print(f"\n  [GPT batch failed, falling back to scan-only for this batch: {e}]")
        return {}, False


def build_payload_for_description(description: str, gpt_contains: set[str]) -> dict:
    """
    Combine text-scan CONTAINS with GPT-inferred CONTAINS. Either signal is
    enough to flag CONTAINS. Never asserts FREE.
    """
    scan_found = scan_ingredients_for_terms(description or "")
    combined_contains = scan_found | gpt_contains

    payload = {}
    for allergen in ALLERGEN_LIST:
        payload[allergen] = "CONTAINS" if allergen in combined_contains else "UNKNOWN"
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
    print(f"GPT_BATCH_SIZE: {GPT_BATCH_SIZE}  QDRANT_BATCH_SIZE: {QDRANT_BATCH_SIZE}\n")

    total_processed = 0
    total_updated = 0
    total_not_found = 0
    total_gpt_added = 0  # count of allergen flags GPT added that scan missed
    failed_gpt_fdc_ids = []  # fdc_ids affected by a failed GPT batch -- for later targeted re-run

    qdrant_fdc_ids = []
    qdrant_payloads = {}

    for dataset_label, csv_path in DATASETS.items():
        print(f"\n--- Processing {dataset_label} ---")
        df = pd.read_csv(csv_path, usecols=["fdc_id", "description"], low_memory=False)

        if TEST_MODE:
            df = df.head(TEST_LIMIT)

        # Process in GPT_BATCH_SIZE chunks
        for start in range(0, len(df), GPT_BATCH_SIZE):
            chunk = df.iloc[start:start + GPT_BATCH_SIZE]
            descriptions = [d if pd.notna(d) else "" for d in chunk["description"].tolist()]

            gpt_results, gpt_success = gpt_infer_allergens_batch(descriptions)
            if not gpt_success:
                failed_gpt_fdc_ids.extend(chunk["fdc_id"].tolist())

            for i, (_, row) in enumerate(chunk.iterrows()):
                total_processed += 1
                fdc_id = row["fdc_id"]
                description = row["description"] if pd.notna(row["description"]) else ""

                scan_found = scan_ingredients_for_terms(description)
                gpt_found = gpt_results.get(i, set())
                newly_added_by_gpt = gpt_found - scan_found
                total_gpt_added += len(newly_added_by_gpt)

                payload = build_payload_for_description(description, gpt_found)
                qdrant_fdc_ids.append(fdc_id)
                qdrant_payloads[str(fdc_id)] = payload

                if len(qdrant_fdc_ids) >= QDRANT_BATCH_SIZE:
                    id_map = resolve_point_ids(client, qdrant_fdc_ids)
                    pairs = [(pid, qdrant_payloads[fs]) for fs, pid in id_map.items()]
                    total_not_found += len(qdrant_fdc_ids) - len(pairs)
                    if pairs:
                        write_batch(client, pairs)
                    total_updated += len(pairs)
                    print(f"Updated {total_updated:,} / processed {total_processed:,} "
                          f"(not found: {total_not_found}, GPT added {total_gpt_added} extra flags)",end="\r")
                    qdrant_fdc_ids = []
                    qdrant_payloads = {}

    # flush remaining
    if qdrant_fdc_ids:
        id_map = resolve_point_ids(client, qdrant_fdc_ids)
        pairs = [(pid, qdrant_payloads[fs]) for fs, pid in id_map.items()]
        total_not_found += len(qdrant_fdc_ids) - len(pairs)
        if pairs:
            write_batch(client, pairs)
        total_updated += len(pairs)

    print(f"\n\n✅ Extraction complete.")
    print(f"Total processed: {total_processed:,}")
    print(f"Total records updated: {total_updated:,}")
    print(f"Total not found in Qdrant: {total_not_found:,}")
    print(f"Total allergen flags added by GPT that text-scan alone would have missed: {total_gpt_added:,}")

    if failed_gpt_fdc_ids:
        print(f"\n⚠️  {len(failed_gpt_fdc_ids)} records fell back to scan-only due to a failed GPT batch.")
        print(f"   These landed on UNKNOWN for any allergen only GPT could have caught (safe direction,")
        print(f"   but incomplete). Affected fdc_ids saved for a targeted re-run:")
        with open("diagnostic/failed_gpt_batch_fdc_ids.txt", "w") as f:
            f.write("\n".join(str(fid) for fid in failed_gpt_fdc_ids))
        print(f"   -> diagnostic/failed_gpt_batch_fdc_ids.txt ({len(failed_gpt_fdc_ids)} ids)")

    if TEST_MODE:
        print(f"\nTEST_MODE was on -- only {TEST_LIMIT} records per dataset were updated.")
        print("Spot-check a few results (especially ones where GPT added a flag scan missed),")
        print("then set TEST_MODE = False for the full run.")


if __name__ == "__main__":
    main()