"""Words in, grams out: turn what the user said about amount ("half",
"8 fl oz", "1/4 cup", "100 grams") into the multiplier applied to a looked-up
record's default-serving nutrition.

Each kind of amount gets one rule:
  count          -> amount x the record's serving (no grams needed)
  weight         -> exact grams (g, kg, oz, lb)
  drink volume   -> fl oz / ml at 1 g/ml
  kitchen volume -> cup / tbsp / tsp through a volume portion the record
                    lists, else the curated record of the same food, else
                    left unconverted so the caller can ask
"""
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Looks up the curated (SR Legacy/FNDDS) record for a food name. Passed in so
# this module never touches the database itself.
ReferenceLookup = Callable[[str], Awaitable[dict | None]]


_WORD_TO_QUANTITY = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
    "dozen": 12.0,
    "half": 0.5,
}


_UNICODE_FRACTIONS = {"½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75}


def leading_fraction(serving_size) -> float | None:
    """'1/4 cup' -> 0.25, '1 1/2 cups' -> 1.5, '½ cup' -> 0.5; None otherwise.

    GPT writes the fraction correctly in serving_size text but has been seen
    to put 1 in the numeric amount field ("1/4 cup" with amount 1.0).
    """
    text = str(serving_size or "").strip().lower()
    mixed = re.match(r"^(\d+)\s+(\d+)/(\d+)\b", text)
    if mixed and int(mixed.group(3)):
        return int(mixed.group(1)) + int(mixed.group(2)) / int(mixed.group(3))
    simple = re.match(r"^(\d+)/(\d+)\b", text)
    if simple and int(simple.group(2)):
        return int(simple.group(1)) / int(simple.group(2))
    if text[:1] in _UNICODE_FRACTIONS:
        return _UNICODE_FRACTIONS[text[:1]]
    return None


def parse_quantity_multiplier(serving_size) -> float:
    """Parse GPT serving_size into a numeric scale factor for per-item nutrition.

    Bare numbers ('2') are preferred. If the model includes a food name
    ('2 bananas') or a unit ('2 cups'), use the leading quantity instead of
    silently falling back to 1.0.
    """
    if serving_size is None:
        logger.warning("serving_size missing; defaulting quantity multiplier to 1.0")
        return 1.0
    if isinstance(serving_size, (int, float)) and not isinstance(serving_size, bool):
        return float(serving_size)

    text = str(serving_size).strip().lower()
    if not text:
        logger.warning("serving_size empty; defaulting quantity multiplier to 1.0")
        return 1.0

    try:
        return float(text)
    except (TypeError, ValueError):
        pass

    fraction = leading_fraction(text)
    if fraction is not None:
        return fraction

    dozen_match = re.match(r"^(?:a|an)\s+dozen\b", text)
    if dozen_match or text == "dozen" or text.startswith("dozen "):
        if text not in {"12", "12.0"}:
            logger.warning(
                "serving_size %r is not a bare number; using dozen quantity 12.0",
                serving_size,
            )
        return 12.0

    num_match = re.match(r"^(\d+(?:\.\d+)?)\b(.*)$", text)
    if num_match:
        quantity = float(num_match.group(1))
        rest = num_match.group(2).strip()
        if rest:
            logger.warning(
                "serving_size %r is not a bare number; using leading quantity %s",
                serving_size,
                quantity,
            )
        return quantity

    word_match = re.match(r"^([a-z]+)(?:\s+(.*))?$", text)
    if word_match:
        word = word_match.group(1)
        rest = (word_match.group(2) or "").strip()
        if word in ("a", "an") and rest.startswith("dozen"):
            logger.warning(
                "serving_size %r is not a bare number; using dozen quantity 12.0",
                serving_size,
            )
            return 12.0
        if word in _WORD_TO_QUANTITY:
            quantity = _WORD_TO_QUANTITY[word]
            if rest or word not in {str(int(quantity))}:
                logger.warning(
                    "serving_size %r is not a bare number; using word quantity %s",
                    serving_size,
                    quantity,
                )
            return quantity

    logger.warning(
        "Could not parse serving_size %r as a quantity; defaulting multiplier to 1.0",
        serving_size,
    )
    return 1.0


# Weight units convert to grams exactly, so a stated weight never needs the
# record's default serving to mean anything. Volume units (cup, tbsp) are not
# here: their grams depend on the food.
_GRAMS_PER_WEIGHT_UNIT = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "oz": 28.3495,
    "ounce": 28.3495,
    "ounces": 28.3495,
    "lb": 453.592,
    "lbs": 453.592,
    "pound": 453.592,
    "pounds": 453.592,
}


def _unit_after_quantity(serving_size) -> str:
    """'100 grams' -> 'grams', '1/4 cup' -> 'cup'. Empty when there is no unit."""
    text = str(serving_size or "").strip().lower()
    match = re.match(
        r"^(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[½⅓⅔¼¾]|[a-z]+)\s+(.+)$", text
    )
    return match.group(1).strip().rstrip(".") if match else ""


# Drinks are stated by volume. At 1 g/ml the error is ~3% for milk, juice and
# soda, far below the serving-mismatch errors this replaces.
_ML_PER_FLUID_UNIT = {
    "fl oz": 29.5735,
    "fl. oz": 29.5735,
    "floz": 29.5735,
    "fluid ounce": 29.5735,
    "fluid ounces": 29.5735,
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
}


def stated_fluid_grams(serving_size, unit, amount: float) -> float | None:
    """Grams for a stated drink volume ('8 fl oz', '330 ml') at 1 g/ml, else None."""
    rest = _unit_after_quantity(serving_size)
    for candidate in (rest, str(unit or "").strip().lower()):
        if candidate in _ML_PER_FLUID_UNIT:
            return amount * _ML_PER_FLUID_UNIT[candidate]
    return None


# Kitchen volumes, in tablespoons. Their grams depend on the food, so they
# convert only through a volume portion the record itself lists.
_TBSP_PER_VOLUME_UNIT = {
    "cup": 16.0,
    "cups": 16.0,
    "c": 16.0,
    "tablespoon": 1.0,
    "tablespoons": 1.0,
    "tbsp": 1.0,
    "tbs": 1.0,
    "teaspoon": 1.0 / 3.0,
    "teaspoons": 1.0 / 3.0,
    "tsp": 1.0 / 3.0,
}


def _volume_unit(token: str) -> str:
    return token.strip().lower().rstrip(".,")


def stated_volume_unit(serving_size, unit) -> str | None:
    """'cup' / 'tablespoon' / ... when the user stated a kitchen volume, else None."""
    rest = _unit_after_quantity(serving_size)
    for candidate in (rest.split()[0] if rest else "", str(unit or "")):
        if _volume_unit(candidate) in _TBSP_PER_VOLUME_UNIT:
            return _volume_unit(candidate)
    return None


def grams_per_tablespoon(portion_options) -> float | None:
    """The food's own density from a volume portion it lists ('1 tablespoon'
    14 g, '1/4 cup' 45 g), or None when it lists no volume portion."""
    for option in portion_options or []:
        label = str(option.get("label") or "").strip().lower()
        grams = option.get("gram_weight")
        if not label or not grams:
            continue
        # "1 cup, in shell, yields 51 g" / "1 oz, dry, yields 80 g" give the
        # weight of a different form of the food, not what a cup weighs.
        if "yield" in label:
            continue
        count = leading_fraction(label)
        if count is None:
            number = re.match(r"^(\d+(?:\.\d+)?)\b", label)
            count = float(number.group(1)) if number else None
        rest = _unit_after_quantity(label)
        token = _volume_unit(rest.split()[0]) if rest else ""
        if count and token in _TBSP_PER_VOLUME_UNIT:
            return float(grams) / (count * _TBSP_PER_VOLUME_UNIT[token])
    return None


_PREP_WORDS = {"cooked", "uncooked", "dry", "raw", "plain"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower().replace("'", ""))


def _word_in(word: str, words: set[str]) -> bool:
    forms = {word, word + "s", word + "es", word.rstrip("s")}
    if word.endswith("es"):
        forms.add(word[:-2])
    return bool(forms & words)


def reference_names_same_food(food: str, reference_name: str) -> bool:
    """True when a curated record is the same food, so its cup weight applies.

    Both directions: every word the user said is in the record name, and the
    record's head (text before the first comma, e.g. 'Rice noodles') is only
    words the user said. Prep words are ignored on the user's side.
    """
    food_words = [w for w in _words(food) if w not in _PREP_WORDS]
    name_words = set(_words(reference_name))
    head_words = _words(reference_name.split(",")[0])
    if not food_words or not head_words:
        return False
    said = set(food_words)
    return all(_word_in(w, name_words) for w in food_words) and all(
        _word_in(w, said) for w in head_words
    )


# Calories per gram within this factor = same food in the same state. Dry
# oats (3.7 kcal/g) vs cooked oatmeal (0.7) differ ~5x and must not mix.
_MAX_KCAL_PER_GRAM_RATIO = 1.5


def _kcal_per_gram(record: dict) -> float | None:
    try:
        calories = float(record.get("calories") or 0)
        grams = float(record.get("serving_size_g") or 0)
    except (TypeError, ValueError):
        return None
    return calories / grams if calories > 0 and grams > 0 else None


async def borrowed_grams_per_tablespoon(
    food: str, matched: dict, lookup_reference: ReferenceLookup
) -> tuple[float, str] | None:
    """Cup weight from the curated (SR Legacy/FNDDS) version of the same food,
    for records that list no volume portion. Only the density is borrowed;
    calories per gram still come from the matched record, so the two must
    agree on calories per gram (same state: cooked vs dry)."""
    reference = await lookup_reference(food)
    if not reference or reference.get("blocked_by_allergy"):
        return None
    name = reference.get("food_name") or ""
    if not reference_names_same_food(food, name):
        return None
    matched_density = _kcal_per_gram(matched)
    reference_density = _kcal_per_gram(reference)
    if not matched_density or not reference_density:
        return None
    ratio = matched_density / reference_density
    if not (1 / _MAX_KCAL_PER_GRAM_RATIO <= ratio <= _MAX_KCAL_PER_GRAM_RATIO):
        logger.info(
            "volume_density_rejected=%r food=%r kcal_per_g matched=%.2f reference=%.2f",
            name,
            food,
            matched_density,
            reference_density,
        )
        return None
    per_tbsp = grams_per_tablespoon(reference.get("portion_options"))
    return (per_tbsp, name) if per_tbsp else None


def stated_weight_grams(serving_size, unit, amount: float) -> float | None:
    """Grams the user stated by weight, or None when the amount is not a weight.

    serving_size text is checked first because GPT's separate unit field has
    been seen to say 'serving' where the text says '3 tablespoons'.
    """
    rest = _unit_after_quantity(serving_size)
    candidates = (rest, rest.split()[0] if rest else "", str(unit or "").strip().lower())
    for candidate in candidates:
        if candidate in _GRAMS_PER_WEIGHT_UNIT:
            return amount * _GRAMS_PER_WEIGHT_UNIT[candidate]
    return None


@dataclass
class StatedQuantity:
    multiplier: float  # applied to the record's default-serving nutrition
    amount: float  # what the user said: 100 for "100 grams", 0.5 for "half"
    unconverted_volume: str | None  # kitchen unit with no honest gram figure


async def resolve_quantity(
    parsed: dict, nutrition: dict, lookup_reference: ReferenceLookup
) -> StatedQuantity:
    """The single entry point: parsed amount + matched record -> multiplier."""
    food_query = parsed.get("food")
    if parsed.get("amount") is not None:
        try:
            quantity = float(parsed["amount"])
        except (TypeError, ValueError):
            quantity = parse_quantity_multiplier(parsed.get("serving_size", "1"))
    else:
        quantity = parse_quantity_multiplier(parsed.get("serving_size", "1"))
    text_fraction = leading_fraction(parsed.get("serving_size"))
    if text_fraction is not None:
        quantity = text_fraction

    # A stated weight ("100 grams", "8 oz") scales against the record's
    # serving grams, not against the serving itself. The logged amount
    # stays what the user said.
    stated_amount = quantity
    stated_grams = stated_fluid_grams(
        parsed.get("serving_size"), parsed.get("unit"), quantity
    )
    if stated_grams is None:
        stated_grams = stated_weight_grams(
            parsed.get("serving_size"), parsed.get("unit"), quantity
        )
    # A kitchen volume ("1 tablespoon") converts through the food's own
    # volume portion. Without one there is no honest gram figure.
    unconverted_volume = None
    if stated_grams is None:
        volume_unit = stated_volume_unit(parsed.get("serving_size"), parsed.get("unit"))
        if volume_unit:
            per_tbsp = grams_per_tablespoon(nutrition.get("portion_options"))
            if per_tbsp:
                stated_grams = quantity * _TBSP_PER_VOLUME_UNIT[volume_unit] * per_tbsp
            else:
                borrowed = await borrowed_grams_per_tablespoon(food_query, nutrition, lookup_reference)
                if borrowed:
                    per_tbsp, reference_name = borrowed
                    stated_grams = quantity * _TBSP_PER_VOLUME_UNIT[volume_unit] * per_tbsp
                    logger.info(
                        "volume_density_source=%r food=%r grams_per_tbsp=%.2f",
                        reference_name,
                        food_query,
                        per_tbsp,
                    )
                else:
                    unconverted_volume = volume_unit
    try:
        serving_g = float(nutrition.get("serving_size_g") or 0)
    except (TypeError, ValueError):
        serving_g = 0.0
    if stated_grams is not None and serving_g > 0:
        quantity = stated_grams / serving_g

    return StatedQuantity(
        multiplier=quantity,
        amount=stated_amount,
        unconverted_volume=unconverted_volume,
    )


def unconverted_volume_resolution(food_name: str, unit: str, portion_options) -> dict:
    """One amount question, built from the record's own portions, for a kitchen
    volume that could not be converted."""
    options = [
        {"label": p.get("label"), "calories": p.get("calories"), "kind": "portion"}
        for p in portion_options or []
        if p.get("label")
    ]
    listed = "; ".join(
        f"{o['label']} ({int(round(o['calories']))} cal)"
        for o in options[:3]
        if o.get("calories") is not None
    )
    reason = f"I don't have a {unit} measurement for {food_name}."
    question = (
        f"{reason} Did you mean {listed}?" if listed
        else f"{reason} How much did you have?"
    )
    return {
        "status": "needs_clarification",
        "axis": "amount",
        "reason": reason,
        "question": question,
        "options": options,
    }
