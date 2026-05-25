"""
Food parser eval suite — calls the real GPT + Edamam pipeline (no mocks).

Run: pytest tests/eval_food_parser.py -v -s
Use -s to see the score summary printed after the test run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

import pytest

from backend.services.food_parser import parse_food_input

Category = Literal["simple", "branded", "composite", "vague", "ambiguous"]


@dataclass
class EvalCase:
    raw_input: str
    expected_food: str
    expected_quantity: str
    expected_unit: str
    category: Category
    expected_size: str = ""
    expected_measurement: str = ""


@dataclass
class CaseResult:
    case: EvalCase
    actual_food: str | None
    actual_quantity: str | None
    actual_unit: str | None
    raw_serving_size: str | None
    food_exact: bool
    food_fuzzy_ratio: float
    quantity_match: bool
    unit_match: bool
    size_match: bool = True
    measurement_match: bool = True
    error: str | None = None

    @property
    def food_score(self) -> float:
        if self.food_exact:
            return 1.0
        if self.food_fuzzy_ratio >= 0.65:
            return self.food_fuzzy_ratio
        return 0.0

    @property
    def scored_size(self) -> bool | None:
        if not self.case.expected_size:
            return None
        return self.size_match

    @property
    def scored_measurement(self) -> bool | None:
        if not self.case.expected_measurement:
            return None
        return self.measurement_match

    @property
    def case_score(self) -> float:
        dims = [self.food_score, float(self.quantity_match), float(self.unit_match)]
        if self.case.expected_size:
            dims.append(float(self.size_match))
        if self.case.expected_measurement:
            dims.append(float(self.measurement_match))
        return sum(dims) / len(dims)

    @property
    def passed(self) -> bool:
        return self.case_score >= 0.85 and self.error is None


EVAL_CASES: list[EvalCase] = [
    # --- simple (8) ---
    EvalCase("an apple", "apple", "1", "", "simple"),
    EvalCase("two eggs", "eggs", "2", "", "simple"),
    EvalCase("one banana", "banana", "1", "", "simple"),
    EvalCase("a slice of bread", "bread", "1", "slice", "simple"),
    EvalCase("8 ounces of milk", "milk", "8", "ounce", "simple"),
    EvalCase(
        "1 tablespoon of peanut butter", "peanut butter", "1", "tablespoon", "simple"
    ),
    EvalCase("a cup of black coffee", "coffee", "1", "cup", "simple"),
    EvalCase("three crackers", "crackers", "3", "", "simple"),
    # --- branded (6) ---
    EvalCase(
        "Great Value light Greek yogurt",
        "greek yogurt",
        "1",
        "serving",
        "branded",
    ),
    EvalCase(
        "Chobani nonfat plain yogurt",
        "nonfat plain yogurt",
        "1",
        "serving",
        "branded",
    ),
    EvalCase("a can of Coca-Cola", "coca-cola", "1", "can", "branded"),
    EvalCase(
        "two slices of Dave's Killer Bread",
        "dave's killer bread",
        "2",
        "slice",
        "branded",
    ),
    EvalCase("Kirkland protein bar", "protein bar", "1", "", "branded"),
    EvalCase(
        "Trader Joe's cauliflower gnocchi",
        "cauliflower gnocchi",
        "1",
        "serving",
        "branded",
    ),
    # --- composite (6) ---
    EvalCase(
        "a bowl of pasta with chicken",
        "pasta with chicken",
        "1",
        "bowl",
        "composite",
    ),
    EvalCase(
        "turkey sandwich with cheese",
        "turkey sandwich with cheese",
        "1",
        "",
        "composite",
    ),
    EvalCase(
        "salad with grilled salmon",
        "salad with grilled salmon",
        "1",
        "",
        "composite",
    ),
    EvalCase("eggs and toast", "eggs and toast", "1", "serving", "composite"),
    EvalCase("rice and beans", "rice and beans", "1", "serving", "composite"),
    EvalCase(
        "chicken stir fry with vegetables",
        "chicken stir fry",
        "1",
        "serving",
        "composite",
    ),
    # --- vague (6) ---
    EvalCase("a handful of almonds", "almonds", "1", "handful", "vague"),
    EvalCase("a big bowl of rice", "rice", "1", "serving", "vague"),
    EvalCase("some pasta", "pasta", "1", "serving", "vague"),
    EvalCase(
        "a little butter",
        "butter",
        "1",
        "tablespoon",
        "vague",
        expected_measurement="tablespoon",
    ),
    EvalCase("a few grapes", "grapes", "1", "serving", "vague"),
    EvalCase(
        "a small scoop of ice cream",
        "ice cream",
        "1",
        "scoop",
        "vague",
    ),
    # --- ambiguous (4) ---
    EvalCase("chicken", "chicken", "1", "serving", "ambiguous"),
    EvalCase("fish", "fish", "1", "serving", "ambiguous"),
    EvalCase("chips", "chips", "1", "serving", "ambiguous"),
    EvalCase("yogurt", "yogurt", "1", "serving", "ambiguous"),
]

_WORD_TO_NUM: dict[str, str] = {
    "a": "1",
    "an": "1",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "half": "0.5",
    "quarter": "0.25",
    "couple": "2",
}

_VAGUE_QUANTITIES = frozenset(
    {"some", "few", "little", "bit", "handful", "pinch", "dash", "big", "small"}
)

_UNIT_ALIASES: dict[str, set[str]] = {
    "ounce": {"oz", "ounce", "ounces", "fl oz"},
    "tablespoon": {"tbsp", "tablespoon", "tablespoons", "tbs"},
    "cup": {"cup", "cups", "c"},
    "slice": {"slice", "slices"},
    "can": {"can", "cans"},
    "serving": {
        "serving",
        "servings",
        "portion",
        "portions",
        "container",
        "containers",
        "package",
        "packages",
        "cup",
        "cups",
        "piece",
        "pieces",
        "unit",
        "units",
        "item",
        "items",
    },
    "bowl": {"bowl", "bowls"},
    "handful": {"handful", "handfuls"},
    "scoop": {"scoop", "scoops"},
    "medium": {"medium", "med"},
    "large": {"large", "lg"},
    "small": {"small", "sm"},
    "tall": {"tall"},
    "regular": {"regular", "reg"},
    "thin": {"thin"},
    "thick": {"thick"},
}

_ALWAYS_DISCARD_QTY = frozenset(
    {
        "big",
        "little",
        "tiny",
        "huge",
        "giant",
        "generous",
        "heaping",
        "scant",
        "modest",
        "substantial",
        "good",
        "decent",
        "standard",
        "average",
        "narrow",
        "full",
        "partial",
        "light",
        "heavy",
        "short",
        "wide",
    }
)

_CONDITIONAL_SIZE_MODIFIERS = frozenset(
    {"medium", "large", "small", "tall", "regular", "thin", "thick"}
)

_REAL_UNIT_TOKENS = frozenset(
    alias
    for aliases in _UNIT_ALIASES.values()
    for alias in aliases
) | frozenset(_UNIT_ALIASES.keys())


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _normalize_food(value: str) -> str:
    text = _normalize_text(value)
    text = re.sub(r"^(a|an|the)\s+", "", text)
    return text


def _normalize_quantity(value: str | None) -> str | None:
    if value is None:
        return None
    token = _normalize_text(value)
    if token in _WORD_TO_NUM:
        return _WORD_TO_NUM[token]
    if token in _VAGUE_QUANTITIES:
        return token
    num_match = re.match(r"^(\d+(?:\.\d+)?|\d+/\d+)$", token)
    if num_match:
        return num_match.group(1)
    return token


def _expand_unit(unit: str) -> set[str]:
    normalized = _normalize_text(unit)
    aliases = {_normalize_text(alias) for alias in _UNIT_ALIASES.get(normalized, {normalized})}
    aliases.add(normalized)
    return aliases


def _is_real_unit(word: str) -> bool:
    return _normalize_text(word) in _REAL_UNIT_TOKENS


def _strip_size_modifiers_from_unit(unit: str) -> str:
    """Remove vague size words from the unit; keep conditional sizes when alone."""
    words = unit.split()
    while words:
        head = _normalize_text(words[0])
        if head in _ALWAYS_DISCARD_QTY:
            words = words[1:]
            continue
        if (
            head in _CONDITIONAL_SIZE_MODIFIERS
            and len(words) > 1
            and _is_real_unit(words[1])
        ):
            words = words[1:]
            continue
        break
    return " ".join(words)


def _sanitize_quantity_token(qty: str | None) -> str | None:
    if qty is None:
        return None
    token = _normalize_text(qty)
    if token in _ALWAYS_DISCARD_QTY:
        return None
    if token in _CONDITIONAL_SIZE_MODIFIERS:
        return None
    return _normalize_quantity(qty)


def parse_serving_size(serving: str | None) -> tuple[str | None, str | None]:
    """Split GPT serving_size into quantity and unit tokens."""
    if not serving:
        return None, None

    text = serving.strip().lower()
    if text in {"unknown", "n/a", "none"}:
        return None, None

    match = re.match(
        r"^(\d+(?:\.\d+)?|\d+/\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"half|quarter|couple|few|some|handful|scoop)\s+(.+)$",
        text,
    )
    if match:
        qty = _sanitize_quantity_token(match.group(1))
        unit = _strip_size_modifiers_from_unit(match.group(2).strip())
        return qty, unit or None

    if re.match(r"^\d+(?:\.\d+)?$", text) or text in _WORD_TO_NUM:
        return _normalize_quantity(text), None

    if text in _VAGUE_QUANTITIES:
        return _normalize_quantity(text), None

    stripped = _strip_size_modifiers_from_unit(text)
    if stripped != text:
        return None, stripped or None

    return None, text


def score_food(expected: str, actual: str | None) -> tuple[bool, float]:
    if not actual:
        return False, 0.0

    exp = _normalize_food(expected)
    act = _normalize_food(actual)

    if exp == act or exp in act or act in exp:
        return True, 1.0

    ratio = SequenceMatcher(None, exp, act).ratio()
    exp_tokens = set(exp.split())
    act_tokens = set(act.split())
    if exp_tokens and exp_tokens <= act_tokens:
        return False, max(ratio, 0.85)
    if act_tokens and act_tokens <= exp_tokens:
        return False, max(ratio, 0.85)

    return False, ratio


def score_quantity(expected: str, actual: str | None, raw_serving: str | None) -> bool:
    exp = _normalize_quantity(expected)
    act = _normalize_quantity(actual)
    serving = _normalize_text(raw_serving or "")

    if exp == act:
        return True

    if exp in serving or (act and exp in act):
        return True

    if exp in _VAGUE_QUANTITIES and (exp in serving or (act and exp == act)):
        return True

    # Accept assumed single serving when input had no explicit quantity.
    if exp == "1" and act in {None, "1"} and not re.search(r"\d", serving):
        return True

    return False


def score_unit(expected: str, actual: str | None, raw_serving: str | None) -> bool:
    if not expected:
        return True

    expected_aliases = _expand_unit(expected)
    actual_aliases = _expand_unit(actual) if actual else set()
    serving = _normalize_text(raw_serving or "")

    if expected_aliases & actual_aliases:
        return True

    if any(alias in serving for alias in expected_aliases):
        return True

    # "big bowl" / "large bowl" both contain bowl
    if "bowl" in expected_aliases and "bowl" in serving:
        return True

    return False


def score_size(
    expected: str,
    raw_serving: str | None,
    actual_unit: str | None,
    actual_food: str | None,
) -> bool:
    if not expected:
        return True

    size_aliases = _expand_unit(expected)
    serving = _normalize_text(raw_serving or "")
    unit = _normalize_text(actual_unit or "")
    food = _normalize_text(actual_food or "")

    if size_aliases & _expand_unit(unit):
        return True
    if any(alias in serving for alias in size_aliases):
        return True
    if any(alias in food for alias in size_aliases):
        return True

    return False


def score_measurement(
    expected: str, actual_unit: str | None, raw_serving: str | None
) -> bool:
    if not expected:
        return True
    return score_unit(expected, actual_unit, raw_serving)


async def evaluate_case(case: EvalCase) -> CaseResult:
    parsed = await parse_food_input(case.raw_input)

    if "error" in parsed:
        return CaseResult(
            case=case,
            actual_food=None,
            actual_quantity=None,
            actual_unit=None,
            raw_serving_size=None,
            food_exact=False,
            food_fuzzy_ratio=0.0,
            quantity_match=False,
            unit_match=False,
            size_match=False if case.expected_size else True,
            measurement_match=False if case.expected_measurement else True,
            error=parsed.get("error"),
        )

    raw_serving = parsed.get("serving_size")
    actual_quantity, actual_unit = parse_serving_size(raw_serving)
    actual_food = parsed.get("food")

    food_exact, food_fuzzy_ratio = score_food(case.expected_food, actual_food)
    quantity_match = score_quantity(case.expected_quantity, actual_quantity, raw_serving)
    unit_match = score_unit(case.expected_unit, actual_unit, raw_serving)
    size_match = score_size(
        case.expected_size, raw_serving, actual_unit, actual_food
    )
    measurement_match = score_measurement(
        case.expected_measurement, actual_unit, raw_serving
    )

    return CaseResult(
        case=case,
        actual_food=actual_food,
        actual_quantity=actual_quantity,
        actual_unit=actual_unit,
        raw_serving_size=raw_serving,
        food_exact=food_exact,
        food_fuzzy_ratio=food_fuzzy_ratio,
        quantity_match=quantity_match,
        unit_match=unit_match,
        size_match=size_match,
        measurement_match=measurement_match,
    )


def build_report(results: list[CaseResult]) -> dict:
    total_score = sum(r.case_score for r in results) / len(results) if results else 0.0

    categories: dict[str, list[CaseResult]] = {}
    for result in results:
        categories.setdefault(result.case.category, []).append(result)

    category_scores = {
        category: sum(r.case_score for r in cat_results) / len(cat_results)
        for category, cat_results in sorted(categories.items())
    }

    failures = [r for r in results if not r.passed]

    return {
        "total_score": total_score,
        "category_scores": category_scores,
        "failures": failures,
        "results": results,
    }


def format_report(report: dict) -> str:
    lines = [
        "",
        "=" * 72,
        "FOOD PARSER EVAL SUMMARY",
        "=" * 72,
        f"Total score: {report['total_score']:.1%}  ({len(report['results'])} cases)",
        "",
        "Per-category breakdown:",
    ]

    for category, score in report["category_scores"].items():
        lines.append(f"  {category:12s} {score:.1%}")

    failures: list[CaseResult] = report["failures"]
    lines.append("")
    lines.append(f"Failures: {len(failures)}")

    for failure in failures:
        case = failure.case
        lines.append("")
        lines.append(f"  [{case.category}] {case.raw_input!r}")
        if failure.error:
            lines.append(f"    error: {failure.error}")
        else:
            expected_parts = [
                f"food={case.expected_food!r}",
                f"qty={case.expected_quantity!r}",
                f"unit={case.expected_unit!r}",
            ]
            if case.expected_size:
                expected_parts.append(f"size={case.expected_size!r}")
            if case.expected_measurement:
                expected_parts.append(f"measurement={case.expected_measurement!r}")
            lines.append(f"    expected: {' '.join(expected_parts)}")

            lines.append(
                f"    actual:   food={failure.actual_food!r} "
                f"serving_size={failure.raw_serving_size!r} "
                f"(parsed qty={failure.actual_quantity!r}, unit={failure.actual_unit!r})"
            )

            score_parts = [
                f"food_exact={failure.food_exact}",
                f"food_fuzzy={failure.food_fuzzy_ratio:.2f}",
                f"qty={failure.quantity_match}",
                f"unit={failure.unit_match}",
            ]
            if failure.scored_size is not None:
                score_parts.append(f"size={failure.size_match}")
            if failure.scored_measurement is not None:
                score_parts.append(f"measurement={failure.measurement_match}")
            score_parts.append(f"case={failure.case_score:.1%}")
            lines.append(f"    scores:   {' '.join(score_parts)}")

    lines.append("=" * 72)
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_food_parser_eval():
    """Run all eval cases against the live parser and print a score summary."""
    results: list[CaseResult] = []
    for case in EVAL_CASES:
        results.append(await evaluate_case(case))

    report = build_report(results)
    print(format_report(report))

    assert len(results) == len(EVAL_CASES)
