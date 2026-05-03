import json
from openai import AsyncOpenAI
from dotenv import load_dotenv
from backend.services.edamam_service import lookup_food

load_dotenv()

client = AsyncOpenAI()

SYSTEM_PROMPT = """
You are a nutrition data parser for a food logging app.

The user will provide a natural language food description (typed or transcribed from voice).
Your job is to extract structured information and return ONLY valid JSON — no explanation, no markdown.

Return this exact shape:
{
  "food": "string — normalized food name, optimized for database lookup",
  "serving_size": "string — e.g. '1 cup', '2 eggs', '1 medium'",
  "confidence": "high" | "medium" | "low",
  "notes": "string — optional clarification or assumption made",
  "reasoning": "string — optional short explanation of confidence",
  "alternatives": ["string — optional list of likely intended interpretations"]
}

Rules:
- Do NOT include calories or macronutrients — those come from the nutrition database
- Normalize the food name for database lookup (e.g. "two scrambled eggs" -> "scrambled eggs")
- If multiple foods are mentioned, combine them into one descriptive name (e.g. "2 eggs and black coffee")
- If the input is completely unparseable as food, return { "error": "unparseable", "raw": "<input>" }
- Never guess wildly — if uncertain, set confidence to "low" and explain in notes
- If the input is a single common food with an explicit quantity/size, set "confidence" to "high" unless something is genuinely ambiguous
- Only return { "error": "unparseable", "raw": "<input>" } if the input has absolutely nothing to do with food

Confidence rules:
- "high": food and quantity are clear and specific (e.g. "one banana", "two scrambled eggs")
- "medium": food is clear but quantity is vague or assumed, or food type is ambiguous but guessable
- "low": food is ambiguous, heavily vague, or both food type and quantity are unknown

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

async def parse_food_input(raw_input: str, conversation_history: list = []) -> dict:
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

    # Step 2 — Edamam looks up accurate nutrition data
    food_query = f"{parsed.get('serving_size', '')} {parsed['food']}".strip()
    nutrition = await lookup_food(food_query)

    if nutrition:
        # Use Edamam data
        parsed["calories"] = nutrition["calories"]
        parsed["macronutrients"] = {
            "carbohydrates": nutrition["carbs"],
            "protein": nutrition["protein"],
            "fats": nutrition["fat"],
        }
        parsed["data_source"] = "edamam"
    else:
        # Edamam found nothing — ask GPT to estimate as fallback
        parsed["calories"] = None
        parsed["macronutrients"] = {"carbohydrates": None, "protein": None, "fats": None, "sugar": None}
        parsed["confidence"] = "low"
        parsed["reasoning"] = (parsed.get("reasoning") or "") + " Nutrition data unavailable — estimate only."
        parsed["data_source"] = "gpt_fallback"

    return parsed