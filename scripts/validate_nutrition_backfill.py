"""
Post-backfill validation for the nutrition payload backfill (branded_foods,
sr_legacy, fndds).

Not a sample-based spot-check -- this pulls real fleet-wide counts from
Qdrant, same census-style approach used for the allergen duplicate-point
safety check earlier this project. A sample can miss a systemic issue that
only affects a subset of records; a full count against known totals can't.

Four checks:
  1. Sugar coverage -- confirm the 1063->2000 ID fix landed at fleet scale,
     matching Cursor's TEST_MODE percentages (branded ~94.6%, SR Legacy
     ~77.1%, FNDDS ~100%)
  2. Provenance tag distribution -- confirm vitamin_a_source / folate_source /
     vitamin_d_source counts sum to each source's total record count, so no
     records were silently skipped or left untagged
  3. Known-value spot-checks -- a small set of foods where the right answer
     is known (e.g. a cola should show high sugar), extending the handful
     Cursor already validated in TEST_MODE
  4. Allergen non-regression -- confirm allergen fields are still intact
     fleet-wide, not just on previously-sampled records -- this backfill
     should be nutrition-only and never touch allergen fields

Read-only, no writes.
"""

from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

ALLERGENS = ["milk", "egg", "fish", "shellfish", "tree_nut", "peanut", "wheat", "soy", "sesame"]

SOURCES = ["branded_foods", "sr_legacy", "fndds"]

# A handful of records with a well-known expected nutrition profile, spanning
# all three sources and several of tonight's fixes (sugar, vitamin D, vitamin A).
KNOWN_VALUE_CHECKS = [
    # (qdrant_id, description_contains, field, expectation)
]


def source_filter(source: str) -> models.FieldCondition:
    return models.FieldCondition(key="source", match=models.MatchValue(value=source))


def check_sugar_coverage(client: QdrantClient):
    print("=== 1. Sugar coverage (fleet-wide) ===")
    for source in SOURCES:
        total = client.count(
            collection_name=COLLECTION_NAME,
            count_filter=models.Filter(must=[source_filter(source)]),
        ).count

        has_sugar = client.count(
            collection_name=COLLECTION_NAME,
            count_filter=models.Filter(
                must=[source_filter(source)],
                must_not=[models.IsNullCondition(is_null=models.PayloadField(key="sugar"))],
            ),
        ).count

        pct = (has_sugar / total * 100) if total else 0
        print(f"  {source}: {has_sugar:,} / {total:,} ({pct:.1f}%) have sugar data")
    print()


def check_provenance_distribution(client: QdrantClient):
    print("=== 2. Provenance tag distribution (sums should match source totals) ===")
    for source in SOURCES:
        total = client.count(
            collection_name=COLLECTION_NAME,
            count_filter=models.Filter(must=[source_filter(source)]),
        ).count
        print(f"  {source} (total {total:,}):")

        for field, tags in [
            ("vitamin_a_source", ["measured_rae", "unsupported_conversion", "no_data"]),
            ("folate_source", ["measured_dfe", "fallback_from_total", "no_data"]),
            ("vitamin_d_source", ["measured_mcg", "converted_from_iu", "no_data"]),
        ]:
            tag_sum = 0
            counts = {}
            for tag in tags:
                c = client.count(
                    collection_name=COLLECTION_NAME,
                    count_filter=models.Filter(
                        must=[source_filter(source), models.FieldCondition(key=field, match=models.MatchValue(value=tag))]
                    ),
                ).count
                counts[tag] = c
                tag_sum += c

            status = "OK" if tag_sum == total else f"MISMATCH (sum={tag_sum:,}, total={total:,})"
            print(f"    {field}: {counts} -> {status}")
    print()


def check_known_values(client: QdrantClient):
    print("=== 3. Known-value spot-checks ===")
    if not KNOWN_VALUE_CHECKS:
        print("  No entries configured -- fill in KNOWN_VALUE_CHECKS with a few")
        print("  real fdc_ids + expected values before relying on this section.")
        print()
        return

    for qdrant_id, desc_hint, field, expectation in KNOWN_VALUE_CHECKS:
        result, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(must=[models.FieldCondition(key="qdrant_id", match=models.MatchValue(value=qdrant_id))]),
            limit=1,
            with_payload=True,
        )
        if not result:
            print(f"  [{qdrant_id}] NOT FOUND")
            continue
        actual = result[0].payload.get(field)
        print(f"  [{qdrant_id}] {desc_hint}: {field}={actual} (expected: {expectation})")
    print()


def check_allergen_non_regression(client: QdrantClient):
    print("=== 4. Allergen non-regression (fleet-wide) ===")
    valid_states = {"CONTAINS", "FREE", "UNKNOWN"}

    for source in SOURCES:
        total = client.count(
            collection_name=COLLECTION_NAME,
            count_filter=models.Filter(must=[source_filter(source)]),
        ).count

        for allergen in ALLERGENS:
            invalid = 0
            for state in valid_states:
                pass  # counting invalid directly is cheaper via must_not

            valid_count = client.count(
                collection_name=COLLECTION_NAME,
                count_filter=models.Filter(
                    must=[source_filter(source)],
                    should=[models.FieldCondition(key=allergen, match=models.MatchValue(value=s)) for s in valid_states],
                ),
            ).count

            if valid_count != total:
                print(f"  {source} / {allergen}: {valid_count:,} / {total:,} valid -- MISMATCH, investigate")

        print(f"  {source}: all {len(ALLERGENS)} allergen fields checked")
    print()


def main():
    client = QdrantClient(url=QDRANT_URL, timeout=60)
    check_sugar_coverage(client)
    check_provenance_distribution(client)
    check_known_values(client)
    check_allergen_non_regression(client)
    print("Validation complete.")


if __name__ == "__main__":
    main()
