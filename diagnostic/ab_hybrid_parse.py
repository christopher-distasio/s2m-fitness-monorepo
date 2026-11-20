"""
A/B through the real app path: parse_food_input (GPT parse, stated brand,
plain-food-first, brand filter, quantity) with SEARCH_MODE=dense vs hybrid,
for the 230 realistic queries.

GPT runs once per query; its reply is cached and replayed for the second
mode, so only the search mode differs between the two rows.

    poetry run python diagnostic/ab_hybrid_parse.py

Writes diagnostic/ab_hybrid_parse.csv (resumable, one row per query).
"""
import asyncio
import contextlib
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import backend.services.food_parser as fp  # noqa: E402
import backend.services.nutrition_service as ns  # noqa: E402

HERE = os.path.dirname(__file__)
QUERIES = os.path.join(HERE, "realistic_food_queries.json")
OUT = os.path.join(HERE, "ab_hybrid_parse.csv")

_gpt_cache: dict[str, object] = {}
_real_create = fp.client.chat.completions.create


async def _cached_create(*args, **kwargs):
    key = json.dumps(kwargs.get("messages"), sort_keys=True, default=str)
    if key not in _gpt_cache:
        _gpt_cache[key] = await _real_create(*args, **kwargs)
    return _gpt_cache[key]


fp.client.chat.completions.create = _cached_create

_last = {}
_real_lookup = fp.lookup_food


async def _recording_lookup(*args, **kwargs):
    result = await _real_lookup(*args, **kwargs)
    if "counted" in kwargs:  # main / plain-first lookups, not the cup-weight reference
        _last["nutrition"] = result
    return result


fp.lookup_food = _recording_lookup


async def run(query: str, mode: str) -> dict:
    ns.SEARCH_MODE = mode
    _last.clear()
    for attempt in range(4):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                r = await fp.parse_food_input(query)
            break
        except Exception as exc:
            if attempt == 3:
                raise
            print(f"    retry {attempt + 1} after {type(exc).__name__}", file=sys.stderr, flush=True)
            await asyncio.sleep(15 * (attempt + 1))
    n = _last.get("nutrition") or {}
    return {
        "name": n.get("food_name") or "",
        "brand": r.get("brand") or "",
        "calories": r.get("calories"),
        "status": (r.get("resolution") or {}).get("status") or r.get("resolution_status") or r.get("error") or "",
    }


async def main():
    with open(QUERIES) as f:
        queries = json.load(f)["realistic_queries"]
    done = {}
    if os.path.exists(OUT):
        with open(OUT, newline="") as f:
            done = {r["query"]: r for r in csv.DictReader(f)}
    fields = ["query", "changed"] + [f"{m}_{k}" for m in ("dense", "hybrid") for k in ("name", "brand", "calories", "status")]
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not done:
            w.writeheader()
        for i, q in enumerate(queries, 1):
            if q in done:
                continue
            d = await run(q, "dense")
            h = await run(q, "hybrid")
            changed = (d["name"], d["calories"]) != (h["name"], h["calories"])
            row = {"query": q, "changed": changed,
                   **{f"dense_{k}": v for k, v in d.items()}, **{f"hybrid_{k}": v for k, v in h.items()}}
            done[q] = row
            w.writerow(row)
            f.flush()
            if changed:
                print(f"[{i}] {q!r}\n    dense : {d['name']} | {d['brand']} | {d['calories']}"
                      f"\n    hybrid: {h['name']} | {h['brand']} | {h['calories']}", flush=True)
    n = sum(str(r["changed"]) == "True" for r in done.values())
    print(f"\n{n} of {len(done)} results changed. Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
