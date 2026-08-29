import json
import logging
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import ResponseHandlingException

from backend.services.query_match_rank import (
    effective_calories_per_100g,
    is_zero_calorie_query,
    rerank_matches_by_query,
)
from backend.services.dietary_filters import (
    FDA_ALLERGENS,
    build_tier_1_filter,
    has_active_allergen_constraint,
    relax_non_allergen_constraints,
    apply_tier_2_boosts,
    wants_lactose_avoidance,
    lactose_or_nested_filter,
    rank_lactose_preference,
    lactose_groups_need_clarification,
    lactose_contrastive_resolution,
)
from backend.services.nutrient_fields import extras_from_scaled, scale_extra_nutrients
from backend.models import DietaryPreferences

load_dotenv()

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
# Fail fast on a down store instead of hanging the parse/voice request.
# 5s was too tight: a 2M-point 3072-d search with unindexed allergen payload
# filters (or a grey/stalled-optimizer collection) measured ~11s and 503'd
# every log. Two _number_variants queries run sequentially, so keep headroom.
QDRANT_TIMEOUT_SECONDS = 20.0
COLLECTION_NAME = "food-vectors"
EMBEDDING_MODEL = "text-embedding-3-large"
SCORE_THRESHOLD = 0.3


class NutritionStoreUnavailable(Exception):
    """Qdrant timed out or could not be reached."""


# Alternatives can be slightly weaker matches than the primary result — we
# still want to offer them, just not obvious garbage. Kept below
# SCORE_THRESHOLD so the "Did you mean?" list isn't empty for near-ties.
CANDIDATE_SCORE_FLOOR = 0.2
MAX_CANDIDATES = 5
MAX_PORTION_OPTIONS = 8

# Broaden retrieval so the candidate pool actually represents the food's
# variation (whole vs skim milk, etc.) instead of just the 5 nearest names.
# Cheap on the query side and needs no re-embedding.
RETRIEVAL_TOP_K = 25

# Brand-vs-generic disambiguation. When the user tells us whether they want a
# specific brand or a general item, we restrict retrieval to the matching
# `source` values stored at embed time.
#
# NOTE (2026-08-04): these values were updated to match what the Qdrant
# embedding script (embed_all_to_qdrant.py) actually wrote to the `source`
# payload field -- "sr_legacy" / "fndds" / "branded_foods", not the
# "usda_"-prefixed names the old Pinecone-era code used. Worth a live
# spot-check against real payload data (e.g. via lookup_single_fdc_id.py)
# before trusting this in production -- this is reconstructed from memory
# of the embedding script, not verified against a live query here.
SOURCE_GROUPS = {
    "generic": ["sr_legacy", "fndds"],
    "brand": ["branded_foods"],
}

NONE_MODIFIER = "NONE"

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
qdrant_client = QdrantClient(url=QDRANT_URL, timeout=QDRANT_TIMEOUT_SECONDS)


# ============================================================================
# QDRANT FILTER BUILDERS
# (replaces the old _source_pinecone_filter / _modifiers_pinecone_filter /
#  _combine_pinecone_filters — same job, native Qdrant syntax instead of the
#  Pinecone/MongoDB-style $and/$in dicts, which are invalid against Qdrant)
# ============================================================================

def _source_qdrant_condition(source_filter: str | None) -> qmodels.FieldCondition | None:
    sources = SOURCE_GROUPS.get((source_filter or "").lower())
    if not sources:
        return None
    return qmodels.FieldCondition(key="source", match=qmodels.MatchAny(any=sources))


def _modifiers_qdrant_conditions(modifiers: dict | None) -> list[qmodels.FieldCondition]:
    """Build Qdrant FieldConditions from the 13 extracted query modifiers
    (cooking_method, skin_status, sodium_level, etc). Only non-NONE values
    become hard filters."""
    if not modifiers:
        return []
    return [
        qmodels.FieldCondition(key=category, match=qmodels.MatchValue(value=value))
        for category, value in modifiers.items()
        if value and value != NONE_MODIFIER
    ]


def _combine_filters(
    source_condition: qmodels.FieldCondition | None,
    modifier_conditions: list[qmodels.FieldCondition],
    tier_1_filter: qmodels.Filter | None,
) -> qmodels.Filter | None:
    """
    Merge source + modifier conditions (both simple `must` clauses) with the
    Tier 1 dietary filter (which may carry its own must_not clauses for
    allergen exclusion). Qdrant filters combine by merging must/must_not
    lists, not by nesting Filter objects inside each other.
    """
    must: list = []
    must_not: list = []

    if source_condition:
        must.append(source_condition)
    must.extend(modifier_conditions)

    if tier_1_filter:
        if tier_1_filter.must:
            must.extend(tier_1_filter.must)
        if tier_1_filter.must_not:
            must_not.extend(tier_1_filter.must_not)

    if not must and not must_not:
        return None

    return qmodels.Filter(
        must=must if must else None,
        must_not=must_not if must_not else None,
    )


# --- Resolver tuning -------------------------------------------------------
# A food is "resolved" when its plausible interpretations agree on calories
# closely enough that asking the user wouldn't change the logged number.
# It's only worth a clarifying question when the spread exceeds BOTH a
# relative and an absolute floor (so we ignore trivial gaps like 100 vs 108).
CALORIE_CONVERGENCE_RATIO = 0.20   # 20% spread between cheapest and priciest
CALORIE_CONVERGENCE_ABS = 20       # ...but never bother over gaps under 20 cal
RESOLVER_SAMPLE_SIZE = 4           # how many top candidate foods to weigh

# Phrases that indicate a food's serving size = the whole container, not a
# single portion (e.g. "PER CAN"). Affects ~0.6% of branded foods — rare, but
# worth surfacing so the app/UI can note it rather than silently treating a
# whole-container amount as a typical single serving.
WHOLE_CONTAINER_PHRASES = ["per can", "per container", "per bottle", "per package", "per bag", "per jar"]


def is_whole_container_serving(household_serving_fulltext: str) -> bool:
    text = (household_serving_fulltext or "").strip().lower()
    return any(phrase in text for phrase in WHOLE_CONTAINER_PHRASES)


def _parse_portions(metadata: dict) -> list[dict]:
    """SR Legacy foods store multiple portions as a JSON string; branded
    foods don't carry this field. Returns [] when absent/unparseable."""
    portions_raw = metadata.get("portions_json")
    if not portions_raw:
        return []
    try:
        portions = json.loads(portions_raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return portions if isinstance(portions, list) else []


def _sanitize_serving_size_g(serving_size_g: float) -> tuple[float, str | None]:
    """Fix implausibly small branded serving weights.

    Some USDA branded rows store grams off by 1000 (e.g. 0.056 instead of 56),
    which scales a real 125 kcal/100g food down to ~0.07 kcal per serving.
    If ×1000 lands in a normal serving range, use that; otherwise fall back
    to 100g so we never silently log ~0 for a caloric food.
    """
    try:
        grams = float(serving_size_g)
    except (TypeError, ValueError):
        return 100.0, "serving_size_g_invalid_fallback"
    if grams >= 1.0:
        return grams, None
    if grams <= 0:
        return 100.0, "serving_size_g_nonpositive_fallback"
    bumped = grams * 1000.0
    if 5.0 <= bumped <= 2000.0:
        return bumped, "serving_size_g_x1000_fix"
    return 100.0, "serving_size_g_implausible_fallback"


def get_serving_size_g(metadata: dict) -> tuple[float, str]:
    """
    Returns (serving_size_g, source_label). Handles both dataset shapes:
    - Branded foods: a single serving_size_g field directly in metadata.
    - SR Legacy foods: a portions_json field with multiple named portion
      options, none of which is "the" serving size the way a label declares
      one — so we pick a default (first available) portion.
    Falls back to 100 (i.e. return raw per-100g values, unscaled) only if
    neither is present, so behavior is at least predictable, not silently
    wrong, for any food this doesn't yet handle.
    """
    raw = metadata.get("serving_size_g")
    if raw is not None and raw != "":
        try:
            raw_f = float(raw)
        except (TypeError, ValueError):
            raw_f = None
        if raw_f is not None and raw_f != 0:
            grams, fix = _sanitize_serving_size_g(raw_f)
            if fix:
                return grams, fix
            return grams, "branded_serving_size"

    for portion in _parse_portions(metadata):
        gram_weight = portion.get("gram_weight")
        if gram_weight:
            grams, fix = _sanitize_serving_size_g(gram_weight)
            if fix:
                return grams, fix
            return grams, "sr_legacy_default_portion"

    return 100, "no_serving_data_fallback"


def record_display_name(metadata: dict | None) -> str:
    """Human-readable name from payload. Qdrant stores `description` at embed
    time; nutrition backfill may also set `name`. Either is usable."""
    meta = metadata or {}
    return str(meta.get("name") or meta.get("description") or "").strip()


def is_phantom_record(metadata: dict | None) -> bool:
    """True for searchable-but-unusable rows: 100g serving fallback plus
    either no calories or no display name.

    These are typically branded vectors that were embedded from a description
    but never received nutrition backfill. They can still score 0.70–0.80
    against a real query because the description embedding is fine — only
    the nutrition payload is empty. They must never silently resolve.
    """
    meta = metadata or {}
    _, serving_source = get_serving_size_g(meta)
    if serving_source != "no_serving_data_fallback":
        return False
    name = record_display_name(meta)
    calories = scale_nutrients(meta, 100.0).get("calories")
    try:
        cal_f = float(calories) if calories is not None else 0.0
    except (TypeError, ValueError):
        cal_f = 0.0
    return (not name) or cal_f <= 0.5


def is_phantom_match(match: dict | None) -> bool:
    if not match:
        return True
    return is_phantom_record(match.get("metadata") or {})


def filter_phantom_matches(matches: list[dict]) -> list[dict]:
    """Drop phantom rows from the retrieved set so they cannot win or appear
    as the only clarification options."""
    return [m for m in matches if not is_phantom_match(m)]


def is_phantom_lookup_result(nutrition: dict | None) -> bool:
    """Same guard on the lookup_food return shape (parser safety net)."""
    if not nutrition:
        return False
    if nutrition.get("serving_source") != "no_serving_data_fallback":
        return False
    name = str(
        nutrition.get("food_name") or nutrition.get("name") or ""
    ).strip()
    try:
        cal_f = float(nutrition.get("calories") if nutrition.get("calories") is not None else 0)
    except (TypeError, ValueError):
        cal_f = 0.0
    return (not name) or cal_f <= 0.5


def scale_nutrients(metadata: dict, serving_size_g: float) -> dict:
    """Qdrant stores nutrient values per 100g. Scale them to the given
    serving size in grams. Central helper so the primary result, the
    candidate list, and each portion option all compute calories the exact
    same way.

    When the calorie field is missing/0 but macros are present (common in
    branded USDA rows), calories are estimated with Atwater (4P+4C+9F).
    Also scales fiber/sugar/micros into the same dict for logging/summary.
    """
    multiplier = serving_size_g / 100
    calories_100 = effective_calories_per_100g(metadata)
    protein_100 = float(metadata.get("protein") or 0)
    carbs_100 = float(metadata.get("carbs") or 0)
    fat_100 = float(metadata.get("fat") or 0)
    scaled = {
        "calories": round((calories_100 or 0) * multiplier, 2),
        "protein": round(protein_100 * multiplier, 2),
        "carbs": round(carbs_100 * multiplier, 2),
        "fat": round(fat_100 * multiplier, 2),
    }
    scaled.update(scale_extra_nutrients(metadata, serving_size_g))
    return scaled



def _pick_match_with_usable_calories(query: str, matches: list[dict]) -> dict | None:
    """Prefer a hit whose effective calories aren't a degenerate zero.

    For caloric foods, skip rows that are still ~0 after Atwater. Zero-cal
    queries (water, black coffee, …) keep the top lexical hit that is not a
    phantom record. Never fall back to a phantom — return None so lookup
    misses instead of logging 0 calories.
    """
    usable = [m for m in matches if not is_phantom_match(m)]
    if not usable:
        return None
    if is_zero_calorie_query(query):
        return usable[0]
    for match in usable:
        if match.get("score", 0) < SCORE_THRESHOLD:
            continue
        cal = effective_calories_per_100g(match.get("metadata") or {})
        if cal is not None and cal > 0.5:
            return match
    return None


def get_brand(metadata: dict) -> str:
    """Branded foods carry brand info; SR Legacy foods don't. Empty string
    for generic/whole foods so callers can treat it as 'no brand'."""
    return (metadata.get("brand_name") or metadata.get("brand_owner") or "").strip()


def format_branded_name(name: str | None, brand: str | None) -> str:
    """Join brand + name for display/speech without duplicating brand.

    Branded `name` often already starts with brand_name (e.g.
    'GREAT VALUE POTATO CHIPS'). Callers that also have a separate `brand`
    field must not prepend again — that produces 'Great Value Great Value…'.
    Comparison is case-insensitive substring, matching process_branded.py.
    """
    name = (name or "").strip()
    brand = (brand or "").strip()
    if not brand:
        return name
    if brand.lower() in name.lower():
        return name
    return f"{brand} {name}"


# Serving-size-looking strings that are not real food names (e.g. "100 g").
_PLACEHOLDER_FOOD_NAME_RE = re.compile(
    r"^\d+(\.\d+)?\s*(g|gram|grams|oz|onz|ounce|ounces|ml|l|cup|cups|piece|pieces)?\.?$",
    re.IGNORECASE,
)


def _candidate_display_name(c: dict) -> str:
    return format_branded_name(c.get("name"), c.get("brand")).strip()


def _candidate_calories_int(c: dict) -> int:
    try:
        return int(round(float(c.get("calories") or 0)))
    except (TypeError, ValueError):
        return 0


def _candidate_dedupe_key(c: dict) -> str:
    """Same product + same logged calories → one clarification row."""
    name = _candidate_display_name(c).lower()
    serving = (c.get("serving_label") or "").strip().lower()
    return f"{name}|{serving}|{_candidate_calories_int(c)}"


def _candidate_soft_dedupe_key(c: dict) -> str:
    """Collapse SKU clones that only differ on serving label wording."""
    name = _candidate_display_name(c).lower()
    return f"{name}|{_candidate_calories_int(c)}"


def _is_junk_clarification_candidate(c: dict, *, allow_zero_cal: bool) -> bool:
    name = (c.get("name") or "").strip()
    display = _candidate_display_name(c)
    if not name or not display:
        return True
    if _PLACEHOLDER_FOOD_NAME_RE.match(name) or _PLACEHOLDER_FOOD_NAME_RE.match(display):
        return True
    if len(display) < 2:
        return True
    if not allow_zero_cal and _candidate_calories_int(c) <= 0:
        return True
    return False


def clean_clarification_candidates(
    candidates: list[dict],
    *,
    primary: dict | None = None,
    query: str = "",
) -> list[dict]:
    """Drop junk/0-cal rows, exclude the primary pick, and dedupe display clones.

    Used before assess_resolution and returned to the client so identity
    clarification is not a wall of identical branded SKUs.
    """
    allow_zero = is_zero_calorie_query(query)
    primary_id = None
    primary_key = None
    primary_soft = None
    if primary:
        if primary.get("fdc_id") is not None:
            primary_id = str(primary["fdc_id"])
        primary_key = _candidate_dedupe_key(primary)
        primary_soft = _candidate_soft_dedupe_key(primary)

    seen_full: set[str] = set()
    seen_soft: set[str] = set()
    out: list[dict] = []
    for c in candidates:
        if primary_id is not None and str(c.get("fdc_id")) == primary_id:
            continue
        if _is_junk_clarification_candidate(c, allow_zero_cal=allow_zero):
            continue
        full_key = _candidate_dedupe_key(c)
        soft_key = _candidate_soft_dedupe_key(c)
        if primary_key and full_key == primary_key:
            continue
        if primary_soft and soft_key == primary_soft:
            continue
        if full_key in seen_full or soft_key in seen_soft:
            continue
        seen_full.add(full_key)
        seen_soft.add(soft_key)
        out.append(c)
    return out


_NUMERIC_PORTION_TOKEN_RE = re.compile(r"^\d+$")
_UNUSABLE_PORTION_DESC = {"quantity not specified", "not specified", ""}


def _is_numeric_portion_token(value: str) -> bool:
    """FNDDS stores measure-unit *codes* in modifier (e.g. '60343')."""
    return bool(_NUMERIC_PORTION_TOKEN_RE.match((value or "").strip()))


def _portion_description_usable(description: str) -> bool:
    return description.strip().lower() not in _UNUSABLE_PORTION_DESC


def _format_portion_label(portion: dict) -> str:
    """Build a human-readable label from a portion row.

    Dataset shapes differ:
    - SR Legacy: amount + text modifier ('cup, mashed') → '1 cup, mashed'
    - FNDDS: description is already the full phrase ('1 banana'); modifier is
      a numeric measure code and must NOT be shown as the unit.
    """
    modifier = (portion.get("modifier") or "").strip()
    unit = (portion.get("unit") or "").strip()
    description = (portion.get("description") or "").strip()

    # Survey/FNDDS rows: prefer the ready-made household phrase.
    if _portion_description_usable(description):
        return description

    if modifier and not _is_numeric_portion_token(modifier):
        unit_part = modifier
    elif unit and unit.lower() != "undetermined":
        unit_part = unit
    else:
        unit_part = "serving"

    try:
        amount_f = float(portion.get("amount")) if portion.get("amount") is not None else 1.0
    except (TypeError, ValueError):
        amount_f = 1.0
    if amount_f <= 0:
        amount_f = 1.0

    # Avoid "1 1 cup" if a description slipped through without the early return.
    if re.match(r"^\d", unit_part):
        return unit_part
    return f"{amount_f:g} {unit_part}".strip()


def build_serving_label(metadata: dict, serving_size_g: float, serving_source: str) -> str:
    """One-line description of the serving the primary calories are based on.
    Prefers the branded household text (e.g. '1 cup (240 ml)'), then the
    default SR portion label, then a plain gram amount."""
    if serving_source == "branded_serving_size":
        household = (metadata.get("household_serving_fulltext") or "").strip()
        if household:
            return household
        return f"{serving_size_g:g} g"

    if serving_source == "sr_legacy_default_portion":
        for portion in _parse_portions(metadata):
            if not portion.get("gram_weight"):
                continue
            description = (portion.get("description") or "").strip()
            # Skip FNDDS placeholder rows when a real named portion exists later.
            if description and not _portion_description_usable(description):
                continue
            return _format_portion_label(portion)

    return f"{serving_size_g:g} g"


def build_portion_options(metadata: dict) -> list[dict]:
    """The 'how much?' axis, straight from the data. For SR Legacy foods this
    is every named portion (medium/large/cup...) with its own calories; for
    branded foods it's the single label serving. Each option is enough to log
    directly without re-parsing."""
    options: list[dict] = []

    portions = _parse_portions(metadata)
    if portions:
        seen_grams: set[float] = set()
        for portion in portions:
            grams = portion.get("gram_weight")
            if not grams or grams in seen_grams:
                continue
            description = (portion.get("description") or "").strip()
            if description and not _portion_description_usable(description):
                continue
            label = _format_portion_label(portion)
            # Never offer measure-code leftovers like "1 60343".
            if _is_numeric_portion_token(label.split()[-1] if label else ""):
                continue
            seen_grams.add(grams)
            macros = scale_nutrients(metadata, grams)
            options.append({
                "label": label,
                "gram_weight": grams,
                **macros,
            })
        options.sort(key=lambda o: o["gram_weight"])
        return options[:MAX_PORTION_OPTIONS]

    # Branded (or anything with a single serving_size_g): one option.
    serving_size_g, serving_source = get_serving_size_g(metadata)
    macros = scale_nutrients(metadata, serving_size_g)
    options.append({
        "label": build_serving_label(metadata, serving_size_g, serving_source),
        "gram_weight": serving_size_g,
        **macros,
    })
    return options


def summarize_match(match: dict) -> dict:
    """Turn a raw match into a grounded, loggable candidate: real name,
    brand, serving label, and calories/macros scaled to its default serving.
    This is what powers data-driven 'Did you mean?' alternatives."""
    metadata = match.get("metadata", {})
    serving_size_g, serving_source = get_serving_size_g(metadata)
    macros = scale_nutrients(metadata, serving_size_g)
    household = metadata.get("household_serving_fulltext", "")
    return {
        "fdc_id": match.get("id"),
        "name": record_display_name(metadata) or None,
        "brand": get_brand(metadata),
        "serving_label": build_serving_label(metadata, serving_size_g, serving_source),
        "serving_size_g": serving_size_g,
        "serving_source": serving_source,
        "serving_note": "This serving size represents the entire container." if is_whole_container_serving(household) else None,
        "score": round(match.get("score", 0), 4),
        "source": metadata.get("source"),
        **macros,
    }


def _calorie_spread(values: list) -> dict:
    """Measure how far apart a set of calorie numbers are, and decide whether
    that gap is big enough to matter. 'Ratio' is measured against the smaller
    value so an 83 -> 149 jump reads as ~80% (meaningful), not ~44%."""
    vals = [v for v in values if v is not None]
    if not vals:
        return {"min": 0.0, "max": 0.0, "diverges": False}
    lo, hi = min(vals), max(vals)
    abs_gap = hi - lo
    ratio = (abs_gap / lo) if lo > 0 else float("inf")
    diverges = abs_gap > CALORIE_CONVERGENCE_ABS and ratio > CALORIE_CONVERGENCE_RATIO
    return {"min": round(lo, 1), "max": round(hi, 1), "diverges": diverges}


def _build_question(options: list[dict], chosen_name: str, limit: int = 3) -> str:
    """A single, bounded clarifying question — with a 'typical' escape hatch so
    the user is never trapped in the choice."""
    shown = [o for o in options[:limit] if o.get("calories") is not None]
    if not shown:
        return f"Which {chosen_name} did you mean?"
    listed = "; ".join(
        f"{o['label']} ({int(round(o['calories']))} cal)" for o in shown
    )
    return f"Did you mean {listed}? Or say 'typical' to use {chosen_name} as-is."


def assess_resolution(
    chosen_name: str, candidates: list[dict], portion_options: list[dict]
) -> dict:
    """Consolidated disambiguation check — the single place that decides
    'log it' vs 'ask one question', for BOTH kinds of ambiguity:

      1. identity — do the top candidate *foods* disagree on calories?
                    (e.g. "milk": skim ~83 vs whole ~149)
      2. amount   — do the chosen food's *portions* disagree?
                    (e.g. "banana": medium 105 vs 1 cup mashed 200)

    It compares only calories (the number the user actually logs) and stops as
    soon as the remaining spread wouldn't change that number. Fully
    deterministic — no extra model call.
    """
    sample = candidates[:RESOLVER_SAMPLE_SIZE]
    identity = _calorie_spread([c.get("calories") for c in sample])
    amount = _calorie_spread([p.get("calories") for p in portion_options])

    identity_gap = identity["max"] - identity["min"]
    amount_gap = amount["max"] - amount["min"]

    if identity["diverges"] and identity_gap >= amount_gap:
        options = [
            {
                "label": format_branded_name(c.get("name"), c.get("brand")),
                "calories": c.get("calories"),
                "kind": "food",
            }
            for c in sample
        ]
        return {
            "status": "needs_clarification",
            "axis": "identity",
            "reason": f"“{chosen_name}” could be different foods with very different calories.",
            "question": _build_question(options, chosen_name),
            "options": options,
            "identity_spread": identity,
            "amount_spread": amount,
        }

    if amount["diverges"]:
        options = [
            {"label": p.get("label"), "calories": p.get("calories"), "kind": "portion"}
            for p in portion_options
        ]
        return {
            "status": "needs_clarification",
            "axis": "amount",
            "reason": f"The amount of {chosen_name} changes the calories a lot.",
            "question": _build_question(options, chosen_name),
            "options": options,
            "identity_spread": identity,
            "amount_spread": amount,
        }

    return {
        "status": "resolved",
        "axis": None,
        "reason": "Top matches agree on calories closely enough to log directly.",
        "question": None,
        "options": [],
        "identity_spread": identity,
        "amount_spread": amount,
    }


def _pluralize(word: str) -> str:
    """Best-effort English pluralization. Doesn't need to be perfect — a wrong
    guess just produces a variant that scores lower and gets discarded."""
    lower = word.lower()
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if lower.endswith("y") and len(word) > 1 and word[-2].lower() not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _singularize(word: str) -> str:
    """Best-effort inverse of _pluralize, same 'wrong guess is harmless' logic."""
    lower = word.lower()
    if lower.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if lower.endswith(("ches", "shes", "xes", "zes", "ses")):
        return word[:-2]
    if lower.endswith("s") and not lower.endswith("ss") and len(word) > 1:
        return word[:-1]
    return word


def _number_variants(query: str) -> list[str]:
    """Original query plus its grammatical-number toggle, applied to the head
    noun (the LAST word, e.g. 'chicken breast' -> 'chicken breasts'). Returns
    [original] or [original, toggled]."""
    query = query.strip()
    if not query:
        return [query]
    parts = query.split()
    head = parts[-1]
    head_lower = head.lower()
    looks_plural = head_lower.endswith("s") and not head_lower.endswith("ss")
    toggled = _singularize(head) if looks_plural else _pluralize(head)
    alt = " ".join(parts[:-1] + [toggled]).strip()
    if alt and alt.lower() != query.lower():
        return [query, alt]
    return [query]


def _qdrant_results_to_matches(results) -> list[dict]:
    """
    Convert Qdrant ScoredPoint objects into the {id, score, metadata} dict
    shape the rest of this file already expects. This is the ONE place that
    bridges Qdrant's object-attribute API to the existing dict-based logic,
    so summarize_match / assess_resolution / etc. needed zero changes.

    Uses payload["qdrant_id"] (the original fdc_id, stored at embed time) as
    "id" — NOT Qdrant's internal point id, which is meaningless outside Qdrant.
    """
    matches = []
    for point in results:
        payload = point.payload or {}
        matches.append({
            "id": payload.get("qdrant_id"),
            "score": point.score,
            "metadata": payload,
        })
    return matches


async def _retrieve_best(
    query: str, qdrant_filter: qmodels.Filter | None = None
) -> tuple[list[dict], str]:
    """Try the query and its number variant, and keep whichever one's TOP
    match scores highest. Both variants are embedded in a SINGLE batched
    OpenAI call (input accepts a list), so this adds Qdrant queries but not
    extra embedding round-trips. Taking the max score means a bad variant can
    only be ignored, never degrade the result. `qdrant_filter` (optional)
    restricts results by payload, e.g. brand-vs-generic source, dietary
    constraints."""
    variants = _number_variants(query)

    embedding_response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=variants,
    )
    vectors = [item.embedding for item in embedding_response.data]

    best_matches: list[dict] = []
    best_score = -1.0
    best_variant = query
    for variant, vector in zip(variants, vectors):
        # NOTE (2026-08-05): qdrant_client.search() was renamed to
        # query_points() in this client version -- .search() doesn't exist
        # at all here, confirmed against a real AttributeError during the
        # first live end-to-end test. query_points() returns a QueryResponse
        # object with a .points attribute (not a bare list like .search() did).
        try:
            response = qdrant_client.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=RETRIEVAL_TOP_K,
                query_filter=qdrant_filter,
                with_payload=True,
            )
        except (ResponseHandlingException, TimeoutError, OSError, ConnectionError) as exc:
            logger.warning(
                "Qdrant query failed (%s): %r",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise NutritionStoreUnavailable("Nutrition search is temporarily unavailable.") from exc
        matches = _qdrant_results_to_matches(response.points)
        top_score = matches[0]["score"] if matches else 0
        if top_score > best_score:
            best_score = top_score
            best_matches = matches
            best_variant = variant

    return best_matches, best_variant


async def lookup_food(
    query: str,
    source_filter: str | None = None,
    modifiers: dict | None = None,
    dietary_preferences: DietaryPreferences | None = None,
) -> dict | None:
    """
    dietary_preferences is passed in by the caller (route layer), already
    fetched from the user's UserProfile — this function stays DB-agnostic
    and testable without a live Mongo connection.
    """
    print("RAG query:", query, "| source_filter:", source_filter)

    tier_1 = dietary_preferences.tier_1 if dietary_preferences else None
    tier_2 = dietary_preferences.tier_2 if dietary_preferences else None

    source_condition = _source_qdrant_condition(source_filter)
    modifier_conditions = _modifiers_qdrant_conditions(modifiers)
    tier_1_filter = build_tier_1_filter(tier_1)
    combined_filter = _combine_filters(source_condition, modifier_conditions, tier_1_filter)
    lactose_active = wants_lactose_avoidance(query, tier_1)
    if lactose_active and not (tier_1 is not None and getattr(tier_1, "lactose_free", False)):
        extra = lactose_or_nested_filter()
        if combined_filter is None:
            combined_filter = qmodels.Filter(must=[extra])
        else:
            must = list(combined_filter.must or [])
            must.append(extra)
            combined_filter = qmodels.Filter(
                must=must or None,
                must_not=combined_filter.must_not,
            )

    print("RAG tier_1 filter:", tier_1_filter)
    print("RAG combined filter:", combined_filter)

    matches, winning_variant = await _retrieve_best(query, combined_filter)
    retrieval_top1 = matches[0]["score"] if matches else None
    retrieval_top2 = matches[1]["score"] if matches and len(matches) > 1 else None
    retrieval_gap = (
        retrieval_top1 - retrieval_top2
        if retrieval_top1 is not None and retrieval_top2 is not None
        else None
    )

    # Zero results: only fall back if it's SAFE to. If any allergen is
    # active, never relax -- tell the caller explicitly rather than silently
    # retrying with a weaker filter. This is the exact failure mode the
    # allergen extraction work tonight was scoped to prevent.
    used_fallback = False
    if not matches:
        if has_active_allergen_constraint(tier_1):
            return {
                "blocked_by_allergy": True,
                "message": "I couldn't find any options matching your allergy requirements. "
                           "I've withheld unsafe options for your safety.",
            }
        if tier_1 is not None:
            relaxed_tier_1 = relax_non_allergen_constraints(tier_1)
            if relaxed_tier_1 is not None:
                relaxed_filter = _combine_filters(
                    source_condition, modifier_conditions, build_tier_1_filter(relaxed_tier_1)
                )
                matches, winning_variant = await _retrieve_best(query, relaxed_filter)
                used_fallback = True
                retrieval_top1 = matches[0]["score"] if matches else None
                retrieval_top2 = matches[1]["score"] if matches and len(matches) > 1 else None
                retrieval_gap = (
                    retrieval_top1 - retrieval_top2
                    if retrieval_top1 is not None and retrieval_top2 is not None
                    else None
                )

    if not matches:
        return None

    if winning_variant.strip().lower() != query.strip().lower():
        print(f"RAG: variant '{winning_variant}' outscored original '{query}'")

    # Vector score alone often buries the everyday food (e.g. "Bananas, raw")
    # under chips/branded neighbors. Re-rank by how closely the name matches
    # what the user said (plus a small near-zero-kcal demotion for caloric
    # foods) before picking the primary + candidate list.
    matches = rerank_matches_by_query(query, matches)

    # Tier 2 soft preferences (organic, keto, grass-fed, ...) get the final
    # polish pass -- boosts ranking within the semantically/name relevant
    # set, never overrides it (capped multiplicative boost).
    matches = apply_tier_2_boosts(matches, tier_2)
    if lactose_active:
        matches = rank_lactose_preference(matches)

    matches = filter_phantom_matches(matches)

    match = _pick_match_with_usable_calories(query, matches)
    if match is None or match.get("score", 0) < SCORE_THRESHOLD:
        return None
    if is_phantom_match(match):
        return None

    metadata = match.get("metadata", {})
    fdc_id = match["id"]
    display_name = record_display_name(metadata) or None

    print(
        f"Top match: {display_name} — score: {match['score']} "
        f"(after query-match re-rank)"
    )

    serving_size_g, serving_source = get_serving_size_g(metadata)
    macros = scale_nutrients(metadata, serving_size_g)
    calories = macros["calories"]
    if is_phantom_record(metadata):
        return None
    protein = macros["protein"]
    carbs = macros["carbs"]
    fat = macros["fat"]
    nutrients = extras_from_scaled(macros)

    print(f"fdc_id: {fdc_id}, serving_size_g: {serving_size_g} (source: {serving_source}), calories: {calories}")

    household_serving_fulltext = metadata.get("household_serving_fulltext", "")
    whole_container = is_whole_container_serving(household_serving_fulltext)

    serving_label = build_serving_label(metadata, serving_size_g, serving_source)
    primary_summary = {
        "fdc_id": fdc_id,
        "name": display_name,
        "brand": get_brand(metadata),
        "serving_label": serving_label,
        "calories": calories,
    }

    # Over-fetch then clean: branded indexes often return several SKUs that
    # collapse to the same display name/calories after formatting.
    raw_candidates = [
        summarize_match(m)
        for m in matches
        if m.get("score", 0) >= CANDIDATE_SCORE_FLOOR
    ][: MAX_CANDIDATES * 4]
    candidates = clean_clarification_candidates(
        raw_candidates,
        primary=primary_summary,
        query=query,
    )[:MAX_CANDIDATES]

    portion_options = build_portion_options(metadata)

    resolution = assess_resolution(display_name, candidates, portion_options)
    if lactose_active and lactose_groups_need_clarification(matches):
        resolution = lactose_contrastive_resolution()
    print(
        f"resolution: {resolution['status']}"
        + (f" (ask about {resolution['axis']})" if resolution["axis"] else "")
    )

    # Allergen tags for the route-layer severe/moderate gate (create + PATCH).
    # CONTAINS → listed in allergens; per-allergen state keys kept so UNKNOWN
    # can still drive a moderate warning without blocking.
    allergens_present = [
        name for name in FDA_ALLERGENS if metadata.get(name) == "CONTAINS"
    ]
    allergen_states = {
        name: metadata.get(name)
        for name in FDA_ALLERGENS
        if metadata.get(name) in ("CONTAINS", "FREE", "UNKNOWN")
    }

    return {
        "food_name": display_name,
        "brand": get_brand(metadata),
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "serving_size_g": serving_size_g,
        "serving_source": serving_source,
        "serving_label": serving_label,
        "serving_note": "This serving size represents the entire container." if whole_container else None,
        "source": "usda_rag",
        "candidates": candidates,
        "portion_options": portion_options,
        "resolution": resolution,
        "used_dietary_fallback": used_fallback,
        "nutrients": nutrients,
        "allergens": allergens_present,
        # Spec 1 database confidence layer — stop discarding retrieval scores.
        "database_score": match.get("score"),
        "database_score_gap": retrieval_gap,
        "database_score_top1": retrieval_top1,
        "database_score_top2": retrieval_top2,
        **allergen_states,
    }