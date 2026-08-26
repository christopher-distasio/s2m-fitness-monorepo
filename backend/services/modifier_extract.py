"""
Shared USDA-style modifier matching (query-side and database-side).

Word-boundary matching plus branded-name suppressions, compound-span
rules, and a few document-level co-occurrence checks. Maps and EXCLUSIONS
stay with each caller so FNDDS can keep extra TEMP_HOT phrases.
"""

from __future__ import annotations

import re
from functools import lru_cache

NONE_VALUE = "NONE"

# Evidence-based brand/company phrases. A trigger whose match span sits
# inside one of these is ignored.
BRAND_DENYLIST = (
    "canada dry",
    "fresh foods market",
    "fresh creative foods",
    "crystal light",
)

# Phrases that consume a shorter trigger without themselves assigning a
# modifier (e.g. "salted caramel" must not fire sodium_level).
COVERING_PHRASES = (
    "salted caramel",
)

# `light` → FAT_LEVEL_REDUCED: adjacent-window neighbors (3 tokens).
LIGHT_NEIGHBOR_TOKENS = frozenset({
    "tuna", "syrup", "nectar", "meat", "roast", "chunk",
    "yellow", "crispy", "molasses",
})
LIGHT_NEIGHBOR_PHRASES = (
    ("brown", "sugar"),
    ("corn", "syrup"),
    ("layer", "of"),
    ("olive", "oil"),
    ("kidney", "beans"),
)
LIGHT_TOKEN_WINDOW = 3

# If these appear anywhere in the description, `light` is not reduced-fat.
# Needed for comma-split names ("CHUNK LIGHT TUNA IN WATER, CHUNK LIGHT IN WATER")
# and drink mixes where the beverage word is far from `light`.
LIGHT_DOC_PHRASES = (
    "tuna",
    "olive oil",
    "lemonade",
    "tonic",
    "drink mix",
    "soft drink",
    "molasses",
    "corn syrup",
    "kidney beans",
    "crystal light",
)

RAW_FOLLOWERS = frozenset({"honey", "sugar", "turbinado"})

ICED_NEIGHBOR_TOKENS = frozenset({
    "cake", "cookie", "cookies", "donut", "doughnut", "roll", "brownie",
})
ICED_TOKEN_WINDOW = 4
BOSTON_BAKED_BEANS = "boston baked beans"
BOSTON_CANDY_CUES = ("candy", "peanut", "peanuts")

_TERM_BOUNDARY = r"(?<![a-z0-9]){term}(?![a-z0-9])"
_LACTOSE_FREE_RE = re.compile(r"lactose[\s-]?free", re.I)
_DAIRY_FREE_RE = re.compile(r"dairy[\s-]?free", re.I)


@lru_cache(maxsize=512)
def _term_re(term: str) -> re.Pattern:
    return re.compile(_TERM_BOUNDARY.format(term=re.escape(term)))


def _spans(term: str, text: str) -> list[tuple[int, int]]:
    return [m.span() for m in _term_re(term).finditer(text)]


def _tokenize(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[a-z0-9]+", text)]


def _span_covered(span: tuple[int, int], cover: tuple[int, int]) -> bool:
    cs, ce = cover
    ss, se = span
    return cs <= ss and ce >= se and (ce - cs) > (se - ss)


def _span_inside(span: tuple[int, int], cover: tuple[int, int]) -> bool:
    cs, ce = cover
    ss, se = span
    return cs <= ss and ce >= se


def _all_terms(mappings: dict) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term_map in mappings.values():
        for term in term_map:
            if term not in seen:
                seen.add(term)
                terms.append(term)
    return terms


def _covered_by_longer_term(
    span: tuple[int, int],
    term: str,
    text: str,
    terms: list[str],
) -> bool:
    term_len = len(term)
    for other in terms:
        if len(other) <= term_len:
            continue
        for cover in _spans(other, text):
            if _span_covered(span, cover):
                return True
    return False


def _inside_phrases(span: tuple[int, int], text: str, phrases: tuple[str, ...]) -> bool:
    for phrase in phrases:
        for cover in _spans(phrase, text):
            if _span_inside(span, cover):
                return True
    return False


def _window_words(
    span: tuple[int, int],
    tokens: list[tuple[str, int, int]],
    window: int,
) -> list[str]:
    ss, se = span
    idx = None
    for i, (_, ts, te) in enumerate(tokens):
        if not (te <= ss or ts >= se):
            idx = i
            break
    if idx is None:
        return []
    lo = max(0, idx - window)
    hi = min(len(tokens), idx + window + 1)
    return [w for w, _, _ in tokens[lo:hi]]


def _phrase_in_words(words: list[str], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    for i in range(len(words) - n + 1):
        if tuple(words[i : i + n]) == phrase:
            return True
    return False


def _light_suppressed(span: tuple[int, int], tokens: list[tuple[str, int, int]], text: str) -> bool:
    if any(_term_re(p).search(text) for p in LIGHT_DOC_PHRASES):
        return True
    words = _window_words(span, tokens, LIGHT_TOKEN_WINDOW)
    if any(w in LIGHT_NEIGHBOR_TOKENS for w in words):
        return True
    return any(_phrase_in_words(words, p) for p in LIGHT_NEIGHBOR_PHRASES)


def _raw_suppressed(span: tuple[int, int], tokens: list[tuple[str, int, int]], text: str) -> bool:
    _, se = span
    rest = text[se:].lstrip()
    if rest.startswith("!"):
        return True
    following = [w for w, ts, _ in tokens if ts >= se]
    if not following:
        return False
    if following[0] in RAW_FOLLOWERS:
        return True
    if len(following) >= 2 and following[0] == "cane" and following[1] == "sugar":
        return True
    return False


def _iced_suppressed(span: tuple[int, int], tokens: list[tuple[str, int, int]], text: str) -> bool:
    words = _window_words(span, tokens, ICED_TOKEN_WINDOW)
    if any(w in ICED_NEIGHBOR_TOKENS for w in words):
        return True
    if "devil" in words and "food" in words:
        return True
    return False


def _boston_baked_beans_candy(span: tuple[int, int], text: str) -> bool:
    if BOSTON_BAKED_BEANS not in text:
        return False
    if not any(cue in text for cue in BOSTON_CANDY_CUES):
        return False
    return _inside_phrases(span, text, (BOSTON_BAKED_BEANS,))


def _phrase_excluded(term: str, text: str, exclusions: dict) -> bool:
    return any(phrase in text for phrase in exclusions.get(term, []))


def iter_modifier_hits(
    text: str,
    mappings: dict,
    exclusions: dict,
    *,
    categories: list[str] | None = None,
) -> list[tuple[str, str, str]]:
    """
    Winning (category, canonical_value, trigger_term) triples for `text`.
    One winner per category, same order as iterating `mappings`.
    """
    desc = (text or "").lower().strip()
    if not desc:
        return []

    terms = _all_terms(mappings)
    tokens = _tokenize(desc)
    cats = categories if categories is not None else list(mappings.keys())
    hits: list[tuple[str, str, str]] = []

    for category in cats:
        term_map = mappings.get(category) or {}
        for term, value in term_map.items():
            if _phrase_excluded(term, desc, exclusions):
                continue
            accepted = False
            for span in _spans(term, desc):
                if _inside_phrases(span, desc, BRAND_DENYLIST):
                    continue
                if _inside_phrases(span, desc, COVERING_PHRASES):
                    continue
                if _covered_by_longer_term(span, term, desc, terms):
                    continue
                if term == "light" and _light_suppressed(span, tokens, desc):
                    continue
                if term == "raw" and _raw_suppressed(span, tokens, desc):
                    continue
                if term == "iced" and _iced_suppressed(span, tokens, desc):
                    continue
                if term == "baked" and _boston_baked_beans_candy(span, desc):
                    continue
                accepted = True
                break
            if accepted:
                hits.append((category, value, term))
                break
    return hits


def extract_modifiers_from_maps(
    text: str,
    mappings: dict,
    exclusions: dict,
) -> dict[str, str]:
    result = {category: NONE_VALUE for category in mappings}
    for category, value, _term in iter_modifier_hits(text, mappings, exclusions):
        result[category] = value
    return result


def extract_literal_diet_claims(text: str) -> dict[str, str]:
    """Literal lactose-free / dairy-free claims. Never infers one from the other."""
    desc = text or ""
    out: dict[str, str] = {}
    if _LACTOSE_FREE_RE.search(desc):
        out["lactose_free"] = "lactose_free"
    if _DAIRY_FREE_RE.search(desc):
        out["dairy_free"] = "dairy_free"
    return out


def query_mentions_lactose_free(query: str) -> bool:
    return bool(_LACTOSE_FREE_RE.search(query or ""))
