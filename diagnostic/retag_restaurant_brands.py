"""
Retag known restaurant-chain entries currently mislabeled as
source="usda_sr_legacy" so they stop leaking into "general" results.

Updates metadata IN PLACE (no re-embedding needed - same vector, new tag).

Builds the exact list of SR Legacy vector IDs directly from
data/processed/sr_legacy_full_clean.json (same file embed_sr_legacy.py reads),
so only the ~7,793 real SR Legacy vectors are fetched - no scanning the
460k+ Branded vectors in the same namespace.

Run from repo root: poetry run python scripts/retag_restaurant_brands.py
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index("food-index")

SR_LEGACY_JSON = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "sr_legacy_full_clean.json"
)

# Known fast food chains that show up embedded in SR Legacy's dataset.
# Add to this list as you find more (see dry-run output below).
CHAIN_NAMES = [
    "MCDONALD'S", "BURGER KING", "TACO BELL", "KFC", "WENDY'S",
    "ARBY'S", "SUBWAY", "PIZZA HUT", "DOMINO'S", "DAIRY QUEEN",
    "HARDEE'S", "JACK IN THE BOX", "SONIC", "CARL'S JR",
]

NEW_SOURCE = "usda_restaurant_brand"
DRY_RUN = False  # set to False once you've reviewed the matches
FETCH_BATCH_SIZE = 100


def find_restaurant_entries():
    """
    Build sr_<fdc_id> vector IDs directly from the local SR Legacy source
    file, fetch each vector's metadata from Pinecone, and check description
    against known chain names. Only ~7,793 vectors touched, not 469,057.
    """
    with open(SR_LEGACY_JSON) as f:
        sr_legacy_foods = json.load(f)

    all_ids = [f"sr_{food['fdc_id']}" for food in sr_legacy_foods]
    print(f"Built {len(all_ids)} SR Legacy vector IDs from local JSON")

    matches_found = []
    for i in range(0, len(all_ids), FETCH_BATCH_SIZE):
        batch_ids = all_ids[i : i + FETCH_BATCH_SIZE]
        fetched = index.fetch(ids=batch_ids, namespace="")
        for vec_id, vec in fetched.vectors.items():
            md = vec.metadata or {}
            desc = (md.get("description") or "").upper()
            if any(chain in desc for chain in CHAIN_NAMES):
                matches_found.append((vec_id, md.get("description")))

    return matches_found


def main():
    entries = find_restaurant_entries()

    print(f"\nFound {len(entries)} restaurant-brand entries tagged as usda_sr_legacy:")
    for vec_id, desc in entries:
        print(f"  {vec_id} — {desc}")

    if DRY_RUN:
        print("\nDRY_RUN is True — no changes made. Review the list above,")
        print("add any missing chain names to CHAIN_NAMES, then set DRY_RUN = False.")
        return

    print(f"\nUpdating {len(entries)} entries to source='{NEW_SOURCE}'...")
    for vec_id, _ in entries:
        index.update(id=vec_id, set_metadata={"source": NEW_SOURCE}, namespace="")
    print("Done.")


if __name__ == "__main__":
    main()