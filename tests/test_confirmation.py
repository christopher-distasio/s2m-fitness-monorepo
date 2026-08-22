"""Spec 2 risk-weighted confirmation — policy table, ASK cap, questions, replies."""

from __future__ import annotations

from backend.models.food_event import CONFIDENCE_FIELD_KEYS
from backend.services.confirmation import (
    apply_self_repair,
    attach_confirmation,
    evaluate_confirmation,
    is_answerable_question,
    resolve_confirmation_reply,
)
from backend.services.confirmation_policy import (
    CONSEQUENCE_TIER,
    POLICY_TABLE,
    policy_action,
)
from backend.services.utterance_pipeline import PIPELINE_ORDER
import backend.services.utterance_pipeline as pipeline_mod


def _parsed(bands: dict[str, str] | None = None, **extra) -> dict:
    detail = {key: {"band": "high"} for key in CONFIDENCE_FIELD_KEYS}
    for key, band in (bands or {}).items():
        detail[key] = {"band": band}
    out = {
        "food": extra.pop("food", "yogurt"),
        "confidence_detail": detail,
        "candidates": extra.pop("candidates", []),
        "portion_options": extra.pop("portion_options", []),
        "allergen_state": extra.pop("allergen_state", {}),
    }
    out.update(extra)
    return out


def test_policy_table_covers_all_nine_cells():
    assert len(POLICY_TABLE) == 9
    for band in ("high", "medium", "low"):
        for tier in ("high", "medium", "low"):
            assert (band, tier) in POLICY_TABLE
    assert set(CONSEQUENCE_TIER) == set(CONFIDENCE_FIELD_KEYS)


def test_high_band_any_tier_is_silent():
    for field in CONFIDENCE_FIELD_KEYS:
        assert policy_action("high", field) == "SILENT"
    decision = evaluate_confirmation(_parsed(), "yogurt")
    assert decision.action == "SILENT"
    assert decision.question is None
    assert not decision.asked_fields


def test_low_allergen_or_negation_always_ask():
    for field in ("allergen_match", "negation"):
        decision = evaluate_confirmation(
            _parsed({field: "low", "food": "high"}),
            "yogurt",
        )
        assert decision.action == "ASK"
        assert field in decision.asked_fields


def test_three_ask_fields_yield_exactly_one_question_turn():
    decision = evaluate_confirmation(
        _parsed(
            {
                "allergen_match": "low",
                "food": "low",
                "amount": "low",
            }
        ),
        "some food",
        self_repaired=True,
    )
    assert decision.action == "ASK"
    assert len(decision.asked_fields) <= 2
    assert decision.question
    assert decision.question.count("?") <= 2
    # Remaining ASK-tier fields degrade to CONFIRM rather than a second turn.
    confirm_fields = {f for f, a in decision.field_actions.items() if a == "CONFIRM"}
    assert "food" in confirm_fields or "amount" in confirm_fields
    assert "allergen_match" in decision.asked_fields


def test_contrastive_when_two_or_three_candidates():
    candidates = [
        {"name": "dry rice", "calories": 200, "brand": ""},
        {"name": "cooked rice", "calories": 130, "brand": ""},
    ]
    decision = evaluate_confirmation(
        _parsed({"food": "low"}, candidates=candidates, food="rice"),
        "rice",
        self_repaired=True,
    )
    assert decision.action == "ASK"
    assert decision.question_kind == "contrastive"
    assert "dry rice" in (decision.question or "")
    assert "cooked rice" in (decision.question or "")
    assert "or" in (decision.question or "").lower()
    assert is_answerable_question(decision.question or "")


def test_narrowing_when_more_than_three_candidates():
    candidates = [
        {"name": "yogurt", "brand": "Chobani", "calories": 120},
        {"name": "yogurt", "brand": "Chobani", "calories": 118},
        {"name": "yogurt", "brand": "Fage", "calories": 90},
        {"name": "yogurt", "brand": "Fage", "calories": 88},
        {"name": "yogurt", "brand": "Dannon", "calories": 140},
    ]
    decision = evaluate_confirmation(
        _parsed({"food": "low"}, candidates=candidates, food="yogurt"),
        "yogurt",
        self_repaired=True,
    )
    assert decision.action == "ASK"
    assert decision.question_kind == "narrowing"
    assert is_answerable_question(decision.question or "")
    assert "calorie" not in (decision.question or "").lower()


def test_second_one_and_small_one_resolve_against_this_turn_list():
    spoken = [
        {"name": "large banana", "serving_label": "large"},
        {"name": "small banana", "serving_label": "small"},
        {"name": "medium banana", "serving_label": "medium"},
    ]
    second = resolve_confirmation_reply("the second one", spoken)
    assert second is not None
    assert second["index"] == 2
    assert second["candidate"]["name"] == "small banana"

    small = resolve_confirmation_reply("the small one", spoken)
    assert small is not None
    assert small["index"] == 2
    assert small["candidate"]["name"] == "small banana"

    stale = [
        {"name": "oatmeal"},
        {"name": "granola"},
    ]
    against_stale = resolve_confirmation_reply("the second one", stale)
    assert against_stale["candidate"]["name"] == "granola"
    assert against_stale["candidate"]["name"] != "small banana"


def test_self_repair_chicken_no_turkey_is_not_ask():
    rewritten, repaired = apply_self_repair("chicken — no, turkey")
    assert repaired is True
    assert "turkey" in rewritten.lower()
    assert "chicken" not in rewritten.lower()
    decision = evaluate_confirmation(
        _parsed({"food": "high"}, food="turkey"),
        "chicken — no, turkey",
        self_repaired=True,
    )
    assert decision.action != "ASK"
    assert decision.self_repaired is True
    assert decision.field_actions.get("food") == "SILENT"


def test_no_mayo_never_silently_logs_mayo():
    parsed = _parsed({"food": "high", "negation": "high"}, food="mayo")
    decision = evaluate_confirmation(parsed, "no mayo")
    assert parsed["confidence_detail"]["negation"]["band"] == "low"
    assert decision.action == "ASK"
    assert "negation" in decision.asked_fields
    assert "mayo" in (decision.question or "").lower()


def test_generated_questions_are_answerable():
    decision = evaluate_confirmation(
        _parsed(
            {"food": "low"},
            candidates=[
                {"name": "grilled chicken", "calories": 200},
                {"name": "fried chicken", "calories": 320},
            ],
            food="chicken",
        ),
        "chicken",
        self_repaired=True,
    )
    assert decision.question
    assert is_answerable_question(decision.question)
    assert "calorie" not in decision.question.lower()
    assert is_answerable_question("Was that bottle, can, or fountain?")
    assert not is_answerable_question("Was that 140 or 150 calories?")


def test_spec2_does_not_run_before_safety_in_pipeline():
    assert PIPELINE_ORDER[0] == "safety"
    source = open(pipeline_mod.__file__, encoding="utf-8").read()
    assert "confirmation" not in source
    assert "evaluate_confirmation" not in source


def test_attach_confirmation_is_additive():
    parsed = _parsed({"brand": "low"}, food="yogurt")
    decision = attach_confirmation(parsed, "yogurt")
    assert "confirmation" in parsed
    assert parsed["confirmation"]["action"] == decision.action
    assert parsed["food"] == "yogurt"
