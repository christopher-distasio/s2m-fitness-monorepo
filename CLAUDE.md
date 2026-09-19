# Speak2Me Fitness (S2M)

Voice-first food logging app. Accessibility is the foundational design
principle, not an add-on — built for people whose disabilities keep them
from benefiting from conventional fitness apps.

## Stack

* Frontend: Next.js 14
* Backend: FastAPI (Python, Poetry)
* Database: MongoDB Atlas + Beanie ODM
* Vector search: Qdrant, self-hosted in Docker (text-embedding-3-large,
  3072 dims, cosine). Collection `food-vectors`, ~2.01M points.
* AI: OpenAI GPT-4o-mini (parsing) + Whisper (transcription)
* Food data: USDA FoodData Central (SR Legacy, FNDDS, Branded Foods,
  CSV release 2026-04-30)
* Deployment: Cloudflare

## Before marking any task done

    poetry run pytest tests/ -m "not live and not slow" -q

Baseline: 391 passed, 26 deselected. Never merge below baseline.

Eval suite lives in `tests/eval_food_parser.py` — 34 entries, 33 unique
queries ('a cup of black coffee' appears twice on purpose: once as a
parse case, once with calorie bounds). Dedupe by `raw_input` when
computing retrieval stats.

Python is pinned to 3.11 via `poetry env use python3.11`. System default
is 3.14, which this project does not support — always use `poetry run`.

## Qdrant

Runs in Docker on the MacBook Air. `QDRANT_URL=http://localhost:6333`.

Do not point it at the Mac Mini (192.168.1.229). A stale Mini reference
sent an earlier debugging session querying an instance the app was not
using, which made a bug appear to resolve itself.

Restart policy is `unless-stopped` — the container cycles on sleep
otherwise.

Snapshots (created via the snapshot API, copied out with `docker cp`):

    ~/qdrant-backups/food-vectors/

* 2026-08-15 — 26GB, predates the modifier backfill
* 2026-09-01 — 33.4GB, current

Take a fresh snapshot before any bulk payload rewrite. A snapshot at this
size takes ~3-4 minutes; the API call blocks until it finishes.

Never store backups in /tmp — macOS clears it on reboot.

## Data status

* ~2.01M points in Qdrant (1,999,864 branded + SR Legacy/FNDDS)
* Three USDA providers: LI (Label Insight) ~1.72M, GDSN ~123k,
  Euromonitor ~2.2k
* 150,690 phantom stub points (no calories, no data_source) — flagged
  for cleanup
* 162,364 branded points with empty serving_size_g — uncharacterized

## Known data defects

USDA Branded Foods ships inconsistent data. These are source defects,
not ingest bugs — the nutrient_id mapping in `scripts/process_branded.py`
is verified correct (1003 protein, 1004 fat, 1005 carbs, 1008 calories).

* **Provider basis mismatch (FIXED).** Euromonitor stores nutrients
  per label serving; LI and GDSN store per 100g. Normalized in
  `_qdrant_results_to_matches` via `normalize_nutrients_to_per_100g`.
  Never scale Euromonitor values without normalizing first.
* **Calorie/macro mismatch (FLAGGED, not fixed).** 156,263 records
  where 4P+4C+9F differs from stored calories by >15%. Cannot be
  corrected — nothing in the data says which number is wrong. Surfaced
  as `calorie_macro_mismatch` / `_rel` / `_kcal` on match metadata.
  Keys are OMITTED when uncomputable (missing macro or calories <= 0);
  `False` means computed and clean. Fires on ~7.8% of realistic top-1
  results; median error 18 kcal per serving.
* **serving_size_g x1000 (PARTIALLY FIXED).** One sanitizer branch was
  firing on three unrelated problems. Now fires only on LI mg/mc units
  (7,485 rows) where the unit is wrong but the number is grams. Still
  open: genuine sub-gram servings (sprays, spices) and 35 Euromonitor
  rows whose serving sizes are cup fractions written into a gram field.
* **Ranking ties.** ~30% of realistic queries have a tied top-1 cluster
  (identical lexical AND vector scores). Broken deterministically by
  fdc_id, sorted as a STRING — "1796943" < "532148". Repeatable, but
  arbitrary. Real scoring signal is still missing.

## Design principles — do not violate

* Accessibility is foundational: every logging path must work for users
  conventional fitness apps fail
* Benefiting from the app must be easy, or people won't use it
* Contextual triggering: features activate off signals (a detected
  completed workout can auto-suggest "log my post-workout meal")
* Users must be able to talk about their own recipes (roadmap, not built)

## Working conventions

* Do not accept summaries — show literal file contents, command output,
  and raw data. Never paraphrase what a file says.
* Verify before fixing. Confirm a suspected bug with clean, typed input
  before writing code.
* Quantify blast radius immediately when a new bug class is found: how
  many records, which providers, does it surface in retrieval.
* When a fix keys on a payload field, prove that field's coverage across
  the whole collection before relying on it.
* One rule per fix. If a single code branch handles unrelated cases,
  split it rather than widening it.
* Work on main. Commit when tests pass.

## Formatting

No enforced linting or formatting. Match the style of surrounding code.
Do not reformat, reorganize, or restyle code you are not otherwise
changing — no import sorting, no line-length rewraps, no autopep8 runs
across files. Diffs should contain only intentional changes.

## Commits

Conventional Commits prefixes: `feat:`, `fix:`, `chore:`, `test:`,
`docs:`, `refactor:`.

Long form. Subject line under ~72 chars, blank line, then a body that
explains what changed and why. For data-layer work the body should
include the blast radius — how many records, which providers, and
whether it surfaces in retrieval.

Example:

    fix: narrow serving_size_g x1000 correction to LI mg/mc units

    The x1000 branch was firing on 22,414 US branded rows covering three
    unrelated problems: LI rows where the unit says MG but the number is
    grams (correct to x1000), genuine sub-gram servings such as sprays
    and spices (wrong), and 35 Euromonitor rows whose serving sizes are
    cup fractions written into a gram field (wrong both ways).

    Narrowed to the mg/mc unit class only: 7,485 rows, all LI. The
    remaining 14,992 fall through to branded_serving_size with their
    stored sub-gram values; none land in a fallback state.

    Qdrant payloads do not carry serving_size_unit, so the read path
    resolves it from a CSV-derived id map at
    backend/services/usda_mg_mc_serving_units.json. process_branded now
    stores the unit, so a re-embed removes the need for that file.

    Sub-gram and Euromonitor serving rules remain open.

## Current focus

1. Verify the top ~200 realistic foods return correct numbers
2. Plural / word-number parsing ("two dannon yogurts")
3. Euromonitor serving-size rule (35 rows)
4. Sub-gram serving rule (sprays, spices)
5. Identity resolution — three fdc_ids share
   "Dannon Light + Fit Greek Nonfat Yogurt" with different calories;
   flavor appears only in ingredients, never in the embedded name

## Reference

* Roadmap: S2M_Master_Roadmap_AUG29_UPDATE_v2.docx
* Decisions log: DECISIONS.md
* Realistic query set: diagnostic/realistic_food_queries.json (230 queries)
