"""
A/B: top-1 result for the 230 realistic queries, SEARCH_MODE=dense vs hybrid.

Read-only. Same path as diagnostic/top1_triage.csv (commit faa599e): live
lookup_food, modifiers from parse_query_modifiers, no stated brand, no
dietary profile. Dense reads food-vectors at QDRANT_URL; hybrid reads
food-vectors-hybrid at HYBRID_QDRANT_URL.

    HYBRID_QDRANT_URL=http://192.168.1.236:6333 \
        poetry run python diagnostic/ab_hybrid_top1.py

Writes diagnostic/ab_hybrid_top1.csv (one row per query) and prints every
query whose top-1 changed.
"""
import asyncio
import contextlib
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.services.nutrition_service as ns  # noqa: E402
from backend.services.parse_query_modifiers import parse_query_modifiers  # noqa: E402

HERE = os.path.dirname(__file__)
QUERIES = os.path.join(HERE, "realistic_food_queries.json")
OUT = os.path.join(HERE, "ab_hybrid_top1.csv")

_picked = {}
_original_pick = ns._pick_match_with_usable_calories


def _recording_pick(query, matches):
    match = _original_pick(query, matches)
    _picked["match"] = match
    return match


ns._pick_match_with_usable_calories = _recording_pick


async def top1(query: str, mode: str) -> dict:
    ns.SEARCH_MODE = mode
    _picked.clear()
    with contextlib.redirect_stdout(io.StringIO()):  # lookup_food prints a lot
        result = await ns.lookup_food(query, modifiers=parse_query_modifiers(query))
    m = _picked.get("match") or {}
    meta = m.get("metadata") or {}
    return {
        "fdc_id": m.get("id") or "",
        "description": meta.get("description") or "",
        "brand": (result or {}).get("brand") or "",
        "calories": (result or {}).get("calories"),
        "bm25": m.get("bm25_score", ""),
    }


async def main():
    with open(QUERIES) as f:
        queries = json.load(f)["realistic_queries"]
    rows, changed = [], 0
    for i, q in enumerate(queries, 1):
        d = await top1(q, "dense")
        h = await top1(q, "hybrid")
        diff = d["fdc_id"] != h["fdc_id"]
        changed += diff
        rows.append({
            "query": q, "changed": diff,
            **{f"dense_{k}": v for k, v in d.items() if k != "bm25"},
            **{f"hybrid_{k}": v for k, v in h.items()},
        })
        if diff:
            print(f"[{i}] {q!r}\n    dense : {d['description']} | {d['brand']} | {d['calories']} kcal"
                  f"\n    hybrid: {h['description']} | {h['brand']} | {h['calories']} kcal", flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n{changed} of {len(queries)} top-1 results changed. Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
