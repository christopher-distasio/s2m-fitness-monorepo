# Cheap local CI helpers — see docs/S2M_Cheap_Simple_CI_Plan.docx

.PHONY: test test-live test-eval test-nutrition-live

# Default merge gate: no Qdrant/GPT required
test:
	poetry run pytest tests/ -q -m "not live"

# Local Qdrant fixtures + dietary lookup (needs localhost:6333)
test-live:
	poetry run pytest tests/ -q -m live --tb=short

# GPT food-parser eval suite (API cost)
test-eval:
	poetry run pytest tests/eval_food_parser.py -v -s -m live

# Nutrition/allergen Qdrant fixtures only
test-nutrition-live:
	poetry run pytest tests/eval_nutrition_allergens.py -v -m live
