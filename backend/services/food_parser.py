import json
import logging
import re
from openai import AsyncOpenAI
from dotenv import load_dotenv
from backend.services.nutrition_service import (
    NutritionStoreUnavailable,
    format_branded_name,
    lookup_food,
)
from backend.services.query_match_rank import is_zero_calorie_query
from backend.services.parse_query_modifiers import parse_query_modifiers
from backend.services.dietary_filters import FDA_ALLERGENS
from backend.models import UserProfile
from backend.services.confidence import extract_semantic_logprob
from backend.services.food_event_build import (
    food_event_from_parsed,
    utterance_from_parsed_events,
)

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
- amount, when present, MUST be a JSON number (2, 1.5) — never a string like "2 bananas"
- If the user names multiple distinct foods ("eggs, toast, and coffee"), put each in "items" as its own object with its own food/brand/serving_size. A single food stays in the top-level fields (items may be []).
- Direct macro dictation ("just log 300 calories") is entry_mode "direct_macro": food may be null and calories is the user-stated number. That is not a lookup failure.
- Always return a non-empty serving_size for resolved food items
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

# Strict structured output — amount is a number so "2 bananas" cannot occupy it.
PARSE_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "unparseable": {"type": "boolean"},
        "hedged": {"type": "boolean"},
        "entry_mode": {"type": "string", "enum": ["resolved", "direct_macro"]},
        "item_type": {"type": "string", "enum": ["food", "beverage", "supplement"]},
        "food": {"type": ["string", "null"]},
        "brand": {"type": "string"},
        "serving_size": {"type": "string"},
        "amount": {"type": ["number", "null"]},
        "unit": {"type": "string"},
        "quantity_kind": {"type": "string", "enum": ["count", "measure"]},
        "calories": {"type": ["number", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "notes": {"type": "string"},
        "reasoning": {"type": "string"},
        "alternatives": {"type": "array", "items": {"type": "string"}},
        "error": {"type": ["string", "null"]},
        "raw": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "food": {"type": ["string", "null"]},
                    "brand": {"type": "string"},
                    "item_type": {
                        "type": "string",
                        "enum": ["food", "beverage", "supplement"],
                    },
                    "serving_size": {"type": "string"},
                    "amount": {"type": ["number", "null"]},
                    "unit": {"type": "string"},
                    "quantity_kind": {"type": "string", "enum": ["count", "measure"]},
                    "calories": {"type": ["number", "null"]},
                    "entry_mode": {
                        "type": "string",
                        "enum": ["resolved", "direct_macro"],
                    },
                },
                "required": [
                    "food",
                    "brand",
                    "item_type",
                    "serving_size",
                    "amount",
                    "unit",
                    "quantity_kind",
                    "calories",
                    "entry_mode",
                ],
            },
        },
    },
    "required": [
        "unparseable",
        "hedged",
        "entry_mode",
        "item_type",
        "food",
        "brand",
        "serving_size",
        "amount",
        "unit",
        "quantity_kind",
        "calories",
        "confidence",
        "notes",
        "reasoning",
        "alternatives",
        "error",
        "raw",
        "items",
    ],
}

QUANTITY_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "amount": {"type": "number"},
        "unit": {"type": "string"},
        "quantity_kind": {"type": "string", "enum": ["count", "measure"]},
        "serving_size": {"type": "string"},
        "hydration_state": {"type": ["string", "null"], "enum": ["dry", "cooked", None]},
        "consumption_fraction": {"type": "number"},
        "consumption_fraction_stated": {"type": "boolean"},
    },
    "required": [
        "amount",
        "unit",
        "quantity_kind",
        "serving_size",
        "hydration_state",
        "consumption_fraction",
        "consumption_fraction_stated",
    ],
}

_DIRECT_MACRO_RE = re.compile(
    r"(?:just\s+)?log\s+(\d+(?:\.\d+)?)\s*(?:cal(?:orie)?s?)\b",
    re.IGNORECASE,
)

UNRECOGNIZED_MESSAGE = (
    "I didn't recognize that as a food I can look up. "
    "Please try a different name or more detail."
)

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


def _direct_macro_parsed(raw_input: str) -> dict | None:
    match = _DIRECT_MACRO_RE.search(raw_input or "")
    if not match:
        return None
    calories = float(match.group(1))
    return {
        "food": None,
        "brand": "",
        "entry_mode": "direct_macro",
        "item_type": "food",
        "serving_size": "1",
        "amount": 1.0,
        "unit": "count",
        "quantity_kind": "count",
        "calories": calories,
        "macronutrients": {"carbohydrates": None, "protein": None, "fats": None},
        "confidence": "high",
        "notes": "User-stated energy amount; no food lookup.",
        "reasoning": "Direct calorie entry — nothing to resolve.",
        "alternatives": [],
        "resolution_status": "resolved",
        "resolution": {"status": "resolved"},
        "data_source": "user_stated",
    }


def _split_parsed_items(parsed: dict) -> list[dict]:
    items = parsed.get("items")
    if isinstance(items, list) and items:
        shared = {
            k: v
            for k, v in parsed.items()
            if k not in {"items", "food", "brand", "serving_size", "amount", "unit"}
        }
        out = []
        for item in items:
            merged = dict(shared)
            merged.update(item)
            out.append(merged)
        return out
    return [parsed]


async def _complete_json(
    messages: list,
    schema: dict | None = None,
    *,
    max_tokens: int = 600,
) -> tuple[dict, object, bool]:
    """Return (parsed_dict, raw_response, extraction_failed)."""
    extraction_failed = False
    kwargs: dict = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "logprobs": True,
        "top_logprobs": 3,
    }
    if schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "food_parse",
                "strict": True,
                "schema": schema,
            },
        }
    try:
        response = await client.chat.completions.create(**kwargs)
    except Exception:
        logger.exception("Structured GPT call failed; retrying without schema/logprobs")
        extraction_failed = True
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )

    content = (response.choices[0].message.content or "").strip()
    print("GPT response:", content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw_response": content}, response, True
    if not isinstance(parsed, dict):
        return {"error": "parse_failed", "raw_response": content}, response, True
    return parsed, response, extraction_failed


def _finalize_utterance(
    parsed_items: list[dict],
    *,
    raw_input: str,
    user_id: str | None,
    input_modality: str,
    activation: str | None,
    asr: float | None,
    semantic: float | None,
    extraction_failed: bool,
) -> dict:
    subject = user_id or "anonymous"
    events = [
        food_event_from_parsed(
            item,
            raw_input=raw_input,
            asr=asr,
            semantic=semantic,
            extraction_failed=extraction_failed,
        )
        for item in parsed_items
    ]
    utterance = utterance_from_parsed_events(
        events,
        subject_user_id=subject,
        raw_input=raw_input,
        input_modality=input_modality,
        activation=activation,
    )
    return utterance.to_parse_response()


async def parse_food_input(
    raw_input: str,
    conversation_history: list = [],
    source_filter: str | None = None,
    user_id: str | None = None,
    *,
    input_modality: str = "text",
    activation: str | None = None,
    asr: float | None = None,
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

    extraction_failed = False
    semantic = None
    parsed: dict

    direct = _direct_macro_parsed(raw_input) if not conversation_history else None
    if direct:
        parsed = direct
    else:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": raw_input})
        print("MESSAGES SENT TO GPT:", json.dumps(messages, indent=2))
        parsed, response, extraction_failed = await _complete_json(
            messages, PARSE_JSON_SCHEMA
        )
        try:
            semantic = extract_semantic_logprob(response, parsed.get("food"))
        except Exception:
            logger.exception("semantic logprob extraction failed")
            extraction_failed = True
            semantic = None

    if parsed.get("error") not in (None, ""):
        if parsed.get("error") == "unparseable" and conversation_history:
            pass
        else:
            return parsed

    if parsed.get("unparseable") and not conversation_history:
        return {"error": "unparseable", "raw": raw_input}

    parsed = _apply_confidence_guards(parsed, raw_input)

    modifiers = parse_query_modifiers(raw_input)
    parsed["modifiers"] = modifiers
    non_none_mods = {k: v for k, v in modifiers.items() if v != "NONE"}
    if non_none_mods:
        print(f"Extracted modifiers: {non_none_mods}")

    items = _split_parsed_items(parsed)
    dietary_preferences = await _fetch_dietary_preferences(user_id)
    enriched: list[dict] = []
    for item in items:
        item["modifiers"] = modifiers
        if item.get("entry_mode") == "direct_macro" or (
            not item.get("food") and item.get("calories") is not None
        ):
            item["entry_mode"] = "direct_macro"
            item["resolution_status"] = "resolved"
            item["resolution"] = {"status": "resolved"}
            item["data_source"] = item.get("data_source") or "user_stated"
            enriched.append(item)
            continue
        filled = await _enrich_with_nutrition(
            item,
            raw_input=raw_input,
            source_filter=source_filter,
            dietary_preferences=dietary_preferences,
        )
        if filled.get("error") == "nutrition_unavailable":
            return filled
        enriched.append(filled)

    return _finalize_utterance(
        enriched,
        raw_input=raw_input,
        user_id=user_id,
        input_modality=input_modality,
        activation=activation,
        asr=asr,
        semantic=semantic,
        extraction_failed=extraction_failed,
    )


async def _enrich_with_nutrition(
    parsed: dict,
    *,
    raw_input: str,
    source_filter: str | None,
    dietary_preferences,
) -> dict:
    stated_brand = (parsed.get("brand") or "").strip()
    effective_source = source_filter
    if effective_source is None and stated_brand:
        effective_source = "brand"

    food_query = parsed.get("food")
    if not food_query:
        parsed["confidence"] = "low"
        parsed["resolution_status"] = "unresolved"
        parsed["resolution"] = {
            "status": "unresolved",
            "reason": UNRECOGNIZED_MESSAGE,
        }
        parsed["reasoning"] = UNRECOGNIZED_MESSAGE
        parsed["calories"] = None
        parsed["candidates"] = []
        parsed["alternatives"] = []
        return parsed

    print("calling lookup_food with:", food_query, "| source:", effective_source)
    try:
        nutrition = await lookup_food(
            food_query,
            source_filter=effective_source,
            modifiers=parsed.get("modifiers"),
            dietary_preferences=dietary_preferences,
        )
    except NutritionStoreUnavailable:
        logger.warning("Nutrition store unavailable for query %r", food_query)
        return {
            "error": "nutrition_unavailable",
            "message": (
                "Nutrition search is temporarily unavailable. Please try again."
            ),
            "raw": raw_input,
        }

    if nutrition and nutrition.get("blocked_by_allergy"):
        parsed["confidence"] = "blocked"
        parsed["blocked_by_allergy"] = True
        parsed["calories"] = None
        parsed["macronutrients"] = {"carbohydrates": None, "protein": None, "fats": None}
        parsed["data_source"] = "allergy_block"
        parsed["reasoning"] = nutrition.get("message")
        parsed["candidates"] = []
        parsed["portion_options"] = []
        parsed["alternatives"] = []
        parsed["resolution_status"] = "needs_clarification"
        return parsed

    if nutrition:
        parsed["calories"] = nutrition["calories"]
        parsed["macronutrients"] = {
            "carbohydrates": nutrition["carbs"],
            "protein": nutrition["protein"],
            "fats": nutrition["fat"],
        }
        parsed["data_source"] = "usda"
        parsed["source"] = nutrition.get("source")
        parsed["fdc_id"] = nutrition.get("fdc_id")
        parsed["database_score"] = nutrition.get("database_score")
        parsed["database_score_gap"] = nutrition.get("database_score_gap")

        parsed["brand"] = nutrition.get("brand") or parsed.get("brand") or None
        parsed["serving_label"] = nutrition.get("serving_label")
        parsed["serving_note"] = nutrition.get("serving_note")
        parsed["candidates"] = nutrition.get("candidates", [])
        parsed["portion_options"] = nutrition.get("portion_options", [])
        parsed["used_dietary_fallback"] = nutrition.get("used_dietary_fallback", False)
        parsed["nutrients"] = dict(nutrition.get("nutrients") or {})
        parsed["allergens"] = nutrition.get("allergens") or []
        for allergen_name in FDA_ALLERGENS:
            if allergen_name in nutrition:
                parsed[allergen_name] = nutrition[allergen_name]

        if parsed.get("amount") is not None:
            try:
                quantity = float(parsed["amount"])
            except (TypeError, ValueError):
                quantity = parse_quantity_multiplier(parsed.get("serving_size", "1"))
        else:
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
        parsed["amount"] = quantity
        print(f"quantity: {quantity}, calories after: {parsed['calories']}")
        logger.info(
            "quantity_used=%s calories_after=%s serving_size=%r",
            quantity,
            parsed.get("calories"),
            parsed.get("serving_size"),
        )

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
            parsed["resolution_status"] = "unresolved"
            parsed["resolution"] = {
                "status": "unresolved",
                "reason": "Nutrition data looks incomplete (0 calories for this food).",
            }
            note = "Nutrition data looks incomplete (0 calories for this food)."
            parsed["reasoning"] = (
                f"{parsed['reasoning']} {note}".strip()
                if parsed.get("reasoning")
                else note
            )

        resolution = nutrition.get("resolution") or {}
        parsed["resolution"] = resolution

        if (
            source_filter is None
            and not stated_brand
            and resolution.get("status") == "needs_clarification"
            and resolution.get("axis") != "lactose"
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
            parsed["resolution_status"] = "needs_clarification"
            parsed["reasoning"] = brand_reason
            parsed["candidates"] = []
            parsed["portion_options"] = []
            parsed["alternatives"] = []
            return _apply_confidence_guards(parsed, raw_input)

        if resolution.get("status") == "needs_clarification":
            parsed["resolution_status"] = "needs_clarification"
            if parsed.get("confidence") == "high":
                parsed["confidence"] = "medium"
            data_reason = resolution.get("reason")
            if data_reason:
                parsed["reasoning"] = data_reason

        if parsed.get("confidence") != "high":
            parsed["alternatives"] = _build_grounded_alternatives(
                parsed, nutrition
            ) or parsed.get("alternatives")
    else:
        parsed["calories"] = None
        parsed["macronutrients"] = {
            "carbohydrates": None,
            "protein": None,
            "fats": None,
            "sugar": None,
        }
        parsed["confidence"] = "low"
        parsed["reasoning"] = UNRECOGNIZED_MESSAGE
        parsed["data_source"] = None
        parsed["resolution_status"] = "unresolved"
        parsed["resolution"] = {
            "status": "unresolved",
            "reason": UNRECOGNIZED_MESSAGE,
        }
        parsed["candidates"] = []
        parsed["alternatives"] = parsed.get("alternatives") or []

    return _apply_confidence_guards(parsed, raw_input)
