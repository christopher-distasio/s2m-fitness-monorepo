"""With a brand named, a product missing a food word the user said loses."""
from backend.services.query_match_rank import missing_food_words, rerank_matches_by_query


def _m(fid, name, brand, score=0.7):
    return {"id": fid, "score": score, "metadata": {"description": name, "brand_name": brand, "calories": 300}}


def test_missing_food_word_counts_only_food_words():
    assert missing_food_words("trader joes orange chicken", "ORANGE JUICE", "Trader Joe's") == 1
    assert missing_food_words("trader joes orange chicken", "ORANGE CHICKEN", "Trader Joe's") == 0
    assert missing_food_words("kikkoman soy sauce", "SOY SAUCE", "Kikkoman") == 0


def test_no_brand_named_means_no_penalty():
    assert missing_food_words("orange chicken", "ORANGE JUICE", "") == 0


def test_right_product_beats_brand_word_match():
    # 2026-11-20 A/B: Trader Joe's orange juice won "trader joes orange chicken".
    juice = _m("1", "ORANGE JUICE", "TRADER JOE'S", score=0.80)
    chicken = _m("2", "MANDARIN ORANGE CHICKEN", "TRADER JOE'S", score=0.70)
    q = "trader joes orange chicken"
    assert rerank_matches_by_query(q, [juice, chicken], stated_brand="Trader Joe's")[0]["id"] == "2"
