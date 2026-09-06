"""Atwater residual on the live lookup_food retrieval path.

EVAL_CASES has a legitimate duplicate raw_input ('a cup of black coffee':
simple parse + nutrition calorie bounds). Retrieval depends only on the
query string, so this script deduplicates by raw_input before searching.
Do not collapse that duplicate in tests/eval_food_parser.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import traceback
from collections import Counter

from backend.services.parse_query_modifiers import parse_query_modifiers
from backend.services.query_match_rank import rerank_matches_by_query
import backend.services.nutrition_service as ns
from tests.eval_food_parser import EVAL_CASES


def unique_eval_queries(cases):
    """Keep first occurrence of each raw_input. Retrieval is query-keyed."""
    seen: set[str] = set()
    unique: list = []
    dropped: list[tuple[str, str]] = []
    for case in cases:
        q = case.raw_input
        if q in seen:
            dropped.append((q, case.category))
            continue
        seen.add(q)
        unique.append(case)
    return unique, dropped


def pctile(xs, p):
    if not xs:
        return None
    ys = sorted(xs)
    if p >= 1:
        return ys[-1]
    i = int(math.floor(p * (len(ys) - 1)))
    return ys[i]


def atwater(meta):
    meta = meta or {}
    out = {
        "fdc_id": meta.get("fdc_id") or meta.get("qdrant_id"),
        "data_source": meta.get("data_source"),
        "source": meta.get("source"),
        "name": meta.get("name") or meta.get("description"),
        "stored_protein": meta.get("protein"),
        "stored_carbs": meta.get("carbs"),
        "stored_fat": meta.get("fat"),
        "stored_calories": meta.get("calories"),
        "status": None,
    }
    if any(meta.get(k) is None for k in ("calories", "protein", "carbs", "fat")):
        out["status"] = "incomplete"
        return out
    try:
        cal = float(meta["calories"])
        pro = float(meta["protein"])
        carb = float(meta["carbs"])
        fat = float(meta["fat"])
    except (TypeError, ValueError):
        out["status"] = "incomplete"
        return out
    if cal <= 0:
        out["status"] = "nonpositive_cal"
        out["computed"] = 4.0 * pro + 4.0 * carb + 9.0 * fat
        return out
    computed = 4.0 * pro + 4.0 * carb + 9.0 * fat
    rel = abs(computed - cal) / cal
    g, ssrc = ns.get_serving_size_g(meta)
    stored_serv = cal * g / 100.0
    computed_serv = computed * g / 100.0
    out.update(
        {
            "status": "ok",
            "computed": computed,
            "rel": rel,
            "serving_size_g": g,
            "serving_source": ssrc,
            "stored_kcal_serving": stored_serv,
            "computed_kcal_serving": computed_serv,
            "abs_kcal_serving": abs(computed_serv - stored_serv),
            "carbs_eq_fat": carb == fat,
            "p4c": 4.0 * pro + 4.0 * carb,
            "p4c_rel": abs((4.0 * pro + 4.0 * carb) - cal) / cal,
        }
    )
    return out


async def ranked_matches(query: str):
    modifiers = parse_query_modifiers(query)
    modifier_conditions = ns._modifiers_qdrant_conditions(modifiers)
    combined = ns._combine_filters(None, modifier_conditions, None)
    matches, variant = await ns._retrieve_best(query, combined)
    matches = rerank_matches_by_query(query, matches, modifiers)
    matches = ns.collapse_retrieval_clones(matches)
    matches = ns.filter_phantom_matches(matches)
    primary = ns._pick_match_with_usable_calories(query, matches)
    if primary is None or primary.get("score", 0) < ns.SCORE_THRESHOLD:
        return {"query": query, "returned": False, "variant": variant, "ordered": []}
    rest = [m for m in matches if m.get("id") != primary.get("id")]
    ordered = [primary] + rest
    packed = []
    for i, m in enumerate(ordered[:5], start=1):
        meta = m.get("metadata") or {}
        a = atwater(meta)
        a["rank"] = i
        a["score"] = m.get("score")
        a["match_id"] = m.get("id")
        packed.append(a)
    return {"query": query, "returned": True, "variant": variant, "ordered": packed}


def fail_line(x):
    return (
        f"  FAIL query={x['query']!r} fdc_id={x.get('match_id')!r} "
        f"data_source={x.get('data_source')!r} "
        f"P/C/F/cal={x.get('stored_protein')}/{x.get('stored_carbs')}/"
        f"{x.get('stored_fat')}/{x.get('stored_calories')} "
        f"computed={x.get('computed')} stored={x.get('stored_calories')} "
        f"rel={x.get('rel')} abs_kcal_serving={x.get('abs_kcal_serving')}"
    )


def print_severity(label, hits):
    print(f"##### {label} #####")
    if not hits:
        print("n=0 (no residual>15% hits)")
        return
    rels = [r["rel"] for r in hits]
    absd = [r["abs_kcal_serving"] for r in hits]
    print(f"n={len(hits)}")
    print(
        f"rel median={pctile(rels, 0.5)} p75={pctile(rels, 0.75)} "
        f"p90={pctile(rels, 0.90)} p95={pctile(rels, 0.95)} max={pctile(rels, 1.0)}"
    )
    print(
        f"abs_kcal_serving median={pctile(absd, 0.5)} p75={pctile(absd, 0.75)} "
        f"p90={pctile(absd, 0.90)} p95={pctile(absd, 0.95)} max={pctile(absd, 1.0)}"
    )


def check_realistic_duplicates(path: str) -> None:
    print("##### REALISTIC QUERY DUPLICATE CHECK #####")
    data = json.load(open(path))
    qs = data.get("realistic_queries") or []
    exact = Counter(qs)
    casefold = Counter(q.lower() for q in qs)
    exact_dups = [(k, v) for k, v in exact.items() if v > 1]
    casefold_dups = [(k, v) for k, v in casefold.items() if v > 1]
    print(f"realistic_queries n={len(qs)}")
    print(f"unique_exact={len(exact)}")
    print(f"unique_casefold={len(casefold)}")
    print(f"exact_duplicates={exact_dups}")
    print(f"casefold_duplicates={casefold_dups}")
    if not exact_dups and not casefold_dups:
        print("NO_DUPLICATES — not re-running realistic retrieval")


async def run_eval() -> None:
    print(f"EVAL_CASES count {len(EVAL_CASES)}")
    unique_cases, dropped = unique_eval_queries(EVAL_CASES)
    print(f"unique query count {len(unique_cases)}")
    print(f"dropped_duplicate_raw_inputs={dropped}")
    print(f"unique raw_input list ({len(unique_cases)}):")
    for i, case in enumerate(unique_cases, 1):
        print(f"  {i:02d} {case.raw_input!r} category={case.category}")

    eval_results = []
    for i, case in enumerate(unique_cases, 1):
        q = case.raw_input
        print(f"EVAL {i}/{len(unique_cases)} {q!r}", flush=True)
        try:
            r = await ranked_matches(q)
        except Exception as e:
            print("ERROR", type(e).__name__, e, flush=True)
            traceback.print_exc()
            r = {"query": q, "returned": False, "error": repr(e), "ordered": []}
        r["eval_category"] = case.category
        eval_results.append(r)

    print("\n##### ITEM 1 EVAL RAW (deduped by raw_input) #####")
    n_ret = sum(1 for r in eval_results if r.get("returned"))
    print(f"eval returned a record: {n_ret}/{len(eval_results)}")
    top1 = []
    for r in eval_results:
        if r.get("returned") and r["ordered"]:
            top1.append(
                {
                    **r["ordered"][0],
                    "query": r["query"],
                    "category": r.get("eval_category"),
                }
            )
        else:
            print(f"NO_RECORD query={r['query']!r} error={r.get('error')}")

    ok = [x for x in top1 if x.get("status") == "ok"]
    print(f"n_rows={len(top1)} n_ok={len(ok)}")
    hits_15 = []
    for t in (0.15, 0.25, 0.50):
        fails = [x for x in ok if x["rel"] > t]
        print(
            f"EVAL top-1 residual>{t}: {len(fails)} of {len(ok)} ok-complete "
            f"({len(top1)} returned)"
        )
        for x in fails:
            print(fail_line(x))
        if t == 0.15:
            hits_15 = fails

    print()
    print_severity("ITEM 3 EVAL severity among residual>15%", hits_15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--realistic-json",
        default="/tmp/atwater_retrieval.json",
        help="Previous-pass dump used only to confirm the 230-query list has no dupes",
    )
    args = parser.parse_args()
    check_realistic_duplicates(args.realistic_json)
    print()
    asyncio.run(run_eval())


if __name__ == "__main__":
    main()
