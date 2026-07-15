import json
import re
from openai import AsyncOpenAI
from dotenv import load_dotenv
from backend.services.nutrition_service import lookup_food

load_dotenv()

client = AsyncOpenAI()

SYSTEM_PROMPT = """
You are a nutrition data parser for a food logging app.

The user will provide a natural language food description (typed or transcribed from voice).
Your job is to extract structured information and return ONLY valid JSON — no explanation, no markdown.

Return this exact shape:
{
  "food": "string — normalized food name, optimized for database lookup",
  "brand": "string — the brand/manufacturer the user EXPLICITLY named, else empty string",
  "serving_size": "string — e.g. '1 cup', '2 eggs', '1 medium'",
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
- Serving_size should be quantity only (e.g. '2', '1 cup'), not include the food name
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


def _format_alt(name: str, brand: str | None, calories, extra: str | None = None) -> str:
    label = f"{brand} {name}" if brand else name
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
            _format_alt(name, candidate.get("brand"), candidate.get("calories"))
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


async def parse_food_input(
    raw_input: str,
    conversation_history: list = [],
    source_filter: str | None = None,
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

    # Did the user explicitly name a brand? If so, we skip the brand-vs-generic
    # question entirely and go straight to branded results — the answer's known.
    stated_brand = (parsed.get("brand") or "").strip()
    effective_source = source_filter
    if effective_source is None and stated_brand:
        effective_source = "brand"

    # Step 2 — Current food data source looks up accurate nutrition data
    food_query = parsed['food']    
    print("calling lookup_food with:", food_query, "| source:", effective_source)
    nutrition = await lookup_food(food_query, source_filter=effective_source)

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

        # Scale per-serving nutrition by the parsed quantity (e.g. "2" eggs).
        quantity_str = parsed.get("serving_size", "1")
        try:
            quantity = float(quantity_str)
        except (TypeError, ValueError):
            quantity = 1.0

        if quantity > 1:
            if parsed["calories"] is not None:
                parsed["calories"] = int(round(parsed["calories"] * quantity))
            macros = parsed["macronutrients"]
            for macro_key in ("protein", "carbohydrates", "fats"):
                if macros.get(macro_key) is not None:
                    macros[macro_key] = round(macros[macro_key] * quantity, 1)

        parsed["quantity_used"] = quantity
        print(f"quantity: {quantity}, calories after: {parsed['calories']}")

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
            parsed["resolution"] = {
                "status": "needs_brand_choice",
                "axis": "brand",
                "reason": (
                    "Could be a specific brand or a general item — the calories "
                    "differ a lot."
                ),
                "question": BRAND_CHOICE_QUESTION,
            }
            # Withhold the mixed list; the filtered follow-up query builds it.
            parsed["candidates"] = []
            parsed["portion_options"] = []
            parsed["alternatives"] = []
            return _apply_confidence_guards(parsed, raw_input)

        if (
            resolution.get("status") == "needs_clarification"
            and parsed.get("confidence") == "high"
        ):
            parsed["confidence"] = "medium"
            if not parsed.get("reasoning"):
                parsed["reasoning"] = resolution.get("reason")

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