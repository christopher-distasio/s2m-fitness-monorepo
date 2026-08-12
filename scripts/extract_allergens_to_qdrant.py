"""
Full allergen extraction -- write three-state allergen data (CONTAINS/FREE/UNKNOWN)
plus per-allergen "may_contain" flags to all ~2M Branded Foods records already
embedded in Qdrant.

This is a PAYLOAD-ONLY update -- no re-embedding, no vector changes.

APPROACH (v3): resolve real point IDs first, then write by ID.

Every earlier version wrote via a Filter directly (matching qdrant_id == fdc_id
on each call). That stayed slow even after batching and wait=False -- the
likely reason is that Qdrant's payload index speeds up reads (search/scroll)
but the write-by-filter path may still evaluate the filter per-call rather
than using the index the same way. Instead:

  1. For a batch of N fdc_ids, one indexed `scroll()` call with a MatchAny
     filter resolves all N real point IDs at once.
  2. Payload updates are then sent using those exact IDs directly --
     `batch_update_points` with ID-based PointsSelector never touches the
     filter path at all, which is the fast, well-trodden case.

This is two network calls per batch (one scroll, one batched write) instead
of one filter-write call per record.

18 new payload fields per record: for each of the 9 FDA allergens,
  <allergen>              -> "CONTAINS" | "FREE" | "UNKNOWN"
  <allergen>_may_contain  -> bool (cross-contamination warning, used only for
                              severe-severity filtering, ignored for moderate)

Resume support via RESUME_OFFSET in case of interruption.
"""

import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from allergen_extraction_logic import extract_allergen_states, extract_explicit_statement, MAY_CONTAIN_PATTERN

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"
QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

CHUNK_SIZE = 5000          # rows read from CSV per chunk (memory efficiency)
BATCH_SIZE = 200           # records resolved + written per batch

RESUME_OFFSET = 0          # starting clean -- at ~78 records/sec, redoing the first 17,600 costs under 4 minutes
TEST_MODE = False          # full run
TEST_LIMIT = 200

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


def call_with_retry(func, *args, **kwargs):
    """
    Retry wrapper for Qdrant calls. A multi-hour unattended job will hit
    occasional transient slowness (Qdrant's background segment optimization,
    momentary system load) -- one timeout shouldn't kill hours of progress.
    Retries a few times with a short delay before giving up for real.
    """
    import time
    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < MAX_RETRIES:
                print(f"\n  [retry {attempt}/{MAX_RETRIES}] {type(e).__name__}, "
                      f"waiting {RETRY_DELAY_SECONDS}s...")
                time.sleep(RETRY_DELAY_SECONDS)
    raise last_exception


def build_payload_for_record(ingredients: str) -> dict:
    """
    Build the full allergen payload for one product:
    9 allergens x (state + may_contain flag) = 18 fields.
    """
    states = extract_allergen_states(ingredients)
    may_contain_set = extract_explicit_statement(ingredients or "", MAY_CONTAIN_PATTERN)

    payload = {}
    for allergen, state in states.items():
        payload[allergen] = state
        payload[f"{allergen}_may_contain"] = allergen in may_contain_set

    return payload


def resolve_point_ids(client: QdrantClient, fdc_ids: list) -> dict:
    """
    One indexed scroll() call resolves the real Qdrant point IDs for many
    fdc_ids at once, using MatchAny instead of one filter call per record.

    Returns: {fdc_id_str: point_id}
    """
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
    """
    Write payloads by direct point ID -- no filter evaluation on this path.
    id_payload_pairs: list of (point_id, payload_dict) tuples.
    """
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
    print(f"Reading from: {CSV_PATH}")
    print(f"TEST_MODE: {TEST_MODE}" + (f" (limit {TEST_LIMIT})" if TEST_MODE else ""))
    print(f"RESUME_OFFSET: {RESUME_OFFSET}")
    print(f"BATCH_SIZE: {BATCH_SIZE}\n")

    total_processed = 0
    total_updated = 0
    total_not_found = 0

    reader = pd.read_csv(
        CSV_PATH, low_memory=False, usecols=["fdc_id", "ingredients"], chunksize=CHUNK_SIZE
    )

    batch_fdc_ids = []
    batch_payloads = {}  # fdc_id_str -> payload

    stop = False
    for chunk in reader:
        if stop:
            break

        for _, row in chunk.iterrows():
            total_processed += 1

            if RESUME_OFFSET and total_processed <= RESUME_OFFSET:
                continue

            fdc_id = row["fdc_id"]
            ingredients = row["ingredients"] if pd.notna(row["ingredients"]) else ""

            payload = build_payload_for_record(ingredients)
            batch_fdc_ids.append(fdc_id)
            batch_payloads[str(fdc_id)] = payload

            if len(batch_fdc_ids) >= BATCH_SIZE:
                id_map = call_with_retry(resolve_point_ids, client, batch_fdc_ids)
                pairs = [
                    (point_id, batch_payloads[fdc_str])
                    for fdc_str, point_id in id_map.items()
                ]
                total_not_found += len(batch_fdc_ids) - len(pairs)
                if pairs:
                    call_with_retry(write_batch, client, pairs)
                total_updated += len(pairs)

                print(f"Updated {total_updated:,} / processed {total_processed:,} "
                      f"(not found: {total_not_found})", end="\r")

                batch_fdc_ids = []
                batch_payloads = {}

            if TEST_MODE and total_processed >= TEST_LIMIT:
                stop = True
                break

    # flush remaining partial batch
    if batch_fdc_ids:
        id_map = call_with_retry(resolve_point_ids, client, batch_fdc_ids)
        pairs = [(point_id, batch_payloads[fdc_str]) for fdc_str, point_id in id_map.items()]
        total_not_found += len(batch_fdc_ids) - len(pairs)
        if pairs:
            call_with_retry(write_batch, client, pairs)
        total_updated += len(pairs)

    print(f"\n\n✅ Allergen extraction complete.")
    print(f"Total processed: {total_processed:,}")
    print(f"Total records updated: {total_updated:,}")
    print(f"Total not found in Qdrant: {total_not_found:,}")

    if TEST_MODE:
        print(f"\nTEST_MODE was on -- only {TEST_LIMIT} records were updated.")
        print("Time this run. This approach avoids filter evaluation on the write")
        print("path entirely -- if it's still slow, the bottleneck is elsewhere")
        print("(Docker's filesystem layer being the next suspect).")


if __name__ == "__main__":
    main()