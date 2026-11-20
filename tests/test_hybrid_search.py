"""SEARCH_MODE flag: dense stays the default and untouched; hybrid fuses
dense + BM25 candidates but hands cosine scores downstream, with the BM25
score used only to break exact lexical+cosine ties."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import backend.services.nutrition_service as ns
from backend.services.query_match_rank import rerank_matches_by_query


def _pt(pid, score, desc="FOOD BARS"):
    return SimpleNamespace(id=pid, score=score, payload={"qdrant_id": str(pid), "description": desc})


def test_dense_is_default_and_never_touches_hybrid_client(monkeypatch):
    monkeypatch.setattr(ns, "SEARCH_MODE", "dense")
    dense = MagicMock()
    dense.query_points.return_value = SimpleNamespace(points=[_pt(1, 0.8)])
    monkeypatch.setattr(ns, "qdrant_client", dense)
    hybrid = MagicMock(side_effect=AssertionError("hybrid client used in dense mode"))
    monkeypatch.setattr(ns, "_hybrid_client", hybrid)

    resp = ns._query_qdrant_points([0.1], 25, None, query_text="built bar")

    assert [p.id for p in resp.points] == [1]
    assert dense.query_points.call_args.kwargs["collection_name"] == ns.COLLECTION_NAME
    assert not hasattr(resp.points[0], "bm25_score")


def test_hybrid_rescores_fused_pool_with_cosine_and_sorts(monkeypatch):
    monkeypatch.setattr(ns, "SEARCH_MODE", "hybrid")
    client = MagicMock()
    fused = SimpleNamespace(points=[_pt(7, 0.5), _pt(3, 0.33)])  # RRF scores
    cosine = SimpleNamespace(points=[_pt(3, 0.71), _pt(7, 0.64)])
    bm25 = SimpleNamespace(points=[_pt(7, 9.5)])  # 3 has no shared words
    client.query_points.side_effect = [fused, cosine, bm25]
    monkeypatch.setattr(ns, "_hybrid_client", lambda: client)

    resp = ns._query_qdrant_points([0.1], 25, None, query_text="built bar")

    assert [(p.id, p.score, p.bm25_score) for p in resp.points] == [(3, 0.71, 0.0), (7, 0.64, 9.5)]
    first = client.query_points.call_args_list[0].kwargs
    assert first["collection_name"] == ns.HYBRID_COLLECTION_NAME
    assert first["prefetch"][1].using == ns.BM25_VECTOR_NAME
    matches = ns._qdrant_results_to_matches(resp.points)
    assert matches[1]["bm25_score"] == 9.5 and matches[0]["score"] == 0.71


def test_hybrid_without_query_text_falls_back_to_dense(monkeypatch):
    monkeypatch.setattr(ns, "SEARCH_MODE", "hybrid")
    dense = MagicMock()
    dense.query_points.return_value = SimpleNamespace(points=[])
    monkeypatch.setattr(ns, "qdrant_client", dense)
    monkeypatch.setattr(ns, "_hybrid_client", MagicMock(side_effect=AssertionError))

    ns._query_qdrant_points([0.1], 25, None)

    dense.query_points.assert_called_once()


def test_bm25_breaks_only_exact_ties():
    meta = {"description": "FOOD BARS", "calories": 386}
    a = {"id": "1574842", "score": 0.64, "bm25_score": 1.0, "metadata": dict(meta)}
    b = {"id": "1282741", "score": 0.64, "bm25_score": 8.0, "metadata": dict(meta)}
    # Without BM25, "1282741" < "1574842" wins on the string id tiebreak;
    # make the higher-BM25 row the one that would otherwise lose.
    a["bm25_score"], b["bm25_score"] = 8.0, 1.0
    assert [m["id"] for m in rerank_matches_by_query("food bars", [b, a])] == ["1574842", "1282741"]

    higher_cosine = dict(b, score=0.65)
    assert rerank_matches_by_query("food bars", [a, higher_cosine])[0]["id"] == "1282741"

    dense_only = [{k: v for k, v in m.items() if k != "bm25_score"} for m in (a, b)]
    assert [m["id"] for m in rerank_matches_by_query("food bars", dense_only)] == ["1282741", "1574842"]


def _real(pid, desc="FROOT LOOPS CEREAL"):
    return SimpleNamespace(id=pid, score=0.5, payload={
        "qdrant_id": str(pid), "description": desc, "fdc_id": str(pid),
        "calories": 375.0, "protein": 7.0, "carbs": 85.0, "fat": 3.0,
        "serving_size_g": 29.0, "serving_size_unit": "g",
    })


def test_hybrid_drops_phantoms_before_cutting_pool(monkeypatch):
    monkeypatch.setattr(ns, "SEARCH_MODE", "hybrid")
    assert not ns.is_phantom_record(ns.normalize_nutrients_to_per_100g(_real(1).payload))
    client = MagicMock()
    fused = SimpleNamespace(points=[_pt(9, 0.9), _real(1), _pt(8, 0.4), _real(2)])
    client.query_points.side_effect = [
        fused,
        SimpleNamespace(points=[_pt(1, 0.7), _pt(2, 0.6)]),
        SimpleNamespace(points=[]),
    ]
    monkeypatch.setattr(ns, "_hybrid_client", lambda: client)

    resp = ns._query_qdrant_points([0.1], 2, None, query_text="froot loops")

    assert [p.id for p in resp.points] == [1, 2]
    first = client.query_points.call_args_list[0].kwargs
    assert first["limit"] == 2 * ns.HYBRID_PHANTOM_HEADROOM
    assert all(pf.limit == 2 * ns.HYBRID_PHANTOM_HEADROOM for pf in first["prefetch"])


def test_hybrid_keeps_all_phantom_pool_so_escalation_still_fires(monkeypatch):
    monkeypatch.setattr(ns, "SEARCH_MODE", "hybrid")
    client = MagicMock()
    client.query_points.side_effect = [
        SimpleNamespace(points=[_pt(9, 0.9), _pt(8, 0.4), _pt(7, 0.3)]),
        SimpleNamespace(points=[_pt(9, 0.7), _pt(8, 0.6)]),
        SimpleNamespace(points=[]),
    ]
    monkeypatch.setattr(ns, "_hybrid_client", lambda: client)

    resp = ns._query_qdrant_points([0.1], 2, None, query_text="froot loops")

    assert [p.id for p in resp.points] == [9, 8]
