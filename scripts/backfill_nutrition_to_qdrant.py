"""
Backfill nutrition + metadata payloads into the existing Qdrant food-vectors
collection. Payload-only — no re-embedding, no new points.

Reads the three cleaned JSON outputs:
  - data/processed/branded_clean.json
  - data/processed/sr_legacy_full_clean.json
  - data/processed/fndds_clean.json

Resolves real point IDs via scroll() + MatchAny on qdrant_id, then
batch_update_points with SetPayloadOperation. Over-fetches/paginates so
duplicate qdrant_id copies (common in branded_foods) cannot starve the
batch limit and look like "not found". Writes payload to every duplicate
point. Never touches allergen or dietary-tag fields.

Run from repo root:
    poetry run python scripts/backfill_nutrition_to_qdrant.py

Ask before flipping TEST_MODE=False for the full ~2M run.
"""

import json
import time
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROCESSED = _REPO_ROOT / "data" / "processed"

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"
BATCH_SIZE = 200

TEST_MODE = False
TEST_LIMIT = 50  # per source file in TEST_MODE

# Extra fdc_ids always included in TEST_MODE so spot-checks cover sugar /
# provenance / FNDDS category cases (not just the first N CSV-order rows).
TEST_SPOTCHECK_IDS = {
    "branded_foods": [
        "1107490",  # soft peppermint candy — sugar≈100
        "1106143",  # vitamin_d converted_from_iu (iu=164 → 4.1 mcg)
        "1106101",  # folate fallback_from_total
        "1847371",  # vitamin_d measured_mcg (Hershey bar)
        "2554935",  # vitamin_a measured_rae
    ],
    "sr_legacy": [],
    "fndds": [
        "2705385",  # additional_description=leche fresca, wweia=Milk, whole
        "2705394",  # additional_description multi-value (Kefir)
    ],
}

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

# Keys already present on live points that must never be overwritten.
PRESERVE_KEYS = {
    "description",
    "source",
    "qdrant_id",
    # allergens
    "milk", "egg", "fish", "shellfish", "tree_nut", "peanut", "wheat", "soy", "sesame",
    "milk_may_contain", "egg_may_contain", "fish_may_contain", "shellfish_may_contain",
    "tree_nut_may_contain", "peanut_may_contain", "wheat_may_contain", "soy_may_contain",
    "sesame_may_contain",
    # dietary tags
    "vegan", "vegetarian", "kosher", "halal", "gluten_free", "organic", "keto",
}

SOURCE_FILES = [
    ("branded_foods", _PROCESSED / "branded_clean.json"),
    ("sr_legacy", _PROCESSED / "sr_legacy_full_clean.json"),
    ("fndds", _PROCESSED / "fndds_clean.json"),
]


def call_with_retry(func, *args, **kwargs):
    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < MAX_RETRIES:
                print(
                    f"\n  [retry {attempt}/{MAX_RETRIES}] {type(e).__name__}, "
                    f"waiting {RETRY_DELAY_SECONDS}s..."
                )
                time.sleep(RETRY_DELAY_SECONDS)
    raise last_exception


def build_payload(food: dict) -> dict:
    """
    Nutrition/metadata only. Skips preserve keys so we never clobber
    allergens/dietary tags.

    None values are normally omitted, EXCEPT preferred micronutrient fields
    that provenance explicitly cleared (so a full re-backfill can overwrite
    stale non-null values written by the previous schema).
    """
    force_null_keys = set()
    if food.get("vitamin_a_source") in ("unsupported_conversion", "no_data"):
        force_null_keys.add("vitamin_a_rae_mcg")
    if food.get("folate_source") == "no_data":
        force_null_keys.add("folate_dfe_mcg")
    if food.get("vitamin_d_source") == "no_data":
        force_null_keys.add("vitamin_d_mcg")

    payload = {}
    for key, value in food.items():
        if key in PRESERVE_KEYS:
            continue
        if value is None and key not in force_null_keys:
            continue
        if key == "fdc_id":
            payload[key] = str(value)
        else:
            payload[key] = value

    for key in force_null_keys:
        payload[key] = None
    return payload


def resolve_point_ids(client: QdrantClient, fdc_ids: list) -> dict:
    """
    Resolve qdrant_id -> ALL matching point IDs via MatchAny scroll.

    Critical: many branded_foods qdrant_ids have duplicate points (2+ copies).
    A single scroll with limit=len(batch) returns duplicate copies of some IDs
    and silently drops others that DO exist — that caused fake "not found"
    rates (~28% on branded). We over-fetch and paginate with a stable filter
    until every requested ID is collected (or results are exhausted), and
    return every point ID so payload updates hit all copies.

    Returns: {fdc_id_str: [point_id, ...]}
    """
    str_ids = [str(f) for f in fdc_ids]
    wanted = set(str_ids)
    found: dict[str, list] = {}
    offset = None
    # Over-fetch: this collection commonly has 2 points per qdrant_id.
    page_limit = max(len(str_ids) * 3, BATCH_SIZE)

    while True:
        result, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="qdrant_id",
                        match=models.MatchAny(any=str_ids),
                    )
                ]
            ),
            limit=page_limit,
            offset=offset,
            with_payload=["qdrant_id"],
        )
        if not result:
            break

        for point in result:
            qid = str(point.payload["qdrant_id"])
            if qid not in wanted:
                continue
            bucket = found.setdefault(qid, [])
            if point.id not in bucket:
                bucket.append(point.id)

        if wanted.issubset(found.keys()):
            break
        if next_offset is None:
            break
        offset = next_offset

    return found


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


def flush_batch(client, batch_fdc_ids, batch_payloads, totals):
    if not batch_fdc_ids:
        return
    id_map = call_with_retry(resolve_point_ids, client, batch_fdc_ids)
    # One SetPayload per physical point (covers duplicate qdrant_ids).
    pairs = [
        (point_id, batch_payloads[fdc_str])
        for fdc_str, point_ids in id_map.items()
        for point_id in point_ids
    ]
    unique_found = len(id_map)
    totals["not_found"] += len(batch_fdc_ids) - unique_found
    totals["points_written"] += len(pairs)
    if pairs:
        call_with_retry(write_batch, client, pairs)
    totals["updated"] += unique_found
    print(
        f"Updated {totals['updated']:,} / processed {totals['processed']:,} "
        f"(not found: {totals['not_found']}; points written: {totals['points_written']:,})",
        end="\r",
    )


def process_file(client, label: str, path: Path, totals: dict) -> dict:
    """Process one cleaned JSON file. Returns per-file stats."""
    print(f"\n--- {label}: {path.name} ---")
    if not path.exists():
        print(f"  MISSING FILE — skipping")
        return {"processed": 0, "updated": 0, "not_found": 0}

    with open(path, encoding="utf-8") as f:
        foods = json.load(f)

    if TEST_MODE:
        by_id = {str(f.get("fdc_id")): f for f in foods}
        selected = []
        seen = set()
        for fid in TEST_SPOTCHECK_IDS.get(label, []):
            food = by_id.get(str(fid))
            if food and str(fid) not in seen:
                selected.append(food)
                seen.add(str(fid))
        for food in foods:
            fid = str(food.get("fdc_id"))
            if fid in seen:
                continue
            selected.append(food)
            seen.add(fid)
            if len(selected) >= TEST_LIMIT + len(TEST_SPOTCHECK_IDS.get(label, [])):
                break
        # Cap: spotchecks + first TEST_LIMIT others
        foods = selected[: TEST_LIMIT + len(TEST_SPOTCHECK_IDS.get(label, []))]
        print(f"  TEST_MODE: {len(foods)} records "
              f"(includes {len(TEST_SPOTCHECK_IDS.get(label, []))} spot-check IDs)")
    else:
        print(f"  Loaded {len(foods):,} records")

    file_stats = {"processed": 0, "updated": 0, "not_found": 0}
    batch_fdc_ids = []
    batch_payloads = {}

    for food in foods:
        totals["processed"] += 1
        file_stats["processed"] += 1

        fdc_id = food.get("fdc_id")
        if fdc_id is None:
            totals["not_found"] += 1
            file_stats["not_found"] += 1
            continue

        payload = build_payload(food)
        batch_fdc_ids.append(fdc_id)
        batch_payloads[str(fdc_id)] = payload

        if len(batch_fdc_ids) >= BATCH_SIZE:
            before_u, before_n = totals["updated"], totals["not_found"]
            flush_batch(client, batch_fdc_ids, batch_payloads, totals)
            file_stats["updated"] += totals["updated"] - before_u
            file_stats["not_found"] += totals["not_found"] - before_n
            batch_fdc_ids = []
            batch_payloads = {}

    if batch_fdc_ids:
        before_u, before_n = totals["updated"], totals["not_found"]
        flush_batch(client, batch_fdc_ids, batch_payloads, totals)
        file_stats["updated"] += totals["updated"] - before_u
        file_stats["not_found"] += totals["not_found"] - before_n

    print(
        f"\n  {label} done — updated {file_stats['updated']:,} / "
        f"processed {file_stats['processed']:,} "
        f"(not found: {file_stats['not_found']:,})"
    )
    return file_stats


def main():
    client = QdrantClient(url=QDRANT_URL, timeout=60)

    print(f"Connecting to Qdrant at {QDRANT_URL}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"TEST_MODE: {TEST_MODE}" + (f" (limit {TEST_LIMIT} per source)" if TEST_MODE else ""))
    print(f"BATCH_SIZE: {BATCH_SIZE}")

    totals = {"processed": 0, "updated": 0, "not_found": 0, "points_written": 0}
    per_source = {}

    for label, path in SOURCE_FILES:
        per_source[label] = process_file(client, label, path, totals)

    print("\n\n✅ Nutrition backfill complete.")
    print(f"Total processed: {totals['processed']:,}")
    print(f"Total records updated (unique fdc_id): {totals['updated']:,}")
    print(f"Total physical points written (incl. duplicates): {totals['points_written']:,}")
    print(f"Total not found in Qdrant: {totals['not_found']:,}")
    print("\nPer source:")
    for label, stats in per_source.items():
        print(
            f"  {label}: updated {stats['updated']:,} / "
            f"processed {stats['processed']:,} "
            f"(not found: {stats['not_found']:,})"
        )

    if TEST_MODE:
        print(f"\nTEST_MODE was on — only {TEST_LIMIT} records per source were updated.")
        print("Spot-check Qdrant payloads, then set TEST_MODE=False for the full run.")
        print("Do not flip TEST_MODE without explicit review approval.")


if __name__ == "__main__":
    main()
