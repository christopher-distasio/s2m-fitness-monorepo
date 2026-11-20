"""No brand named: try plain USDA foods first, keep the brand question as fallback."""
import pytest

import backend.services.food_parser as fp
from backend.services.query_match_rank import is_exact_plain_match


def test_exact_plain_match():
    assert is_exact_plain_match("banana", "Bananas, raw")
    assert is_exact_plain_match("scrambled egg", "Egg, whole, cooked, scrambled")
    assert not is_exact_plain_match("chicken", "Chicken, back")
    assert not is_exact_plain_match("nutella", "Nutella sandwich on white bread")
    assert not is_exact_plain_match("froot loops", "Cereal, fruit rings")


def _nutrition(name, status="resolved"):
    return {"food_name": name, "calories": 100.0, "protein": 1.0, "carbs": 20.0, "fat": 0.5,
            "serving_size_g": 100.0, "serving_label": "1 medium", "candidates": [],
            "portion_options": [], "resolution": {"status": status, "axis": "identity" if status != "resolved" else None},
            "nutrients": {}, "allergens": []}


async def _run(monkeypatch, food, plain_name):
    calls = []

    async def fake_lookup(query, source_filter=None, **kw):
        calls.append(source_filter)
        if source_filter == "generic":
            return _nutrition(plain_name)
        return _nutrition("KIRKLAND " + query.upper(), status="needs_clarification")

    monkeypatch.setattr(fp, "lookup_food", fake_lookup)
    parsed = {"food": food, "brand": "", "serving_size": "1", "quantity_kind": "count", "modifiers": {}}
    out = await fp._enrich_with_nutrition(parsed, raw_input=food, source_filter=None, dietary_preferences=None)
    return out, calls


@pytest.mark.asyncio
async def test_exact_plain_match_skips_brand_question(monkeypatch):
    out, calls = await _run(monkeypatch, "banana", "Bananas, raw")
    assert calls == ["generic"]
    assert (out.get("resolution") or {}).get("status") != "needs_brand_choice"


@pytest.mark.asyncio
async def test_inexact_plain_match_falls_back_to_brand_question(monkeypatch):
    out, calls = await _run(monkeypatch, "chicken", "Chicken, back")
    assert calls == ["generic", None]
    assert out["resolution"]["status"] == "needs_brand_choice"
