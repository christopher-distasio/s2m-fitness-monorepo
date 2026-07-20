"""Unit tests for query-match re-ranking (no Pinecone / network)."""
from backend.services.query_match_rank import (
    is_zero_calorie_query,
    near_zero_calorie_penalty,
    query_match_score,
    rerank_matches_by_query,
)


def _match(
    name: str,
    score: float,
    brand: str = "",
    calories: float | None = None,
) -> dict:
    meta: dict = {"name": name}
    if brand:
        meta["brand_name"] = brand
    if calories is not None:
        meta["calories"] = calories
    return {"id": name, "score": score, "metadata": meta}


def test_banana_raw_beats_chips_and_bread():
    """Even when chips has a higher vector score, raw banana should win."""
    matches = [
        _match("Banana chips", 0.88),
        _match("BANANA BREAD", 0.86),
        _match("Bananas, raw", 0.81),
        _match("Plantains, raw", 0.79),
    ]
    ranked = rerank_matches_by_query("banana", matches)
    assert ranked[0]["metadata"]["name"] == "Bananas, raw"


def test_unbranded_beats_branded_same_name_stem():
    matches = [
        _match("BANANA CHIPS", 0.9, brand="SOME BRAND"),
        _match("Bananas, raw", 0.8),
    ]
    ranked = rerank_matches_by_query("banana", matches)
    assert ranked[0]["metadata"]["name"] == "Bananas, raw"


def test_milk_whole_still_covers_query():
    """Soft modifiers (whole, milkfat) shouldn't bury a real milk match."""
    score = query_match_score("milk", "Milk, whole, 3.25% milkfat")
    chipsish = query_match_score("milk", "Milk chocolate candy")
    assert score > chipsish


def test_chicken_breast_prefers_head_match():
    matches = [
        _match("Soup, chicken noodle, canned", 0.87),
        _match("Chicken, broilers or fryers, breast, meat only, raw", 0.84),
    ]
    ranked = rerank_matches_by_query("chicken breast", matches)
    assert "breast" in ranked[0]["metadata"]["name"].lower()
    assert "soup" not in ranked[0]["metadata"]["name"].lower()


def test_rerank_preserves_all_matches():
    matches = [_match("A", 0.5), _match("B", 0.4)]
    ranked = rerank_matches_by_query("a", matches)
    assert len(ranked) == 2


def test_zero_cal_ham_loses_to_real_ham():
    """Degenerate 0-kcal branded ham should not beat a real ham in the set."""
    matches = [
        _match("LEAN HAM SLICES", 0.91, brand="Kroger", calories=0),
        _match("Ham, sliced, extra lean (approximately 5% fat)", 0.88, calories=110),
        _match("Ham, honey, smoked", 0.86, calories=140),
    ]
    ranked = rerank_matches_by_query("Kroger Lean Ham slices", matches)
    assert ranked[0]["metadata"]["calories"] > 5
    assert "ham" in ranked[0]["metadata"]["name"].lower()


def test_near_zero_penalty_breaks_ham_near_tie():
    """Small penalty alone flips a near-tie between 0-kcal and real ham."""
    matches = [
        _match("Ham, lean, sliced", 0.90, calories=0),
        _match("Ham, lean, sliced, select", 0.89, calories=120),
    ]
    ranked = rerank_matches_by_query("lean ham sliced", matches)
    assert ranked[0]["metadata"]["calories"] == 120


def test_near_zero_penalty_skipped_for_water():
    assert is_zero_calorie_query("water")
    assert is_zero_calorie_query("sparkling water")
    assert near_zero_calorie_penalty("water", {"calories": 0}) == 0.0
    matches = [
        _match("Water, municipal", 0.9, calories=0),
        _match("Ham, sliced", 0.55, calories=120),
    ]
    ranked = rerank_matches_by_query("water", matches)
    assert ranked[0]["metadata"]["name"].lower().startswith("water")
    assert ranked[0]["metadata"]["calories"] == 0


def test_water_zero_not_demoted_when_caloric_noise_present():
    """Zero-cal water stays on top even if a caloric food is also retrieved."""
    matches = [
        _match("Water", 0.95, calories=0),
        _match("Water chestnuts, canned", 0.7, calories=50),
    ]
    ranked = rerank_matches_by_query("water", matches)
    assert ranked[0]["metadata"]["calories"] == 0


def test_near_zero_penalty_skipped_for_black_coffee_and_diet_soda():
    assert is_zero_calorie_query("black coffee")
    assert is_zero_calorie_query("coffee")
    assert is_zero_calorie_query("diet coke")
    assert not is_zero_calorie_query("coffee cake")
    assert not is_zero_calorie_query("ham")
    assert near_zero_calorie_penalty("black coffee", {"calories": 2}) == 0.0
    assert near_zero_calorie_penalty("diet soda", {"calories": 0}) == 0.0

    # 0-kcal coffee must NOT be demoted to a caloric coffee-cake neighbor.
    matches = [
        _match("Coffee, black, brewed", 0.92, calories=0),
        _match("Coffee cake, creme-filled", 0.8, calories=350),
    ]
    ranked = rerank_matches_by_query("black coffee", matches)
    assert ranked[0]["metadata"]["name"].lower().startswith("coffee")
    assert "cake" not in ranked[0]["metadata"]["name"].lower()
    assert ranked[0]["metadata"]["calories"] == 0

    diet = [
        _match("Diet Coke", 0.9, brand="Coca-Cola", calories=0),
        _match("Cola, regular", 0.7, calories=140),
    ]
    ranked_diet = rerank_matches_by_query("diet coke", diet)
    assert ranked_diet[0]["metadata"]["calories"] == 0


def test_atwater_fills_zero_calorie_branded_ham():
    """Branded rows often have macros but calories=0 — estimate instead of logging 0."""
    from backend.services.query_match_rank import effective_calories_per_100g

    meta = {"calories": 0, "protein": 18, "carbs": 2, "fat": 4}
    # 4*18 + 4*2 + 9*4 = 72+8+36 = 116
    assert effective_calories_per_100g(meta) == 116

    matches = [
        _match(
            "SMOKED DELI STYLE LEAN HAM, SMOKED",
            0.95,
            brand="Kroger",
            calories=0,
        ),
    ]
    # Attach macros onto the zero-cal row
    matches[0]["metadata"]["protein"] = 18
    matches[0]["metadata"]["carbs"] = 2
    matches[0]["metadata"]["fat"] = 4
    ranked = rerank_matches_by_query("Kroger smoked deli lean ham", matches)
    assert ranked[0]["metadata"]["name"].startswith("SMOKED")
    # Penalty should not apply once Atwater effective calories are real.
    assert near_zero_calorie_penalty(
        "Kroger smoked deli lean ham", matches[0]["metadata"]
    ) == 0.0


def test_caloric_query_penalizes_near_zero_candidate():
    assert not is_zero_calorie_query("Kroger Lean Ham slices")
    assert near_zero_calorie_penalty(
        "Kroger Lean Ham slices", {"calories": 0}
    ) > 0
    assert (
        near_zero_calorie_penalty(
            "Kroger Lean Ham slices", {"calories": 110}
        )
        == 0.0
    )
