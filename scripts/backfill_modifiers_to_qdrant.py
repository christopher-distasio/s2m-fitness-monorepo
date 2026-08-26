"""
Backfill USDA-style query modifiers onto food-vectors payloads.

Read-only unless --write. Writes only non-NONE modifier values, plus
literal lactose_free / dairy_free claims and modifier_provenance.
Never writes the dataset-origin `source` field.

Usage:
    poetry run python scripts/backfill_modifiers_to_qdrant.py --dry-run
    poetry run python scripts/backfill_modifiers_to_qdrant.py --write
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

from extract_modifiers_fndds import extract_modifiers as extract_fndds
from extract_modifiers_sr_legacy import extract_modifiers as extract_sr
from backend.services.modifier_extract import NONE_VALUE, extract_literal_diet_claims

load_dotenv(_REPO / ".env")

COLLECTION = "food-vectors"
BATCH_SIZE = 100
PROVENANCE = {
    "sr_legacy": "usda_extractor",
    "fndds": "usda_extractor",
    "branded_foods": "branded_text_heuristic",
}


def build_payload(description: str, dataset_source: str) -> dict:
    if (dataset_source or "") == "fndds":
        mods = extract_fndds(description)
    else:
        mods = extract_sr(description)
    payload = {k: v for k, v in mods.items() if v and v != NONE_VALUE}
    payload.update(extract_literal_diet_claims(description or ""))
    if not payload:
        return {}
    payload["modifier_provenance"] = PROVENANCE.get(dataset_source, "branded_text_heuristic")
    return payload


def flush_writes(client: QdrantClient, pairs: list, totals: dict) -> None:
    if not pairs:
        return
    ops = [
        models.SetPayloadOperation(
            set_payload=models.SetPayload(payload=payload, points=[point_id])
        )
        for point_id, payload in pairs
    ]
    client.batch_update_points(
        collection_name=COLLECTION, update_operations=ops, wait=False
    )
    totals["points_written"] += len(pairs)
    pairs.clear()


def run(url: str, write: bool, sample_per_source: int) -> None:
    client = QdrantClient(url=url, timeout=120)
    scanned = 0
    would_write = 0
    empty = 0
    by_source = defaultdict(lambda: {"scanned": 0, "write": 0, "empty": 0})
    field_counts = Counter()
    samples = defaultdict(list)
    pending: list = []
    totals = {"points_written": 0}

    offset = None
    t0 = time.time()
    print(f"{'WRITE' if write else 'DRY-RUN'}  {url}  collection={COLLECTION}")

    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION,
            limit=256,
            offset=offset,
            with_payload=["qdrant_id", "source", "description"],
            with_vectors=False,
        )
        if not points:
            break
        for point in points:
            scanned += 1
            src = point.payload.get("source") or "unknown"
            by_source[src]["scanned"] += 1
            desc = point.payload.get("description") or ""
            payload = build_payload(desc, src)
            if not payload:
                empty += 1
                by_source[src]["empty"] += 1
                continue
            would_write += 1
            by_source[src]["write"] += 1
            for key in payload:
                if key != "modifier_provenance":
                    field_counts[key] += 1
            if len(samples[src]) < sample_per_source:
                samples[src].append(
                    {
                        "qdrant_id": point.payload.get("qdrant_id"),
                        "description": desc[:120],
                        "payload": payload,
                    }
                )
            if write:
                pending.append((point.id, payload))
                if len(pending) >= BATCH_SIZE:
                    flush_writes(client, pending, totals)
        if scanned % 200000 < 256:
            print(
                f"  scanned {scanned:,} would_write {would_write:,} "
                f"({time.time()-t0:.0f}s)",
                flush=True,
            )
        if offset is None:
            break

    if write:
        flush_writes(client, pending, totals)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s  scanned={scanned:,}")
    print(f"would_write={would_write:,}  left_empty={empty:,}  "
          f"points_written={totals['points_written']:,}")
    print("\nBy source:")
    for src in ("branded_foods", "sr_legacy", "fndds"):
        s = by_source[src]
        print(f"  {src:16} scanned={s['scanned']:,}  write={s['write']:,}  empty={s['empty']:,}")
    print("\nNon-NONE field counts (points that would receive the key):")
    for key, n in field_counts.most_common():
        print(f"  {key:24} {n:,}")
    print("\nSample payloads:")
    for src, rows in samples.items():
        print(f"  --- {src} ---")
        for row in rows[:3]:
            print(f"    {row['qdrant_id']}: {row['description']!r}")
            print(f"      {row['payload']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--sample-per-source", type=int, default=8)
    args = parser.parse_args(argv)
    if args.write and args.dry_run:
        print("Choose one of --dry-run or --write", file=sys.stderr)
        return 2
    if not args.write and not args.dry_run:
        print("Pass --dry-run or --write", file=sys.stderr)
        return 2
    run(args.url, write=args.write, sample_per_source=args.sample_per_source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
