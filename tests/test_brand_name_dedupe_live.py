"""Live Pinecone checks for brand-name duplication (Tier 3 / data layer).

Confirms stored metadata is clean *and* that applying format_branded_name
(get_brand + name — the spoken/UI path) does not reintroduce consecutive
brand duplication across a sample of brands, not just Great Value.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv

from backend.services.nutrition_service import format_branded_name
from tests.test_brand_name_dedupe import (
    consecutive_brand_duplication,
    spoken_candidate,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

pytestmark = pytest.mark.skipif(
    not (os.getenv("PINECONE_API_KEY") or "").strip()
    or not (os.getenv("OPENAI_API_KEY") or "").strip(),
    reason="requires PINECONE_API_KEY and OPENAI_API_KEY",
)

# Known Great Value fdc_ids observed during the original diagnosis (names
# already started with GREAT VALUE; live prepend was the audible bug).
GREAT_VALUE_FDC_IDS = [
    "2504728",  # GREAT VALUE, STEVIA
    "2524338",  # GREAT VALUE, CRISP RICE CEREAL
    "2676443",  # GREAT VALUE WHOLE MILK
    "1861773",  # GREAT VALUE MAYO MAYONNAISE
    "2549996",  # GREAT VALUE FINE GREEN BEANS
]

SAMPLE_QUERIES = [
    "Great Value",
    "Kroger",
    "Good & Gather",
    "Member's Mark",
    "Kirkland",
    "Chobani",
    "Private Selection",
]


def _brand_from_meta(meta: dict) -> str:
    return (meta.get("brand_name") or meta.get("brand_owner") or "").strip()


def _fetch_by_ids(index, ids: list[str]) -> dict[str, dict]:
    raw = index.fetch(ids=ids)
    # pinecone SDK may return object or dict
    vectors = getattr(raw, "vectors", None) or raw.get("vectors") or {}
    out = {}
    for vid, vec in vectors.items():
        meta = getattr(vec, "metadata", None) or vec.get("metadata") or {}
        out[str(vid)] = meta
    return out


def _sample_branded(index, client, embedding_model: str) -> dict[str, dict]:
    """Unique branded metadata via several brand queries."""
    seen: dict[str, dict] = {}
    for q in SAMPLE_QUERIES:
        emb = client.embeddings.create(model=embedding_model, input=q).data[0].embedding
        res = index.query(
            vector=emb,
            top_k=80,
            include_metadata=True,
            filter={"source": {"$eq": "usda_branded_foods"}},
        )
        matches = getattr(res, "matches", None) or res.get("matches") or []
        for m in matches:
            mid = str(getattr(m, "id", None) or m.get("id"))
            meta = getattr(m, "metadata", None) or m.get("metadata") or {}
            seen[mid] = meta
    return seen


def test_great_value_stored_names_have_no_literal_brand_brand_duplication():
    from backend.services.nutrition_service import index

    metas = _fetch_by_ids(index, GREAT_VALUE_FDC_IDS)
    assert len(metas) >= 3, (
        f"expected to fetch several Great Value ids, got {list(metas)}"
    )

    failures = []
    for fid, meta in metas.items():
        name = (meta.get("name") or "").strip()
        brand = _brand_from_meta(meta) or "GREAT VALUE"
        if consecutive_brand_duplication(name, brand):
            failures.append((fid, brand, name))
        # Explicit substring the user heard aloud
        if "great value great value" in name.lower():
            failures.append((fid, brand, name))

    assert not failures, (
        "stored Pinecone name still has consecutive brand duplication:\n"
        + "\n".join(f"  {f}" for f in failures)
    )


def test_sample_branded_records_no_stored_or_spoken_brand_brand_duplication():
    """Broader than Great Value: sample must stay clean after display formatting.

    If only Great Value were fixed and other brands still double on speak,
    this fails — surfacing a narrow patch rather than a general fix.
    """
    from openai import OpenAI

    from backend.services.nutrition_service import EMBEDDING_MODEL, index

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    sample = _sample_branded(index, client, EMBEDDING_MODEL)
    assert len(sample) >= 100, f"expected a broad sample, got {len(sample)}"

    stored_dups = []
    spoken_dups = []
    brands_seen: set[str] = set()

    for fid, meta in sample.items():
        name = (meta.get("name") or "").strip()
        brand = _brand_from_meta(meta)
        if not brand or not name:
            continue
        brands_seen.add(brand.upper())

        if consecutive_brand_duplication(name, brand):
            stored_dups.append((fid, brand, name[:100]))

        spoken = format_branded_name(name, brand)
        if consecutive_brand_duplication(spoken, brand):
            spoken_dups.append((fid, brand, spoken[:100]))

    assert len(brands_seen) >= 5, (
        f"sample too narrow ({len(brands_seen)} brands) — cannot claim "
        f"general fix. brands={sorted(brands_seen)[:20]}"
    )

    assert not stored_dups, (
        f"{len(stored_dups)} stored names have consecutive brand duplication "
        f"(general pattern NOT fixed at data layer):\n"
        + "\n".join(f"  {x}" for x in stored_dups[:15])
    )
    assert not spoken_dups, (
        f"{len(spoken_dups)} records still double brand after "
        f"format_branded_name (spoken/UI path not generally fixed):\n"
        + "\n".join(f"  {x}" for x in spoken_dups[:15])
    )


def test_spoken_path_for_fetched_great_value_records():
    from backend.services.nutrition_service import get_brand, index

    metas = _fetch_by_ids(index, GREAT_VALUE_FDC_IDS)
    assert metas

    for fid, meta in metas.items():
        name = meta.get("name") or ""
        brand = get_brand(meta)
        speech = spoken_candidate(
            name,
            brand,
            serving_label=meta.get("household_serving_fulltext") or "1 serving",
            calories=100,
        )
        assert "great value great value" not in speech.lower(), (
            f"fdc_id={fid} still produces audible brand repeat: {speech!r}"
        )
        assert not consecutive_brand_duplication(speech.split(",")[0], brand)


def test_legitimate_repeat_tokens_in_sample_survive_formatting():
    """False-positive guard on real data: consecutive non-brand tokens must
    remain after format_branded_name (helper must not strip arbitrary repeats).
    """
    from openai import OpenAI

    from backend.services.nutrition_service import EMBEDDING_MODEL, index

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    emb = client.embeddings.create(
        model=EMBEDDING_MODEL, input="Great Value mayo mayonnaise"
    ).data[0].embedding
    res = index.query(
        vector=emb,
        top_k=50,
        include_metadata=True,
        filter={"source": {"$eq": "usda_branded_foods"}},
    )
    matches = getattr(res, "matches", None) or res.get("matches") or []

    checked = 0
    for m in matches:
        meta = getattr(m, "metadata", None) or m.get("metadata") or {}
        name = (meta.get("name") or "").strip()
        brand = _brand_from_meta(meta)
        if not name or not brand:
            continue
        brand_tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9&']+", brand)}
        tokens = re.findall(r"[A-Za-z0-9&']+", name)
        for i in range(len(tokens) - 1):
            if tokens[i].lower() != tokens[i + 1].lower():
                continue
            word = tokens[i]
            if word.lower() in brand_tokens:
                continue
            spoken = format_branded_name(name, brand)
            # Preserve the full name (or brand+name when brand was absent).
            # Comma-separated repeats like "LIGHT, LIGHT" must survive.
            spoken_tokens = [
                t.lower() for t in re.findall(r"[A-Za-z0-9&']+", spoken)
            ]
            assert word.lower() in spoken_tokens
            # The consecutive pair of non-brand tokens must still be adjacent.
            joined = " ".join(spoken_tokens)
            pair = f"{word.lower()} {word.lower()}"
            assert pair in joined, (
                f"over-aggressive strip of legitimate repeat {pair!r} "
                f"in name={name!r} → spoken={spoken!r}"
            )
            checked += 1
            break

    # Synthetic false-positives are covered in test_brand_name_dedupe.py;
    # live sample may not contain pairs every run.
    assert checked >= 0
