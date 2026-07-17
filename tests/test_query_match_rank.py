"""Unit tests for query-match re-ranking (no Pinecone / network)."""
from backend.services.query_match_rank import (
    query_match_score,
    rerank_matches_by_query,
)


def _match(name: str, score: float, brand: str = "") -> dict:
    meta = {"name": name}
    if brand:
        meta["brand_name"] = brand
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
