"""Re-rank vector-search hits so close name matches beat weak neighbors.

Pinecone similarity alone often ranks "Banana chips" or long branded strings
above the everyday food the user meant ("Bananas, raw"). This module applies a
deterministic query-match boost on top of the vector score — no popularity
store, no re-embedding. Pure functions so unit tests don't need Pinecone.
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
    """Stable re-rank: query-match first, then original vector score."""

    def sort_key(match: dict) -> tuple[float, float]:
        meta = match.get("metadata") or {}
        name = meta.get("name") or ""
        brand = (meta.get("brand_name") or meta.get("brand_owner") or "").strip()
        return (
            query_match_score(query, name, brand),
            float(match.get("score") or 0),
        )

    return sorted(matches, key=sort_key, reverse=True)
