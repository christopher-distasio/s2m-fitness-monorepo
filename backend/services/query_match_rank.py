"""Re-rank vector-search hits so close name matches beat weak neighbors.

Pinecone similarity alone often ranks "Banana chips" or long branded strings
above the everyday food the user meant ("Bananas, raw"). This module applies a
deterministic query-match boost on top of the vector score — no popularity
store, no re-embedding. Pure functions so unit tests don't need Pinecone.

Also applies a small additive penalty to near-zero-calorie candidates when the
query is for a food that should plausibly have calories (ham, bread, …), so
degenerate 0-kcal database rows don't win near-ties. Genuinely zero-cal queries
(water, black coffee, diet soda) are not penalized.
"""
from __future__ import annotations

import re

# Descriptors that refine a food without changing its identity. Having these
# in the USDA name should NOT push a match below a differently-product name.
_SOFT_MODIFIERS = {
    "raw",
    "fresh",
    "plain",
    "cooked",
    "boiled",
    "baked",
    "roasted",
    "fried",
    "grilled",
    "steamed",
    "whole",
    "mature",
    "immature",
    "ripe",
    "green",
    "yellow",
    "white",
    "peeled",
    "unpeeled",
    "flesh",
    "only",
    "meat",
    "skin",
    "nfs",
    "ns",
    "as",
    "to",
    "from",
    "with",
    "without",
    "and",
    "or",
    "the",
    "a",
    "an",
    "of",
    "in",
    "for",
    "all",
    "grades",
    "choice",
    "select",
    "commercial",
    "retail",
    "frozen",
    "canned",
    "drained",
    "solids",
    "liquids",
}

# Per-100g (or stored) kcal at/under this is "near zero" for the small penalty.
_NEAR_ZERO_KCAL = 5.0
# Exact/missing zeros are usually bad USDA/brand rows, not real diet foods.
_DEGENERATE_ZERO_KCAL = 0.5
# Subtracted from the lexical score — ~one hard-extra / brand bump, enough to
# break near-ties without burying a dominant name match.
_NEAR_ZERO_CAL_PENALTY = 0.25

# Query tokens that usually mean a real zero/near-zero drink (no penalty).
_ZERO_CAL_ANCHORS = frozenset({
    "water",
    "seltzer",
    "espresso",
    "americano",
    "tea",
})
_COFFEE_CALORIE_CONFLICTS = frozenset({
    "latte",
    "cappuccino",
    "mocha",
    "macchiato",
    "frappe",
    "frappuccino",
    "milk",
    "cream",
    "sugar",
    "syrup",
    "cake",
})
_WATER_CALORIE_CONFLICTS = frozenset({
    "coconut",
    "flavor",
    "flavored",
    "juice",
    "tonic",
    "vitamin",
})
_TEA_CALORIE_CONFLICTS = frozenset({
    "sweet",
    "sweetened",
    "milk",
    "sugar",
    "honey",
    "boba",
    "chai",
    "latte",
})
_DIET_MARKERS = frozenset({"diet", "zero"})
_SODA_TOKENS = frozenset({"soda", "coke", "pepsi", "cola", "pop"})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _singularize(word: str) -> str:
    lower = word.lower()
    if lower.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if lower.endswith(("ches", "shes", "xes", "zes", "ses")):
        return word[:-2]
    if lower.endswith("s") and not lower.endswith("ss") and len(word) > 1:
        return word[:-1]
    return word


def _pluralize(word: str) -> str:
    lower = word.lower()
    if not word:
        return word
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if lower.endswith("y") and len(word) > 1 and word[-2].lower() not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _expand_forms(tokens: set[str]) -> set[str]:
    """Query tokens plus singular/plural variants so 'banana' matches 'bananas'."""
    expanded = set(tokens)
    for t in tokens:
        expanded.add(_singularize(t))
        expanded.add(_pluralize(t).lower())
    return expanded


def _is_related_extra(token: str, q_forms: set[str]) -> bool:
    """True when an 'extra' token is still about the same food (numbers,
    compounds that embed a query word like 'milkfat', etc.)."""
    if token.isdigit():
        return True
    for q in q_forms:
        if len(q) >= 3 and (q in token or token in q):
            return True
    return False


def is_zero_calorie_query(query: str) -> bool:
    """True when the user is asking for a food that can legitimately be ~0 kcal.

    Those queries must NOT trigger the near-zero candidate penalty.
    """
    tokens = _tokenize(query)
    if not tokens:
        return False
    if "water" in tokens:
        return not bool(tokens & _WATER_CALORIE_CONFLICTS)
    if "coffee" in tokens:
        # Plain / black coffee is ~0; latte/mocha/cake are not.
        return not bool(tokens & _COFFEE_CALORIE_CONFLICTS)
    if "tea" in tokens:
        return not bool(tokens & _TEA_CALORIE_CONFLICTS)
    if tokens & _ZERO_CAL_ANCHORS:
        return True
    if (tokens & _DIET_MARKERS) and (tokens & _SODA_TOKENS):
        return True
    return False


def _metadata_calories(meta: dict) -> float | None:
    raw = meta.get("calories")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _metadata_macro(meta: dict, key: str) -> float:
    raw = meta.get(key)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def effective_calories_per_100g(metadata: dict | None) -> float | None:
    """Stored kcal/100g, or Atwater estimate when the calorie field is missing/0.

    Many branded USDA rows have protein/fat filled in but calories left at 0.
    Using 4P+4C+9F keeps the right product selectable without logging 0 kcal.
    """
    meta = metadata or {}
    cal = _metadata_calories(meta)
    if cal is not None and cal > _DEGENERATE_ZERO_KCAL:
        return cal
    protein = _metadata_macro(meta, "protein")
    carbs = _metadata_macro(meta, "carbs")
    fat = _metadata_macro(meta, "fat")
    if protein == 0.0 and carbs == 0.0 and fat == 0.0:
        return cal
    estimated = 4.0 * protein + 4.0 * carbs + 9.0 * fat
    if estimated > _DEGENERATE_ZERO_KCAL:
        return estimated
    return cal


def near_zero_calorie_penalty(query: str, metadata: dict | None) -> float:
    """Additive penalty (≥0) for near-zero kcal rows on caloric queries.

    Returned value is subtracted from the lexical rank score. Small on purpose:
    breaks near-ties. Degenerate exact-zero tops are corrected separately in
    rerank_matches_by_query when a real-calorie alternative exists.
    Uses effective calories (Atwater fallback) so macro-complete 0-kcal rows
    are not treated as empty.
    """
    if is_zero_calorie_query(query):
        return 0.0
    cal = effective_calories_per_100g(metadata)
    if cal is None:
        return 0.0
    if cal <= _NEAR_ZERO_KCAL:
        return _NEAR_ZERO_CAL_PENALTY
    return 0.0


def _promote_caloric_alternative(query: str, ranked: list[dict]) -> list[dict]:
    """If #1 is a degenerate ~0 kcal row for a caloric query, prefer a real one.

    Only runs when some later hit has meaningful calories — otherwise leave the
    zero in place (all bad, or genuinely missing data).
    """
    if not ranked or is_zero_calorie_query(query):
        return ranked
    top_cal = effective_calories_per_100g(ranked[0].get("metadata") or {})
    if top_cal is None or top_cal > _DEGENERATE_ZERO_KCAL:
        return ranked
    for i, match in enumerate(ranked):
        if i == 0:
            continue
        cal = effective_calories_per_100g(match.get("metadata") or {})
        if cal is not None and cal > _NEAR_ZERO_KCAL:
            return [match] + [m for j, m in enumerate(ranked) if j != i]
    return ranked


def query_match_score(query: str, name: str, brand: str = "") -> float:
    """Higher = closer lexical match to what the user said.

    Coverage of query tokens in the name is rewarded. Extra *identity-changing*
    tokens (chips, bread, cereal, …) and an explicit brand are penalized, so
    short generic SR names like "Bananas, raw" beat "Banana chips" even when
    the vector score is slightly lower.
    """
    q = _tokenize(query)
    if not q:
        return 0.0

    n = _tokenize(name)
    if brand:
        n |= _tokenize(brand)

    q_forms = _expand_forms(q)

    covered = 0
    for t in q:
        forms = {t, _singularize(t), _pluralize(t).lower()}
        if forms & n:
            covered += 1
    coverage = covered / len(q)

    # Tokens in the name that aren't the query and aren't soft descriptors —
    # these usually mean a different product (chips, bread, juice, …).
    hard_extras = {
        t
        for t in (n - q_forms - _SOFT_MODIFIERS)
        if not _is_related_extra(t, q_forms)
    }
    extra_penalty = 0.35 * len(hard_extras)

    brand_penalty = 0.35 if (brand or "").strip() else 0.0

    # Prefer the everyday short name when coverage is otherwise equal.
    length_penalty = min(len(name or ""), 100) / 250.0

    # Name headed by a query token ("Bananas, raw") beats buried mentions.
    name_tokens_ordered = _TOKEN_RE.findall((name or "").lower())
    head = name_tokens_ordered[0] if name_tokens_ordered else ""
    head_bonus = 0.4 if head and head in q_forms else 0.0

    return coverage + head_bonus - extra_penalty - brand_penalty - length_penalty


def rerank_matches_by_query(query: str, matches: list[dict]) -> list[dict]:
    """Stable re-rank: query-match (minus near-zero kcal penalty), then vector score.

    After sorting, if the top hit is a degenerate 0-kcal row for a food that
    should have calories, promote the best remaining hit with real calories.
    """

    def sort_key(match: dict) -> tuple[float, float]:
        meta = match.get("metadata") or {}
        name = meta.get("name") or ""
        brand = (meta.get("brand_name") or meta.get("brand_owner") or "").strip()
        lexical = query_match_score(query, name, brand)
        lexical -= near_zero_calorie_penalty(query, meta)
        return (
            lexical,
            float(match.get("score") or 0),
        )

    ranked = sorted(matches, key=sort_key, reverse=True)
    return _promote_caloric_alternative(query, ranked)
