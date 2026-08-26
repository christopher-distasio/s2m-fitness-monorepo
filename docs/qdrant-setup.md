# Qdrant setup (food-vectors)

Local vector store for USDA food lookup. Collection name: `food-vectors`.
Default URL: `http://127.0.0.1:6333` (`QDRANT_URL` in `.env`).

## Start the container

```bash
docker compose up -d qdrant
```

`docker-compose.yml` mounts a named volume at `/qdrant/storage`. That volume
holds points **and** payload indexes *if those indexes were created while
this volume was live*. It does **not** invent indexes that were never
created.

## Payload indexes are a required setup step

Filtered search on this ~2M-point collection without a payload index on the
filtered field times out the production client (2026-08-25: banana + egg
allergy → 503). Indexes are **not** created by `create_collection`, by
upserting points, or by restoring the raw-data backup at
`/tmp/qdrant_backup/storage`.

After **any** of the following, run:

```bash
poetry run python scripts/setup_qdrant_indexes.py
```

- Collection created for the first time (`diagnostic/embed_all_to_qdrant.py`,
  `diagnostic/import_pinecone_to_qdrant.py`)
- Restore from a storage-directory backup
- Rebuild on a new machine (Mac Mini, fresh Docker volume, etc.)

The script is idempotent. Re-running it on a collection that already has
every required index is a skip/no-op, not an error.

Override the target with env or flags:

```bash
QDRANT_URL=http://127.0.0.1:6333 poetry run python scripts/setup_qdrant_indexes.py
poetry run python scripts/setup_qdrant_indexes.py --url http://127.0.0.1:6333 --dry-run
```

`embed_all_to_qdrant.py` and `import_pinecone_to_qdrant.py` call this same
function after the collection exists, so a full re-embed does not depend on
remembering the manual command. A restore-from-backup still needs the
command above — restore never runs those embed scripts.

## What is indexed (and what is not)

`scripts/setup_qdrant_indexes.py` indexes every payload field that appears
in a Qdrant `Filter` / `FieldCondition` / `IsNullCondition` / `MatchText`
anywhere in this repo:

| Group | Fields | Type |
| --- | --- | --- |
| Dataset origin | `source` | keyword |
| Point identity | `qdrant_id` | keyword |
| 9 FDA allergens | `milk` `egg` `fish` `shellfish` `tree_nut` `peanut` `wheat` `soy` `sesame` | keyword |
| may-contain flags | `{allergen}_may_contain` | bool |
| Tier 1 non-allergen | `gluten_free` `lactose_free` `vegan` `vegetarian` `kosher` `halal` | keyword |
| Query modifiers | `cooking_method` `prep_form` `skin_status` `coating_status` `sodium_level` `sweetness` `fat_level` `fat_added` `fat_trim` `grain_type` `sauce_profile` `temperature` `preparation_source` | keyword |
| Lactose OR-match | `dairy_free` | keyword |
| Modifier provenance | `modifier_provenance` | keyword |
| Backfill validation | `vitamin_a_source` `folate_source` `vitamin_d_source` | keyword |
| Backfill validation | `sugar` | float |
| Diagnostic text match | `description` | text |

Not indexed, because they are **not** Qdrant filter keys:

- **Tier 2** preferences (`keto`, `organic`, …) — post-retrieval boost only
- **`certification_status`**, **`brand` / `brand_name`** — not used in any `FieldCondition`
- **Nutrient ceilings** — reported after lookup, never pushed into the Qdrant filter
- **`sulfite_free`** — placeholder on the user profile; not wired to search

If you add a new `FieldCondition` key, add it to `required_indexes()` in the
setup script in the same change and re-run the script.
