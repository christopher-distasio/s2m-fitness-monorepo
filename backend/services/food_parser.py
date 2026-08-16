import json
import logging
import re
from openai import AsyncOpenAI
from dotenv import load_dotenv
from backend.services.nutrition_service import format_branded_name, lookup_food
from backend.services.query_match_rank import is_zero_calorie_query
from backend.services.parse_query_modifiers import parse_query_modifiers
from backend.services.dietary_filters import FDA_ALLERGENS
from backend.models import UserProfile

load_dotenv()

logger = logging.getLogger(__name__)

client = AsyncOpenAI()

SYSTEM_PROMPT = """
You are a nutrition data parser for a food logging app.

The user will provide a natural language food description (typed or transcribed from voice).
Your job is to extract structured information and return ONLY valid JSON — no explanation, no markdown.

Return this exact shape:
{
  "food": "string — normalized food name, optimized for database lookup",
  "brand": "string — the brand/manufacturer the user EXPLICITLY named, else empty string",
  "serving_size": "string — quantity only, e.g. '1', '2', '1 cup', '1 medium' (never include the food name)",
  "confidence": "high" | "medium" | "low",
  "notes": "string — optional clarification or assumption made",
  "reasoning": "string — optional short explanation of confidence",
  "alternatives": ["string — optional list of likely intended interpretations"]
}

Rules:
- Do NOT include calories or macronutrients — those come from the nutrition database
- Normalize the food name for database lookup but PRESERVE brand names. For branded items, include the brand name in the food field (e.g. 'great value light greek yogurt' not just 'greek yogurt', 'chobani nonfat plain yogurt' not just 'yogurt'). Brand names are essential for accurate nutrition lookup.
- Set "brand" to the brand/manufacturer ONLY when the user explicitly named one (e.g. 'Chobani', 'Great Value', "McDonald's"). If they named no brand (e.g. just 'banana', 'yogurt', 'chicken'), set "brand" to an empty string "".
- If multiple foods are mentioned, combine them into one descriptive name (e.g. "2 eggs and black coffee")
- If the input is completely unparseable as food, return { "error": "unparseable", "raw": "<input>" }
- Never guess wildly — if uncertain, set confidence to "low" and explain in notes
- If the input is a single common food with an explicit quantity/size, set "confidence" to "high" unless something is genuinely ambiguous
- Vague quantifiers alone (e.g. "some", "a bit", "a little", "a snack", "some pasta") are never "high" — use "medium" or "low" and ask for quantity/type via reasoning and alternatives
- Only return { "error": "unparseable", "raw": "<input>" } if the input has absolutely nothing to do with food
- serving_size is quantity only. Put the food name in "food", never in serving_size.
  One rule for every case:
  - Countable items (banana, egg, yogurt, cookie, apple): serving_size is the count as a number string only — '1', '2', '3', '12'. Wrong: '2 bananas', '2 eggs', 'two yogurts'. Right: '2' (food is 'banana' / 'egg' / 'yogurt').
  - Measured amounts (cups, oz, tablespoons, grams): serving_size is the number plus the unit only — '1 cup', '2 cups', '8 oz', '1 tablespoon'. Wrong: '2 cups of rice'. Right: serving_size '2 cups', food 'rice'.
  - Size words: '1 medium', '1 large', '1 small' — still no food name.
  - Word numbers from the user ('two', 'a dozen') must be converted to digits in serving_size ('2', '12').
- Always return a non-empty serving_size
- Do NOT always default vague quantities to "1 serving". Apply this logic instead:
  - If the food has a natural standard measurement unit, infer that unit even when quantity is vague:
    butter → tablespoon
    oil, olive oil, vegetable oil → tablespoon
    milk → ounce
    cream, heavy cream → tablespoon
    vinegar → tablespoon
    sauce, hot sauce, soy sauce → tablespoon
    Examples: "a little butter" → "1 tablespoon"; "a splash of milk" → "1 ounce"
  - If the food is an uncountable solid with no natural measurement unit (pasta, rice, chicken, oatmeal, salad, soup), default to "1 serving"
  - If the food is a countable item (eggs, apples, crackers, grapes), return the number with no unit (e.g. "2", "1")
  - When the user says a plural countable food item (e.g. 'two yogurts', 'three cookies', 'two dannon yogurts'), treat each as one individual container/unit. serving_size should be the number (e.g. '2'). Do not interpret plural packaged foods as cups or other measurements.
  - If the food is genuinely ambiguous, default to "1 serving"

Confidence rules:
- "high": food and quantity are clear and specific (e.g. "one banana", "two scrambled eggs")
- "medium": food is clear but quantity is vague or assumed, or food type is ambiguous but guessable
- "low": food is ambiguous, heavily vague, or both food type and quantity are unknown (e.g. "some pasta", "a snack" without type or amount)

Alternatives rules:
- For medium confidence (quantity vague, food clear): provide 2 to 3 portion size variations e.g. ["small handful of potato chips", "medium handful of potato chips", "large handful of potato chips"]
- For medium confidence (food ambiguous but guessable): provide 2 to 3 food type variations e.g. ["tortilla chips", "potato chips", "pita chips"]
- For low confidence where the food is known but quantity is vague: still provide 2 to 3 portion size alternatives
- For low confidence where both food and quantity are unknown: return alternatives as an empty array []
- Match alternatives to the actual source of uncertainty

Clarification flow:
If conversation_history is provided, the user is responding to a previous ambiguous parse.
"A small bowl", "medium portion", "just a little" etc. are quantity clarifications — NOT standalone food descriptions.
Combine the previous food from history with the new quantity/detail to produce a complete parse.
Example: history has "pasta", user says "a small bowl" → parse as "a small bowl of pasta".
NEVER return unparseable for a clarification response.
"""

# The single upfront disambiguating question, before any mixed candidate list.
# Shared by text and voice so the two flows can't diverge.
BRAND_CHOICE_QUESTION = (
    "Are you looking for a specific brand, or a general item?"
)

_VAGUE_QUANTIFIER_RE = re.compile(
    r"\b(some|a\s+bit|a\s+little|a\s+few|a\s+snack|about|roughly|around)\b",
    re.IGNORECASE,
)
_VAGUE_SERVING_RE = re.compile(
    r"^(some|a\s+bit|a\s+little|a\s+few|about|roughly|around|1\s+serving)$",
    re.IGNORECASE,
)


def _apply_confidence_guards(parsed: dict, raw_input: str) -> dict:
    """Never treat vague quantity-only input as high confidence."""
    confidence = parsed.get("confidence")
    serving = (parsed.get("serving_size") or "").strip()
    if confidence != "high":
        return parsed
    if _VAGUE_QUANTIFIER_RE.search(raw_input) or (
        serving and _VAGUE_SERVING_RE.match(serving)
    ):
        parsed["confidence"] = "medium"
        parsed["reasoning"] = (
            parsed.get("reasoning") or "Quantity or portion was vague."
        ).strip()
        if not parsed.get("alternatives"):
            food = parsed.get("food") or "food"
            parsed["alternatives"] = [
                f"a small portion of {food}",
                f"a medium portion of {food}",
                f"a large portion of {food}",
            ]
    return parsed


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


def _format_alt(name: str, brand: str | None, calories, extra: str | None = None) -> str:
    label = format_branded_name(name, brand)
    parts = [label]
    if extra:
        parts.append(extra)
    if calories is not None:
        parts.append(f"{int(round(calories))} calories")
    return ", ".join(parts)


def _build_grounded_alternatives(parsed: dict, nutrition: dict) -> list[str]:
    """Human-readable alternatives derived from the actual data: other likely
    foods (identity) and, when the food is clear but the amount isn't, real
    portion sizes (amount). Returns [] when nothing grounded is available so
    the caller can fall back to the model's suggestions."""
    chosen_name = (nutrition.get("food_name") or "").strip().lower()
    alternatives: list[str] = []

    # Other candidate foods the user might have meant.
    for candidate in nutrition.get("candidates", []):
        name = (candidate.get("name") or "").strip()
        if not name or name.lower() == chosen_name:
            continue
        alternatives.append(
            _format_alt(
                name,
                candidate.get("brand"),
                candidate.get("calories"),
                extra=candidate.get("serving_label"),
            )
        )
        if len(alternatives) >= 3:
            break

    # If the food itself is clear, offer real portion sizes instead.
    portion_options = nutrition.get("portion_options", [])
    if not alternatives and len(portion_options) > 1:
        for option in portion_options[:3]:
            alternatives.append(
                _format_alt(
                    nutrition.get("food_name") or "food",
                    nutrition.get("brand"),
                    option.get("calories"),
                    extra=option.get("label"),
                )
            )

    return alternatives


async def _fetch_dietary_preferences(user_id: str | None):
    """
    NEW (2026-08-04): look up the user's saved dietary preferences so
    lookup_food() can apply Tier 1 hard filters (allergens, vegan, etc.) and
    Tier 2 soft boosts (organic, keto, etc.). Returns None when no user_id is
    given or no profile exists yet — lookup_food() treats None the same as
    "no dietary constraints," so this fails open to unrestricted search
    rather than failing closed / erroring.
    """
    if not user_id:
        return None
    user_profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not user_profile:
        return None
    return user_profile.dietary_preferences


async def parse_food_input(
    raw_input: str,
    conversation_history: list = [],
    source_filter: str | None = None,
    user_id: str | None = None,
) -> dict:
    # If this is a clarification, combine with previous food
    if conversation_history:
        try:
            last_assistant = next(
                m for m in reversed(conversation_history) if m["role"] == "assistant"
            )
            prev = json.loads(last_assistant["content"])
            food = prev.get("food")
            if food:
                raw_input = f"{raw_input} of {food}"
        except Exception:
            pass

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": raw_input})    
    print("MESSAGES SENT TO GPT:", json.dumps(messages, indent=2))
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2,
        max_tokens=400,
    )

    content = response.choices[0].message.content.strip()

    print("GPT response:", content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw_response": content}

    # Return early if unparseable
    if "error" in parsed:
        return parsed

    parsed = _apply_confidence_guards(parsed, raw_input)

    # Extract modifiers from the user's raw input — independent of GPT's
    # parsing, word-boundary matching on the same 13 categories as the
    # database-side extractor.
    modifiers = parse_query_modifiers(raw_input)
    parsed["modifiers"] = modifiers

    non_none_mods = {k: v for k, v in modifiers.items() if v != "NONE"}
    if non_none_mods:
        print(f"Extracted modifiers: {non_none_mods}")

    # Did the user explicitly name a brand? If so, we skip the brand-vs-generic
    # question entirely and go straight to branded results — the answer's known.
    stated_brand = (parsed.get("brand") or "").strip()
    effective_source = source_filter
    if effective_source is None and stated_brand:
        effective_source = "brand"

    # NEW (2026-08-04): fetch the user's dietary preferences (allergens,
    # vegan/kosher/etc, organic/keto/etc) so lookup_food can apply them.
    dietary_preferences = await _fetch_dietary_preferences(user_id)

    food_query = parsed['food']
    print("calling lookup_food with:", food_query, "| source:", effective_source, "| modifiers:", non_none_mods)
    nutrition = await lookup_food(
        food_query,
        source_filter=effective_source,
        modifiers=modifiers,
        dietary_preferences=dietary_preferences,
    )

    # NEW (2026-08-04): lookup_food returns a distinct shape when a severe
    # allergen constraint produced zero safe results — no calories/candidates
    # to process, just a safety message. Handle this BEFORE the normal
    # `if nutrition:` branch, which assumes standard nutrition fields exist.
    #
    # NOTE: introduces a 4th confidence-like state, "blocked", alongside the
    # existing high/medium/low. If the frontend/voice layer only branches on
    # those three values, it will need a small update to handle this state
    # explicitly — not verified against that code from here.
    if nutrition and nutrition.get("blocked_by_allergy"):
        parsed["confidence"] = "blocked"
        parsed["calories"] = None
        parsed["macronutrients"] = {"carbohydrates": None, "protein": None, "fats": None}
        parsed["data_source"] = "allergy_block"
        parsed["reasoning"] = nutrition.get("message")
        parsed["candidates"] = []
        parsed["portion_options"] = []
        parsed["alternatives"] = []
        return parsed

    if nutrition:
        # Use Current food data source data
        parsed["calories"] = nutrition["calories"]
        parsed["macronutrients"] = {
            "carbohydrates": nutrition["carbs"],
            "protein": nutrition["protein"],
            "fats": nutrition["fat"],
        }
        parsed["data_source"] = "usda"

        # Serving/brand context, straight from the matched record.
        parsed["brand"] = nutrition.get("brand") or None
        parsed["serving_label"] = nutrition.get("serving_label")
        parsed["serving_note"] = nutrition.get("serving_note")

        # Grounded choices from the data (real foods + real portions), so the
        # frontend can offer accurate, priced alternatives instead of guesses.
        parsed["candidates"] = nutrition.get("candidates", [])
        parsed["portion_options"] = nutrition.get("portion_options", [])

        # NEW (2026-08-04): surface whether a non-allergen Tier 1 constraint
        # (vegan, kosher, etc.) had to be relaxed to find any results, so the
        # voice/UI layer can say something like "no vegan options found,
        # here's what I found instead" rather than presenting a silently
        # relaxed result as an exact match.
        parsed["used_dietary_fallback"] = nutrition.get("used_dietary_fallback", False)

        # Extra macros/micros scaled to serving (fiber, sodium, vitamins, …).
        parsed["nutrients"] = dict(nutrition.get("nutrients") or {})

        # Allergen tags for POST/PATCH allergy gate (severe block / moderate warn).
        parsed["allergens"] = nutrition.get("allergens") or []
        for allergen_name in FDA_ALLERGENS:
            if allergen_name in nutrition:
                parsed[allergen_name] = nutrition[allergen_name]

        # Scale per-serving nutrition by the parsed quantity (e.g. "2" eggs).
        quantity = parse_quantity_multiplier(parsed.get("serving_size", "1"))

        if quantity > 1:
            if parsed["calories"] is not None:
                parsed["calories"] = int(round(parsed["calories"] * quantity))
            macros = parsed["macronutrients"]
            for macro_key in ("protein", "carbohydrates", "fats"):
                if macros.get(macro_key) is not None:
                    macros[macro_key] = round(macros[macro_key] * quantity, 1)
            nutrients = parsed.get("nutrients") or {}
            for nk, nv in list(nutrients.items()):
                if nv is not None:
                    try:
                        nutrients[nk] = round(float(nv) * quantity, 2)
                    except (TypeError, ValueError):
                        pass
            parsed["nutrients"] = nutrients

        parsed["quantity_used"] = quantity
        print(f"quantity: {quantity}, calories after: {parsed['calories']}")
        logger.info(
            "quantity_used=%s calories_after=%s serving_size=%r",
            quantity,
            parsed.get("calories"),
            parsed.get("serving_size"),
        )

        # Never silently high-confidence-log a degenerate 0 kcal for a food that
        # should have calories (bad branded USDA rows). Atwater usually fills
        # this in lookup; this is the last-resort safety net.
        cal = parsed.get("calories")
        try:
            cal_f = float(cal) if cal is not None else None
        except (TypeError, ValueError):
            cal_f = None
        if (
            cal_f is not None
            and cal_f <= 0.5
            and not is_zero_calorie_query(food_query)
            and not is_zero_calorie_query(raw_input or "")
        ):
            parsed["confidence"] = "low"
            note = "Nutrition data looks incomplete (0 calories for this food)."
            parsed["reasoning"] = (
                f"{parsed['reasoning']} {note}".strip()
                if parsed.get("reasoning")
                else note
            )

        # Consolidated resolver: even when the model was confident about the
        # TEXT, the DATA may show the plausible interpretations disagree on
        # calories (e.g. "milk" -> skim ~83 vs whole ~149). When that happens
        # we drop to "medium" so the app asks one grounded question instead of
        # silently logging a coin-flip. Runs BEFORE the alternatives block so a
        # downgrade still populates the options the user will pick from.
        resolution = nutrition.get("resolution") or {}
        parsed["resolution"] = resolution

        # Brand-vs-generic gate: when the user named no brand AND we haven't yet
        # filtered by source AND the pool is genuinely ambiguous, ask ONE
        # upfront question (brand vs generic) instead of showing a mixed list of
        # branded products, generics, and substitutes. The answer re-queries
        # with a source filter (see routes + frontend), and only THEN do we
        # build the candidate/portion list — now from a single clean source.
        if (
            source_filter is None
            and not stated_brand
            and resolution.get("status") == "needs_clarification"
        ):
            parsed["confidence"] = "medium"
            brand_reason = (
                "Could be a specific brand or a general item — the calories "
                "differ a lot."
            )
            parsed["resolution"] = {
                "status": "needs_brand_choice",
                "axis": "brand",
                "reason": brand_reason,
                "question": BRAND_CHOICE_QUESTION,
            }
            parsed["reasoning"] = brand_reason
            # Withhold the mixed list; the filtered follow-up query builds it.
            parsed["candidates"] = []
            parsed["portion_options"] = []
            parsed["alternatives"] = []
            return _apply_confidence_guards(parsed, raw_input)

        if resolution.get("status") == "needs_clarification":
            if parsed.get("confidence") == "high":
                parsed["confidence"] = "medium"
            # Prefer the data-driven reason over GPT "food is clear…" copy so
            # the Less Sure card matches why we're asking.
            data_reason = resolution.get("reason")
            if data_reason:
                parsed["reasoning"] = data_reason

        # For medium/low confidence, prefer data-grounded alternatives over the
        # model's free-text guesses: real, priced options the user can pick.
        if parsed.get("confidence") != "high":
            parsed["alternatives"] = _build_grounded_alternatives(
                parsed, nutrition
            ) or parsed.get("alternatives")
    else:
        # Current food data source found nothing — ask GPT to estimate as fallback
        parsed["calories"] = None
        parsed["macronutrients"] = {"carbohydrates": None, "protein": None, "fats": None, "sugar": None}
        parsed["confidence"] = "low"
        parsed["reasoning"] = (parsed.get("reasoning") or "") + " Nutrition data unavailable — estimate only."
        parsed["data_source"] = "gpt_fallback"

    return _apply_confidence_guards(parsed, raw_input)
