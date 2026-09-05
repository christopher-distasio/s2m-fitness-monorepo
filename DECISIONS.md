# Decision Log

One line per consequential choice, with a one-line rationale. Newest first.

This exists to answer "why did we decide X" six weeks later. It is deliberately separate from the roadmap, which describes current state and plans. Product-scope decisions that constrain implementation broadly still live in `docs/scope-decisions-d1-d5.md`; this log is for everything else — schema shape, tiering, extraction scope, suppression lists, tuning calls.

Add an entry as part of the change that makes the decision, not afterward. Format:

```
- **YYYY-MM-DD — <decision in one line>.** <One-line rationale.> <Optional: commit/PR or doc link.>
```

## Entries

- **2026-09-04 — Normalize Euromonitor branded nutrients from per-serving onto the per-100g basis at Qdrant-read time, via a `data_source` allowlist.** Measured on branded_food.csv 2026-04-30: Euromonitor fluid-milk energy densities only make sense as label-per-serving; GDSN/LI invert, so this is one provider's convention, not a global flip.
- **2026-08-30 — Scoped the `lactose_free` definition rather than inferring it broadly.** TODO: confirm rationale in a calm review; flagged mid-session and should not be treated as final until reviewed.
- **2026-08-30 — Adopted a suppression list for `light` / `raw` modifier terms during modifier extraction.** These terms produced false-positive modifier matches in the two-round manual review of 200 branded records.
- **2026-08-30 — Recommended promoting modifier-filter coverage from Tier 1 to Tier 2 testing.** Tier 1 only proves the specific bug is fixed; adjacent cases are where the remaining risk sits.
