"""
Create every payload index required for Qdrant filtered queries.

Idempotent: safe to re-run against a collection that already has some or
all of these indexes. Existing indexes with the matching type are skipped;
mismatched types are reported and left untouched.

MUST run after every collection create, restore-from-backup, or rebuild
on a new machine. A storage-directory copy of the raw points does not
recreate payload indexes — that is how the 2026-08-25 egg-allergy banana
503 happened (unindexed allergen filters on ~2M points timed out).

See docs/qdrant-setup.md.

Usage (from repo root):
    poetry run python scripts/setup_qdrant_indexes.py
    QDRANT_URL=http://127.0.0.1:6333 poetry run python scripts/setup_qdrant_indexes.py
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models

load_dotenv()

DEFAULT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "food-vectors")
CREATE_TIMEOUT_SECONDS = 300

# ---------------------------------------------------------------------------
# Audited filter fields (2026-08-25).
#
# Every name below appears as a FieldCondition / IsNullCondition / MatchText
# key somewhere in this repo. Fields that are read from payload but never
# used in a Qdrant filter (Tier 2 boosts, brand, certification_status,
# nutrient ceilings) are intentionally omitted — see docs/qdrant-setup.md.
# ---------------------------------------------------------------------------

# Dataset origin. Filtered in nutrition_service._source_qdrant_condition.
# Distinct from preparation_source (USDA SOURCE_HOME / SOURCE_FRESH / …).
SOURCE_FIELD = "source"

# Point identity. Filtered in every qdrant_id MatchValue / MatchAny scroll
# (extract_allergens_*, backfill_nutrition_to_qdrant, validate_*, tests).
QDRANT_ID_FIELD = "qdrant_id"

# 9 FDA majors. dietary_filters.FDA_ALLERGENS / build_tier_1_filter.
FDA_ALLERGENS = [
    "milk",
    "egg",
    "fish",
    "shellfish",
    "tree_nut",
    "peanut",
    "wheat",
    "soy",
    "sesame",
]

# dietary_filters.NON_ALLERGEN_TIER_1 — hard-constraint match.
NON_ALLERGEN_TIER_1 = [
    "gluten_free",
    "lactose_free",
    "vegan",
    "vegetarian",
    "kosher",
    "halal",
]

# Query modifiers that _modifiers_qdrant_conditions turns into FieldConditions.
# Keys of parse_query_modifiers.ALL_MAPPINGS except "source" (already listed).
QUERY_MODIFIER_FIELDS = [
    "cooking_method",
    "prep_form",
    "skin_status",
    "coating_status",
    "sodium_level",
    "sweetness",
    "fat_level",
    "fat_added",
    "fat_trim",
    "grain_type",
    "sauce_profile",
    "temperature",
    "preparation_source",
]

# Written by backfill_modifiers_to_qdrant.py. Not a filter key this pass
# (branded tags stay Tier 1 until a later ranking change); indexed so a
# restore still has the field searchable when that change lands.
MODIFIER_PROVENANCE_FIELD = "modifier_provenance"

# scripts/validate_nutrition_backfill.py MatchValue filters.
PROVENANCE_FIELDS = [
    "vitamin_a_source",
    "folate_source",
    "vitamin_d_source",
]

# scripts/validate_nutrition_backfill.py IsNullCondition.
SUGAR_FIELD = "sugar"

# diagnostic/spot_check_allergens.py MatchText.
DESCRIPTION_FIELD = "description"


@dataclass(frozen=True)
class IndexSpec:
    field: str
    data_type: str  # keyword | bool | float | text
    reason: str


def required_indexes() -> list[IndexSpec]:
    specs: list[IndexSpec] = [
        IndexSpec(SOURCE_FIELD, "keyword", "dataset origin + colliding modifier category"),
        IndexSpec(QDRANT_ID_FIELD, "keyword", "point lookup / backfill / extract scripts"),
    ]
    for name in FDA_ALLERGENS:
        specs.append(IndexSpec(name, "keyword", "Tier 1 allergen hard filter"))
        specs.append(
            IndexSpec(
                f"{name}_may_contain",
                "bool",
                "Tier 1 severe-allergen must_not",
            )
        )
    for name in NON_ALLERGEN_TIER_1:
        specs.append(IndexSpec(name, "keyword", "Tier 1 non-allergen hard filter"))
    specs.append(
        IndexSpec(
            "dairy_free",
            "keyword",
            "accepted as a lactose_free match (not the reverse)",
        )
    )
    specs.append(
        IndexSpec(
            MODIFIER_PROVENANCE_FIELD,
            "keyword",
            "usda_extractor vs branded_text_heuristic (written now, filtered later)",
        )
    )
    for name in QUERY_MODIFIER_FIELDS:
        specs.append(
            IndexSpec(name, "keyword", "query-modifier FieldCondition (nutrition_service)")
        )
    for name in PROVENANCE_FIELDS:
        specs.append(IndexSpec(name, "keyword", "validate_nutrition_backfill count filter"))
    specs.append(IndexSpec(SUGAR_FIELD, "float", "validate_nutrition_backfill IsNullCondition"))
    specs.append(IndexSpec(DESCRIPTION_FIELD, "text", "spot_check_allergens MatchText"))
    return specs


def _schema_type_name(entry) -> str | None:
    """Normalize payload_schema entries from client objects or raw dicts."""
    if entry is None:
        return None
    data_type = getattr(entry, "data_type", None)
    if data_type is None and isinstance(entry, dict):
        data_type = entry.get("data_type")
    if data_type is None:
        return None
    return str(getattr(data_type, "value", data_type)).lower()


def _field_schema(data_type: str):
    mapping = {
        "keyword": models.PayloadSchemaType.KEYWORD,
        "bool": models.PayloadSchemaType.BOOL,
        "float": models.PayloadSchemaType.FLOAT,
        "text": models.PayloadSchemaType.TEXT,
    }
    try:
        return mapping[data_type]
    except KeyError as exc:
        raise ValueError(f"unsupported index data_type: {data_type!r}") from exc


def ensure_payload_indexes(
    client: QdrantClient,
    collection_name: str = DEFAULT_COLLECTION,
    *,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """
    Create any missing payload indexes. Returns
    {created, skipped, mismatched} lists of field names.
    """
    info = client.get_collection(collection_name)
    existing = info.payload_schema or {}

    created: list[str] = []
    skipped: list[str] = []
    mismatched: list[str] = []

    for spec in required_indexes():
        current = _schema_type_name(existing.get(spec.field))
        if current == spec.data_type:
            skipped.append(spec.field)
            print(f"  skip  {spec.field:24} already {spec.data_type}")
            continue
        if current is not None:
            mismatched.append(spec.field)
            print(
                f"  WARN  {spec.field:24} exists as {current}, "
                f"wanted {spec.data_type} — leaving untouched"
            )
            continue
        print(f"  create {spec.field:24} {spec.data_type:8} ({spec.reason})")
        if dry_run:
            created.append(spec.field)
            continue
        client.create_payload_index(
            collection_name=collection_name,
            field_name=spec.field,
            field_schema=_field_schema(spec.data_type),
            wait=True,
            timeout=CREATE_TIMEOUT_SECONDS,
        )
        created.append(spec.field)

    return {"created": created, "skipped": skipped, "mismatched": mismatched}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Qdrant REST URL")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without writing",
    )
    args = parser.parse_args(argv)

    print(f"Qdrant {args.url}  collection={args.collection}")
    client = QdrantClient(url=args.url, timeout=CREATE_TIMEOUT_SECONDS)
    try:
        info = client.get_collection(args.collection)
    except Exception as exc:
        print(f"ERROR: cannot read collection {args.collection!r}: {exc}", file=sys.stderr)
        return 1

    print(
        f"status={info.status} points={info.points_count} "
        f"existing_indexes={len(info.payload_schema or {})}"
    )
    print()

    result = ensure_payload_indexes(
        client, args.collection, dry_run=args.dry_run
    )

    print()
    print(
        f"created={len(result['created'])}  "
        f"skipped={len(result['skipped'])}  "
        f"mismatched={len(result['mismatched'])}"
    )
    if result["mismatched"]:
        print("Mismatched types (not modified): " + ", ".join(result["mismatched"]))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
