# Spec 1 — FoodEvent Object + Four-Layer Confidence Model

Branch: `feat/food-event-confidence-model` (from main)

Foundational data-shape change. Specs 2-4 (confirmation rules, verbosity setting, partial recapture) all read from this. Get the shape right; downstream code assumes it.

## 1. The FoodEvent model

New Pydantic model (suggest `backend/models/food_event.py`). This replaces the ad-hoc `parsed` dict as the canonical shape flowing from parse -> lookup -> route -> log. The existing dict keys map into it; nothing is lost, several things are added.

```python
class VariantTag(BaseModel):
    type: str    # "fat_content" | "grain_type" | "style" | "flavor" | "diet_formulation" | "size_class" | ...
    value: str   # "2%", "whole wheat", "greek", "vanilla", "sugar_free", "large"

class FieldConfidence(BaseModel):
    band: str                    # "high" | "medium" | "low"  <- ALL decision logic reads ONLY this
    asr: float | None = None     # raw Whisper signal; None for typed input
    semantic: float | None = None    # logprob-derived from GPT output tokens
    database: float | None = None    # Qdrant top score; store top1-top2 gap alongside if easy

class FoodEvent(BaseModel):
    # Item type — what kind of intake this is. Shapes that don't fit here
    # (symptoms, activity) become SIBLING COLLECTIONS later, not subtypes of this.
    item_type: str = "food"         # "food" | "beverage" | "supplement"

    # Entry mode — resolved food lookup vs. direct macro dictation
    entry_mode: str = "resolved"    # "resolved" | "direct_macro"
    # direct_macro: identity fields legitimately empty; calories/macros are user-stated
    # with provenance="user_stated". NOT the same as resolution_status="unresolved" —
    # that means "we tried and failed"; direct_macro means "there was nothing to resolve."

    # Sharing consent — default private, nothing leaves the device without an explicit change
    visibility: str = "private"     # "private" | "shared_anonymous" | "shared_attributed"
    # Consumption data (what/when/how much someone ate) is NEVER shared regardless of
    # this value. This field governs contributed PRODUCT data only (see hard rule 15).

    # Identity
    food: str | None = None         # None only when entry_mode="direct_macro"
    brand: str | None = None
    upc: str | None = None          # barcode scan (Phase 2) — populated when input_modality="barcode"
    variant_tags: list[VariantTag] = []
    recipe_ref_id: str | None = None    # reserved FK to a future saved-recipe/PERSONAL_FOOD entity
                                        # (Phase 2/3) — no recipes collection needs to exist yet

    # Preparation
    preparation: str | None = None

    # Quantity
    quantity_kind: str = "count"    # "count" | "measure" — count = discrete containers/units
                                    # (2 yogurts, 2 apples), measure = continuous amount (2 cups rice)
    amount: float = 1.0
    unit: str = "count"
    unit_definition: dict | None = None
    # when quantity_kind="count" and the unit is a confirmed container size, e.g.
    # {"size": "5.3oz cup", "source": "user_confirmed"} — without this, a logged
    # "2 yogurts" can't later be audited as 2 cups vs. 2 tubs (a 6x calorie difference)
    hydration_state: str | None = None          # "dry" | "cooked" — grains/pasta/legumes only
    packing_medium_consumed: bool | None = None # canned/jarred only
    consumption_fraction: float = 1.0           # user-stated ONLY; system never infers
    meal_slot: str | None = None    # "breakfast" | "lunch" | "dinner" | "snack" | None
                                    # nullable now; grouping/session logic is a later spec

    # Safety & restrictions — shared three-state machinery
    allergen_state: dict[str, str] = {}         # value in {"contains","free","unknown"}
    restriction_tags: dict[str, str] = {}       # same three-state; includes "meat_dairy_class"
                                                # with values "meat"|"dairy"|"pareve" as special case
    certification_status: dict[str, str] = {}   # {"halal": "certified"|"not_certified"|"unknown"}
                                                # DEFAULT unknown. NEVER derived from ingredients.

    # Confidence — per field, keyed by field name
    confidence: dict[str, FieldConfidence] = {}
    # required keys when populated: "food", "brand", "variant", "preparation",
    # "amount", "unit", "negation", "allergen_match"
    # (all fields day one — populate every key on every parse)

    # Provenance — per field; separate from confidence, this is WHERE the value came from
    provenance: dict[str, str] = {}
    # values: "user_stated" | "user_approximate" | "user_confirmed" | "inferred" | "record_default"
    # "user_approximate" = hedged input ("I think it was...") — must survive into the log as hedged

    # Evidence basis for safety/restriction claims (v1 minimal — see section 3a)
    evidence_basis: dict[str, str] = {}
    # per allergen/restriction key: "declared_ingredient" | "advisory_label_present"
    #   | "certified" | "not_assessed"
    # This is WHY we know (or don't). Distinct from allergen_state (WHAT we know)
    # and confidence (how sure). Reporting evidence is not asserting safety.

    # Resolution
    resolution_status: str = "resolved"         # "resolved" | "needs_clarification" | "unresolved"

    # Existing nutrition payload fields carry over — WITH TWO CHANGES:
    # calories, macronutrients, nutrients, serving_label, serving_note,
    # candidates, portion_options, used_dietary_fallback, quantity_used, fdc_id/source
    #
    # CHANGE 1 — every nutrient value stores its unit explicitly:
    #   {"sodium": {"value": 640, "unit": "mg", "usda_nutrient_id": 1093}}
    #   NOT {"sodium": 640}. Inferring units later from convention is exactly the
    #   error class that produced the Vitamin D IU-vs-mcg rework in August.
    #   Keeping usda_nutrient_id makes future standards mapping (incl. FHIR) a
    #   lookup table rather than data archaeology — see hard rule 16.
    #
    # CHANGE 2 — denormalize human-readable display values into the log at write time.
    #   Storing fdc_id alone means any export must re-query every referenced record,
    #   and a later data refresh silently rewrites historical logs. Store the resolved
    #   food name, brand, and serving label AS LOGGED alongside the id.
```

## 1a. UtteranceResult wrapper (NEW — architectural change, do not skip)

FoodEvent is NOT the top-level object. It is what one branch of an intent router produces. Four different communicative acts can wrap the same food ambiguity ("I had milk" / "what milk did I log?" / "change that to oat milk" / "always assume oat milk"), and "delete the last one" has almost no food semantics at all. Introducing the wrapper now is cheap; retrofitting it after Specs 2-4 read FoodEvent as top-level is not.

```python
class UtteranceResult(BaseModel):
    intent: str = "LOG"          # v1 ONLY emits "LOG"; enum reserved for
                                 # REPAIR | QUERY | CONTROL | CONFIRM | SETTING | SAFETY | ...
    food_events: list[FoodEvent] = []   # LIST — "eggs, toast, and coffee" is one utterance,
                                        # three events. Never assume singular.
    subject_user_id: str                  # EXPLICIT always — never an implicit "current user"
    input_modality: str = "text"          # "voice" | "text" | "photo" | "barcode"
    activation: str | None = "push_to_talk"   # ONLY meaningful when input_modality="voice"
                                              # "push_to_talk" | "wake_word" | "ambient"
    raw_transcript: str | None = None
```

v1 scope is log-only: the intent field is always "LOG" and no classifier is built in this spec. The point is that the shape exists so Specs 2-4 and the future intent layer plug in rather than refactor.

**Two option-preserving rules that cost nothing now and are expensive later:**
1. `subject_user_id` is explicit on every record and session object. Do not introduce ambient-current-user shortcuts anywhere.
2. All TTS output goes through a SINGLE `speak()` choke point. No direct TTS calls from route handlers or components. This is the one that makes future shared-device/discretion policy a one-line insertion instead of a full call-site audit.

## 2. Confidence capture — implementation per layer

**ASR layer:** switch the Whisper call to `response_format="verbose_json"`. Capture per-segment `avg_logprob` and `no_speech_prob`. Map to the segment(s) covering each parsed field where determinable; otherwise apply utterance-level values to all fields. Typed input: `asr=None`, and the asr layer contributes nothing to band computation.

**Semantic layer:** request `logprobs=True` (with `top_logprobs`) on the GPT parse call. Derive per-field confidence from the token logprobs of each field's VALUE tokens in the structured output (e.g. the tokens producing "2" for amount). Do NOT use model self-reported confidence numbers for this layer — keep the existing coarse high/medium/low self-report as a whole-parse sanity signal only.

**Database layer:** capture the Qdrant similarity score of the chosen match, and the score gap between top-1 and top-2 (small gap = ambiguous match). Already computed in `_retrieve_best` — stop discarding it.

**Band computation:** one function, `compute_band(asr, semantic, database) -> "high"|"medium"|"low"`. Initial thresholds are placeholders to be tuned against the eval suite — put them in one constants block, clearly marked TUNABLE, not scattered. Rules: any missing layer is skipped, not treated as zero. If extraction of any signal fails, band = "low" (see hard rules).

## 2a. LLM API usage standards (applies to every GPT call, this spec and after)

Principle: **LLMs at the edges, determinism in the middle.** Interpretation is an LLM job; decisions are code.

1. **Strict structured outputs.** Use OpenAI structured outputs with `strict: true` and a JSON schema on every parse call. This alone makes the "2 bananas" class of bug structurally impossible — a schema-typed `amount: number` cannot come back as "2 bananas".
2. **Enum-constrain every closed value space** in the schema: `unit`, `hydration_state`, `preparation`, `intent`, `provenance`, `resolution_status`, variant `type`. An invalid value becomes unemittable rather than something the validation layer catches after the fact.
3. **Many small focused calls, not one mega-prompt.** The quantity bug came from two contradictory instructions inside one large prompt. Split extraction jobs (identity / quantity+unit / modifiers+negation) where prompt sections could conflict. At 4o-mini pricing the extra calls are effectively free; prompt clarity is the scarce resource.
4. **Model tiering, never ensembling.** Cheap model for cheap jobs; escalate to a stronger model only when a specific field comes back ambiguous. Do NOT call multiple models on the same input and vote/merge in the request path — disagreement doesn't identify the correct answer, and it multiplies cost and latency. Multi-model review stays offline (design/spec synthesis).
5. **Deterministic validation layer after every call.** Schema conformance is necessary, not sufficient: also range-check numbers, verify enum plausibility in context, and confirm required fields for the detected food bucket. Failures route to `resolution_status="needs_clarification"`, never to a silent default.
6. **Safety-critical decisions never run through an LLM.** Allergen/restriction blocking, threshold checks, and nutrition arithmetic are deterministic code reading FoodEvent fields — auditable and unit-testable.

## 2b. Resolution audit trail

Extend per-field provenance into a full chain, stored on the log document:

```
raw_transcript -> parsed_interpretation -> candidate_set_considered
  -> record_selected (fdc_id + source) -> assumptions_applied -> user_confirmations
```

Not necessarily surfaced in the UI on every log, but it must exist. It is the technical substance behind every trust and provenance claim, it powers the future "why 300 calories?" / "which entry did you use?" query, and it is what makes a clinician/OT export credible. Cheap to add while the model is being written; expensive to reconstruct later.

## 3. Hard rules (non-negotiable)

1. **Graceful degradation:** confidence machinery failing anywhere (API shape change, missing logprobs, exception in band computation) must NEVER block or fail a log. Catch, set band="low", set provenance="inferred" if unknown, proceed. Add an explicit test for this.
2. **Decision logic reads bands only.** Raw floats are stored for telemetry/tuning; nothing branches on a raw float.
3. **consumption_fraction is user-stated only.** No inference path may set it != 1.0.
4. **"May contain"/facility-language mapping:** in allergen/restriction extraction and lookup, "may contain X" / "made in a facility with X" -> "unknown". Never "free", never "contains". Write this as a constant-documented rule in the extraction code.
5. **certification_status is never inferred from ingredients.** Only set from explicit certification data (which we mostly don't have yet -> stays "unknown"). Ingredient-compatibility and certification are different sentences everywhere they surface.
6. **resolution_status="unresolved"** replaces every silent-0-calorie path: if no candidate is acceptable, nothing logs; the route returns the unresolved state for the frontend to show an explicit not-recognized message with re-entry. (This closes the 0-cal fallback backlog item.)
7. **Report, never assert safety.** The app states what the record shows and what is unknown. It never emits "this is safe for you" for any allergen, restriction, or certification. `evidence_basis` reports the basis for a claim; reporting evidence is not asserting safety. This is a product-wide language rule, not just a data rule — it governs UI copy and TTS phrasing too.
8. **Modality parity.** Every flow — including clarification, correction, and partial recapture — must be completable by voice alone AND by touch alone. Neither may ever be the only escape hatch (a blind user with a tremor has no reliable touch path; a deaf speech-impaired user has no voice path). Add this to the four-tier Tier 4 check.
9. **Hands-free/wake-word activation is core scope (REVISED Aug 18 — reverses earlier push-to-talk-only framing).** `input_modality="voice"` plus `activation` supporting "wake_word" and "ambient" alongside "push_to_talk". Wake-word detection and basic addressedness filtering (distinguishing directed speech from TV/background noise) are a REQUIRED v1 build item — not for safety reasons, but because ambient listening without it produces false-positive logs from any nearby audio. This is a product-functionality requirement, distinct from the privacy/bystander-exposure question below, which is handled by disclosure rather than by restricting the feature. `subject_user_id` stays explicit on every record regardless of activation mode; multi-account speaker attribution remains deferred and is covered by the shared-device disclaimer in the meantime.
10. **Wake-word listening must be a user-facing on/off setting, not an always-on default.** `activation` (only meaningful when `input_modality="voice"`) records which mode a given utterance used; separately, the user's account/settings must have an explicit `wake_word_enabled: bool` (default OFF until the user opts in, ideally during onboarding alongside the privacy disclaimer). Push-to-talk and text remain available regardless of this setting. The privacy disclaimer only makes sense if listening is something the user actively turned on — an always-on mic with no toggle undermines the disclosure it depends on.
11. **`input_modality` is a separate dimension from `activation`.** Barcode scans (Phase 2) and photo logging (Phase 4) are arrival channels, not voice-trigger modes — they must never be added as values inside `activation`, which stays scoped to how the microphone turned on. When `input_modality` is "photo" or "barcode", `activation` is null.
12. **`entry_mode="direct_macro"` is a distinct, legitimate state — not a resolution failure.** When a user directly dictates macros with no food to resolve ("just log 300 calories"), `food` is None by design and `resolution_status` should read "resolved" (not "unresolved"), since nothing was attempted and failed. Do not let UI code treat an empty `food` field as a bug — check `entry_mode` first.
13. **`users` collection needs a `subscription_tier` field reserved now** (nullable, unused until Stripe/freemium — Phase 3) so paywall-gating logic has somewhere to read from when it's built, and so the "accessibility/safety features are never paywalled" commitment (D5) is enforceable in code from day one rather than retrofitted alongside billing.
14. **Restriction/allergen evaluation MUST be decoupled from logging.** Today `check_allergy_block()` runs only on `POST /food` and `PATCH /food/{id}` — it is a logging-time gate. Extract the evaluation into a pure function:
    ```python
    def evaluate_restrictions(food_record, user_profile) -> RestrictionVerdict
    ```
    returning the verdict (allowed / warn / block) plus which tags fired, their three-state values, and their `evidence_basis`. The POST/PATCH gate becomes ONE CALLER among several. This is required because every one of these needs the same evaluation with NO logging: barcode scan-to-verdict ("can I eat this?" in a grocery aisle), voice allergen queries ("does that have peanuts?"), and any future recommendation or substitution feature. Cheap now; a real refactor once three features depend on the logging-coupled version.
15. **`users` needs `nutrient_display_preferences: list[str]`.** Progressive disclosure is not optional — voice output physically cannot read 84 nutrients aloud. This field determines which 3-5 nutrients lead. One field serves protein-priority (GLP-1/appetite-suppressed users), nutrient ceilings (CKD/sodium), and general voice brevity. Without it, every nutrient-surfacing decision gets hardcoded and has to be unwound later.
16. **`users` needs `contribution_consent: bool` (default False), and consumption data is never shared.** Paired with FoodEvent's `visibility` field. Policy: factual product data (UPC → product identity, transcribed nutrition panel) MAY be contributed to a shared database with consent, because it is verifiable fact about a package that exists in every store. User-generated content (custom food names, notes) requires explicit opt-in. **Consumption data — what a person ate, when, how much — is NEVER shared under any setting.** And allergen/safety determinations are NEVER crowdsourced into canonical status: community input may flag an item for review, it may never become the answer. That distinction is precisely what produced the public SnackSafely advisories against Fig and Sifter.
17. **Timezone-aware timestamps everywhere.** Store timezone-aware datetimes, or UTC plus an explicit user timezone on the profile — either is fine, but be consistent. There is an existing UTC-boundary bug (`read_today`/`calories_today` use midnight UTC, so US users get wrong results for several hours each evening); do not replicate that pattern in new code. A clinical export showing meals on the wrong day is worse than no export.
18. **Standards-mapping future-proofing is already satisfied — don't build more.** Retaining `usda_nutrient_id` per nutrient (hard rule / CHANGE 1), explicit units, stable `fdc_id` references, denormalized display values, and timezone-aware timestamps together make a future FHIR `NutritionIntake` mapping a lookup-table exercise rather than a data-archaeology project. **Do NOT implement FHIR now** — no OT or RD is ingesting FHIR from a consumer app; they want CSV and PDF. Export format is a pure rendering decision made whenever export ships.

## 4. Wiring

- `food_parser.parse_food_input` constructs and returns a FoodEvent (or a dict conforming to it — Pydantic model preferred for validation).
- `nutrition_service.lookup_food` populates database confidence, allergen_state, restriction_tags (from existing payload fields), resolution candidates.
- Routes (`POST /food`, voice route, PATCH) consume FoodEvent; the allergy gate reads allergen_state + restriction_tags identically (restriction blocks/warns use the same check_allergy_block pattern — generalize its signature to take the union of both dicts + user severity/strictness map).
- Mongo log documents store the full FoodEvent shape.
- Frontend contract: additive — existing fields keep their names/locations so current UI does not break; new fields are additions. Do not rename existing response keys in this spec.

## 5. Migration — full backfill (thorough path, chosen deliberately)

**Required first step — backup before touching anything:**
```bash
mongodump --uri="<atlas uri>" --collection=food_logs --out=./backups/premigration-$(date +%F)
```
Not optional. Confirm the dump completed and has a non-trivial file size before proceeding. Keep it at least one week past verified-successful migration, then it can be deleted — this is throwaway demo/test data, not user data, but the backup is cheap insurance against a bad field-mapping requiring a redo from originals, and the post-migration validation step below needs a before-state to diff against regardless.

One-time script `scripts/migrate_logs_to_food_event.py` upgrading every existing Mongo food-log document:
- Map existing fields directly where present (food, brand, calories, macros, nutrients, serving info).
- amount/unit: derive from existing serving_size/quantity_used where parseable; else amount=1.0, unit="count".
- All confidence keys: band="low", raw layers None (history can't tell us).
- provenance: every field "record_default".
- allergen_state: carry existing allergen fields; absent -> {} (not fabricated "free").
- restriction_tags/certification_status: {} (empty, honest).
- resolution_status: "resolved" (they were logged).

Disciplines (standing rules):
- Backup FIRST (see above) — verified before any write.
- Schema diff FIRST: dump 5-10 real existing documents, diff against target shape, confirm mapping before writing the script.
- TEST_MODE gate: script defaults to dry-run reporting counts + 3 sample transformed docs; explicit flag + user sign-off required for production writes.
- Post-run validation: count check (docs before == docs after), spot-check script verifying N random migrated docs parse as valid FoodEvent, diffed against the backup to confirm faithful representation of the original.

## 6. Testing (four-tier standard)

- Tier 1: FoodEvent round-trips through parse -> lookup -> log for a simple case ("banana"); all confidence keys present with bands; provenance populated.
- Tier 2: adjacent — typed input (asr=None path), voice input, hedged input ("I think it was chicken" -> provenance user_approximate), unresolved path (garbage input -> resolution_status unresolved, nothing logged), confidence-extraction-failure path (mock a broken logprobs response -> band low, log succeeds), multi-item utterance ("eggs, toast, and coffee" -> three FoodEvents in the food_events list, each with independent confidence), direct-macro entry ("log 300 calories" -> entry_mode="direct_macro", food=None, resolution_status="resolved" not "unresolved"), quantity_kind cases ("2 yogurts" -> quantity_kind="count" with unit_definition populated once confirmed; "2 cups of rice" -> quantity_kind="measure", unit_definition=None).
- Tier 3: promote all of the above to permanent pytest: tests/test_food_event_model.py (schema/validation, incl. item_type and visibility defaults), tests/test_confidence_capture.py (mocked API responses with known logprobs -> expected bands), tests/test_migration_food_event.py (sample old-shape docs -> valid new-shape), **tests/test_evaluate_restrictions.py (the decoupled pure function — verdict correctness for contains/free/unknown against block/warn strictness, called WITHOUT any logging occurring)**. Unit-marked, offline, in the default make test gate.
- Tier 4: voice AND text paths explicitly for every Tier 2 case above — this entire spec is shared-logic.

## 7. Out of scope for this spec (do not build here)

- Any confirmation/ask behavior changes (Spec 2 reads the bands; this spec only produces them).
- Verbosity settings (Spec 3).
- Recapture flow (Spec 4).
- Restriction-tag EXTRACTION runs over the 2M records (separate data-pipeline task after this lands; this spec only creates the fields and gate wiring).
- Combination rules (meat+dairy enforcement) and temporal/fasting overlays — deferred, documented in cultural-religious-dietary-restrictions.md.
- Threshold tuning — placeholder bands now, tuned against eval suite as a follow-up task.
