#!/usr/bin/env python3
"""Upgrade existing food_logs documents to the Spec 1 FoodEvent shape.

Required first step (not performed by this script):

    mongodump --uri="<atlas uri>" --collection=food_logs --out=./backups/premigration-$(date +%F)

Confirm the dump completed and is non-trivial before --apply.

Defaults to dry-run (TEST_MODE). Production writes require --apply.
"""

from __future__ import annotations

import argparse
import os
from copy import deepcopy
from datetime import datetime, timezone

from pymongo import MongoClient

from backend.models.food_event import CONFIDENCE_FIELD_KEYS
from backend.services.nutrient_fields import wrap_nutrient_map


def transform_log(doc: dict) -> dict:
    """Map a pre-Spec-1 food_logs document to one that carries FoodEvent."""
    out = deepcopy(doc)
    extras = doc.get("extra_nutrients") or {}
    amount = 1.0
    unit = "count"
    quantity = doc.get("quantity")
    if isinstance(quantity, (int, float)) and not isinstance(quantity, bool):
        amount = float(quantity)
    confidence = {
        key: {"band": "low", "asr": None, "semantic": None, "database": None}
        for key in CONFIDENCE_FIELD_KEYS
    }
    provenance = {key: "record_default" for key in CONFIDENCE_FIELD_KEYS}
    event = {
        "item_type": "food",
        "entry_mode": "resolved",
        "visibility": "private",
        "food": doc.get("food_name"),
        "brand": None,
        "upc": None,
        "variant_tags": [],
        "recipe_ref_id": None,
        "preparation": None,
        "quantity_kind": "count",
        "amount": amount,
        "unit": unit,
        "unit_definition": None,
        "hydration_state": None,
        "packing_medium_consumed": None,
        "consumption_fraction": 1.0,
        "meal_slot": None,
        "allergen_state": {},
        "restriction_tags": {},
        "certification_status": {},
        "confidence": confidence,
        "provenance": provenance,
        "evidence_basis": {},
        "resolution_status": "resolved",
        "calories": doc.get("calories"),
        "macronutrients": {
            "protein": doc.get("protein"),
            "carbohydrates": doc.get("carbs"),
            "fats": doc.get("fat"),
        },
        "nutrients": wrap_nutrient_map(extras),
        "serving_label": None,
        "serving_note": None,
        "candidates": [],
        "portion_options": [],
        "used_dietary_fallback": False,
        "quantity_used": amount,
        "fdc_id": None,
        "source": None,
        "logged_food_name": doc.get("food_name"),
        "logged_brand": None,
        "logged_serving_label": None,
        "serving_size": quantity if isinstance(quantity, str) else None,
        "notes": None,
        "reasoning": doc.get("reasoning"),
        "alternatives": doc.get("alternatives"),
        "resolution": {"status": "resolved"},
        "data_source": None,
        "modifiers": None,
        "blocked_by_allergy": False,
        "resolution_audit": {
            "raw_transcript": doc.get("raw_input"),
            "parsed_interpretation": {"food": doc.get("food_name")},
            "candidate_set_considered": [],
            "record_selected": None,
            "assumptions_applied": ["migrated_from_pre_food_event"],
            "user_confirmations": [],
        },
    }
    out["food_event"] = event
    out["utterance"] = {
        "intent": "LOG",
        "subject_user_id": doc.get("user_id"),
        "input_modality": "text",
        "activation": None,
        "raw_transcript": doc.get("raw_input"),
    }
    if "logged_at" in out and isinstance(out["logged_at"], datetime):
        if out["logged_at"].tzinfo is None:
            out["logged_at"] = out["logged_at"].replace(tzinfo=timezone.utc)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write transformed documents. Default is dry-run.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max docs to scan (0 = all)")
    args = parser.parse_args()

    uri = os.environ.get("MONGODB_URL")
    if not uri:
        raise SystemExit("MONGODB_URL is required")

    client = MongoClient(uri)
    coll = client["speak2me-fitness"]["food_logs"]
    cursor = coll.find({})
    if args.limit:
        cursor = cursor.limit(args.limit)

    docs = list(cursor)
    samples = [transform_log(d) for d in docs[:3]]
    print(f"scanned={len(docs)} dry_run={not args.apply}")
    for sample in samples:
        event = sample.get("food_event") or {}
        print(
            "sample",
            {
                "_id": sample.get("_id"),
                "food": event.get("food"),
                "resolution_status": event.get("resolution_status"),
            },
        )

    if not args.apply:
        print("TEST_MODE: no writes. Re-run with --apply after sign-off.")
        return

    print("APPLY: writing transformed documents")
    for doc in docs:
        transformed = transform_log(doc)
        coll.replace_one({"_id": doc["_id"]}, transformed)
    print(f"wrote={len(docs)}")


if __name__ == "__main__":
    main()
