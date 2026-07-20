import json
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pinecone import Pinecone

from backend.services.query_match_rank import (
    effective_calories_per_100g,
    is_zero_calorie_query,
    rerank_matches_by_query,
)
# import httpx  # kept for potential future use — see commented fallback block below

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY").strip()
USDA_API_KEY = os.getenv("USDA_API_KEY")  # unused now, kept for the commented fallback below
INDEX_NAME = "food-index"
EMBEDDING_MODEL = "text-embedding-3-large"
SCORE_THRESHOLD = 0.3
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
# `source` values stored at embed time. "generic" spans SR Legacy and (once
# embedded) FNDDS; "brand" is the branded-foods dataset. Applied as a Pinecone
# metadata filter so the candidate/portion list is built from a single, clean
# source — not a mixed pile of brands, generics, and substitutes.
SOURCE_GROUPS = {
    "generic": ["usda_sr_legacy", "usda_fndds"],
    "brand": ["usda_branded_foods"],
}


def _source_pinecone_filter(source_filter: str | None) -> dict | None:
    sources = SOURCE_GROUPS.get((source_filter or "").lower())
    return {"source": {"$in": sources}} if sources else None

# --- Resolver tuning -------------------------------------------------------
# A food is "resolved" when its plausible interpretations agree on calories
# closely enough that asking the user wouldn't change the logged number.
# It's only worth a clarifying question when the spread exceeds BOTH a
# relative and an absolute floor (so we ignore trivial gaps like 100 vs 108).
CALORIE_CONVERGENCE_RATIO = 0.20   # 20% spread between cheapest and priciest
CALORIE_CONVERGENCE_ABS = 20       # ...but never bother over gaps under 20 cal
RESOLVER_SAMPLE_SIZE = 4           # how many top candidate foods to weigh

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)

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


def scale_nutrients(metadata: dict, serving_size_g: float) -> dict:
    """Pinecone stores nutrient values per 100g. Scale them to the given
    serving size in grams. Central helper so the primary result, the
    candidate list, and each portion option all compute calories the exact
    same way.

    When the calorie field is missing/0 but macros are present (common in
    branded USDA rows), calories are estimated with Atwater (4P+4C+9F).
    """
    multiplier = serving_size_g / 100
    calories_100 = effective_calories_per_100g(metadata)
    protein_100 = float(metadata.get("protein") or 0)
    carbs_100 = float(metadata.get("carbs") or 0)
    fat_100 = float(metadata.get("fat") or 0)
    return {
        "calories": round((calories_100 or 0) * multiplier, 2),
        "protein": round(protein_100 * multiplier, 2),
        "carbs": round(carbs_100 * multiplier, 2),
        "fat": round(fat_100 * multiplier, 2),
    }


def _pick_match_with_usable_calories(query: str, matches: list[dict]) -> dict | None:
    """Prefer a hit whose effective calories aren't a degenerate zero.

    For caloric foods, skip rows that are still ~0 after Atwater. Zero-cal
    queries (water, black coffee, …) keep the top lexical hit.
    """
    if not matches:
        return None
    if is_zero_calorie_query(query):
        return matches[0]
    for match in matches:
        if match.get("score", 0) < SCORE_THRESHOLD:
            continue
        cal = effective_calories_per_100g(match.get("metadata") or {})
        if cal is not None and cal > 0.5:
            return match
    # Nothing usable — return top match and let the parser refuse high-confidence.
    return matches[0]


def get_brand(metadata: dict) -> str:
    """Branded foods carry brand info; SR Legacy foods don't. Empty string
    for generic/whole foods so callers can treat it as 'no brand'."""
    return (metadata.get("brand_name") or metadata.get("brand_owner") or "").strip()


def _format_portion_label(portion: dict) -> str:
    """Build a human-readable label from an SR Legacy portion row, e.g.
    '1 cup, mashed' or '1 medium (7" to 7-7/8" long)'. Falls back through
    modifier -> unit -> description -> 'serving' so we always say something."""
    amount = portion.get("amount") or 1
    modifier = (portion.get("modifier") or "").strip()
    unit = (portion.get("unit") or "").strip()
    description = (portion.get("description") or "").strip()

    if modifier:
        unit_part = modifier
    elif unit and unit.lower() != "undetermined":
        unit_part = unit
    elif description:
        unit_part = description
    else:
        unit_part = "serving"

    return f"{amount:g} {unit_part}".strip()


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
            if portion.get("gram_weight"):
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
            seen_grams.add(grams)
            macros = scale_nutrients(metadata, grams)
            options.append({
                "label": _format_portion_label(portion),
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
    """Turn a raw Pinecone match into a grounded, loggable candidate: real
    name, brand, serving label, and calories/macros scaled to its default
    serving. This is what powers data-driven 'Did you mean?' alternatives."""
    metadata = match.get("metadata", {})
    serving_size_g, serving_source = get_serving_size_g(metadata)
    macros = scale_nutrients(metadata, serving_size_g)
    household = metadata.get("household_serving_fulltext", "")
    return {
        "fdc_id": match.get("id"),
        "name": metadata.get("name"),
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
    deterministic — no extra model call. (A future optional LLM step could
    *name* the diverging axis more naturally; that would slot in right here.)
    """
    sample = candidates[:RESOLVER_SAMPLE_SIZE]
    identity = _calorie_spread([c.get("calories") for c in sample])
    amount = _calorie_spread([p.get("calories") for p in portion_options])

    # If both axes diverge, ask about the bigger calorie swing first.
    identity_gap = identity["max"] - identity["min"]
    amount_gap = amount["max"] - amount["min"]

    if identity["diverges"] and identity_gap >= amount_gap:
        options = [
            {
                "label": (f"{c['brand']} " if c.get("brand") else "")
                + (c.get("name") or ""),
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
    [original] or [original, toggled]. We verified embedding similarity is
    sensitive to singular/plural — 'bananas' matches the SR name 'Bananas,
    raw' better than 'banana' does — so we try both and keep the better."""
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


async def _retrieve_best(
    query: str, pinecone_filter: dict | None = None
) -> tuple[list, str]:
    """Try the query and its number variant, and keep whichever one's TOP
    match scores highest. Both variants are embedded in a SINGLE batched
    OpenAI call (input accepts a list), so this adds Pinecone queries but not
    extra embedding round-trips. Taking the max score means a bad variant can
    only be ignored, never degrade the result. `pinecone_filter` (optional)
    restricts results by metadata, e.g. brand-vs-generic source."""
    variants = _number_variants(query)

    embedding_response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=variants,
    )
    vectors = [item.embedding for item in embedding_response.data]

    best_matches: list = []
    best_score = -1.0
    best_variant = query
    for variant, vector in zip(variants, vectors):
        results = index.query(
            vector=vector,
            top_k=RETRIEVAL_TOP_K,
            include_metadata=True,
            filter=pinecone_filter,
        )
        matches = results.get("matches", [])
        top_score = matches[0].get("score", 0) if matches else 0
        if top_score > best_score:
            best_score = top_score
            best_matches = matches
            best_variant = variant

    return best_matches, best_variant


async def lookup_food(query: str, source_filter: str | None = None) -> dict | None:
    print("RAG query:", query, "| source_filter:", source_filter)

    pinecone_filter = _source_pinecone_filter(source_filter)
    matches, winning_variant = await _retrieve_best(query, pinecone_filter)
    if not matches:
        return None

    if winning_variant.strip().lower() != query.strip().lower():
        print(f"RAG: variant '{winning_variant}' outscored original '{query}'")

    # Vector score alone often buries the everyday food (e.g. "Bananas, raw")
    # under chips/branded neighbors. Re-rank by how closely the name matches
    # what the user said (plus a small near-zero-kcal demotion for caloric
    # foods) before picking the primary + candidate list.
    matches = rerank_matches_by_query(query, matches)

    match = _pick_match_with_usable_calories(query, matches)
    if match is None or match.get("score", 0) < SCORE_THRESHOLD:
        return None

    metadata = match.get("metadata", {})
    fdc_id = match["id"]

    print(
        f"Top match: {metadata.get('name')} — score: {match['score']} "
        f"(after query-match re-rank)"
    )

    # Pinecone stores nutrient values per 100g. serving_size_g (branded) or
    # a default portion's gram_weight (SR Legacy) tells us the actual amount
    # to scale to, instead of returning raw per-100g values.
    serving_size_g, serving_source = get_serving_size_g(metadata)
    macros = scale_nutrients(metadata, serving_size_g)
    calories = macros["calories"]
    protein = macros["protein"]
    carbs = macros["carbs"]
    fat = macros["fat"]

    # --- Previous live-USDA-API fallback (replaced by the metadata-based
    # math above, now that serving_size_g is stored at embed time). Left here
    # commented out, not deleted, in case a live lookup is ever needed again
    # (e.g. for a food that predates the serving_size_g fix, or a field this
    # embed doesn't carry yet).
    #
    # try:
    #     async with httpx.AsyncClient(timeout=10) as http_client:
    #         usda_response = await http_client.get(
    #             f"https://api.nal.usda.gov/fdc/v1/food/{fdc_id}",
    #             params={"api_key": USDA_API_KEY},
    #         )
    #         usda_response.raise_for_status()
    #         response = usda_response.json()
    #
    #     label = response.get("labelNutrients", {})
    #     if label.get("calories"):
    #         calories = label.get("calories", {}).get("value")
    #         protein = label.get("protein", {}).get("value")
    #         carbs = label.get("carbohydrates", {}).get("value")
    #         fat = label.get("fat", {}).get("value")
    #     else:
    #         serving_size = response.get("servingSize") or 100
    #         unit = response.get("servingSizeUnit", "g")
    #         if unit in ["oz", "OZ"]:
    #             serving_size *= 28.3495
    #         multiplier = serving_size / 100
    #         calories = (metadata.get("calories") or 0) * multiplier
    #         protein = (metadata.get("protein") or 0) * multiplier
    #         carbs = (metadata.get("carbs") or 0) * multiplier
    #         fat = (metadata.get("fat") or 0) * multiplier
    # except Exception as e:
    #     print(f"USDA lookup failed for fdc_id {fdc_id}: {e}")

    print(f"fdc_id: {fdc_id}, serving_size_g: {serving_size_g} (source: {serving_source}), calories: {calories}")

    household_serving_fulltext = metadata.get("household_serving_fulltext", "")
    whole_container = is_whole_container_serving(household_serving_fulltext)

    # Grounded alternatives, straight from the vector search — real foods the
    # user might have meant (identity axis), each priced with its own serving.
    candidates = [
        summarize_match(m)
        for m in matches
        if m.get("score", 0) >= CANDIDATE_SCORE_FLOOR
    ][:MAX_CANDIDATES]

    # Grounded portion choices for the chosen food (amount axis) — this is
    # what lets "banana" offer medium/large/cup instead of guessing one.
    portion_options = build_portion_options(metadata)

    # One consolidated decision: is this resolved, or worth one question?
    resolution = assess_resolution(metadata.get("name"), candidates, portion_options)
    print(
        f"resolution: {resolution['status']}"
        + (f" (ask about {resolution['axis']})" if resolution["axis"] else "")
    )

    return {
        "food_name": metadata.get("name"),
        "brand": get_brand(metadata),
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "serving_size_g": serving_size_g,
        "serving_source": serving_source,
        "serving_label": build_serving_label(metadata, serving_size_g, serving_source),
        "serving_note": "This serving size represents the entire container." if whole_container else None,
        "source": "usda_rag",
        "candidates": candidates,
        "portion_options": portion_options,
        "resolution": resolution,
    }
