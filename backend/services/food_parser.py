from openai import AsyncOpenAI
import os
import json
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You are a nutrition data parser for a food logging app.

The user will provide a natural language food description (typed or transcribed from voice).
Your job is to extract structured nutrition data and return ONLY valid JSON — no explanation, no markdown.

Return this exact shape:
{
  "food": "string — normalized food name",
  "calories": integer,
  "serving_size": "string — e.g. '1 cup', '2 eggs', '1 medium'",
  "macronutrients": {
    "carbohydrates": float,
    "protein": float,
    "fats": float,
    "sugar": float
  },
  "confidence": "high" | "medium" | "low",
  "notes": "string — optional clarification or assumption made",
  "reasoning": "string — optional short explanation of confidence",
  "alternatives": ["string — optional list of likely intended interpretations"]
}

Rules:
- Use standard USDA-style estimates when exact data is unavailable
- If multiple foods are mentioned, combine them into one entry with a descriptive name (e.g. "2 eggs and black coffee")
- If the input is completely unparseable as food, return { "error": "unparseable", "raw": "<input>" }
- Never guess wildly — if uncertain, set confidence to "low" and explain in notes
- If the input is a single common food with an explicit quantity/size (e.g. "one large banana", "2 eggs", "1 cup oatmeal"),
  you should generally be confident and set "confidence" to "high" unless something is genuinely ambiguous.
"""

async def parse_food_input(raw_input: str) -> dict:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_input}
        ],
        temperature=0.2,
        max_tokens=300,
    )

    content = response.choices[0].message.content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw_response": content}