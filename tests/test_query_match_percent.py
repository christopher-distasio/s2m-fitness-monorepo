"""Percentages in the lexical re-rank ("0%", "0 percent", "zero percent")."""
from backend.services.query_match_rank import _tokenize, query_match_score


def test_percent_spellings_tokenize_alike():
    assert "0pct" in _tokenize("Fage Total 0% Greek")
    assert "0pct" in _tokenize("fage total 0 percent yogurt")
    assert "0pct" in _tokenize("zero percent yogurt")
    assert "2pct" in _tokenize("greek yogurt two percent")
    assert "2p5pct" in _tokenize("2.5% fat")


def test_stated_percentage_beats_a_different_one():
    # 2026-11-20 triage: the 5% yogurt won "fage total 0 percent yogurt".
    q = "fage total 0 percent yogurt"
    assert query_match_score(q, "TOTAL 0% NONFAT GREEK STRAINED YOGURT", "FAGE") > \
        query_match_score(q, "Fage Total 5% Greek Strained Yogurt", "Fage")


def test_percentage_on_product_is_neutral_when_query_has_none():
    q = "greek yogurt"
    assert query_match_score(q, "Fage Total 2% Greek Yogurt", "Fage") == \
        query_match_score(q, "Fage Total 5% Greek Yogurt", "Fage")


def test_stated_milk_percentage_beats_whole():
    q = "organic valley 2 percent milk"
    assert query_match_score(q, "Organic Valley Milk, Reduced Fat, 2% Milk Fat", "Organic Valley") > \
        query_match_score(q, "Organic Valley Whole Milk", "Organic Valley")


def test_whole_milk_query_unchanged_by_percent_rule():
    q = "whole milk"
    assert query_match_score(q, "Whole Milk", "") > query_match_score(q, "2% Reduced Fat Milk", "")
