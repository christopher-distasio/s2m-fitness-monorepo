"""Four-layer confidence capture and band computation (Spec 1).

Decision logic reads bands only. Raw floats are stored for telemetry/tuning.

TUNABLE thresholds live in this one block — do not scatter copies.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from backend.models.food_event import Band, FieldConfidence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TUNABLE — placeholder thresholds; tune against the eval suite as a follow-up.
# Do not copy these values into call sites.
# ---------------------------------------------------------------------------
ASR_HIGH = -0.35          # Whisper avg_logprob; closer to 0 is better
ASR_MEDIUM = -0.80
SEMANTIC_HIGH = -0.20     # GPT token logprob of the field value
SEMANTIC_MEDIUM = -0.60
DATABASE_HIGH = 0.55      # Qdrant similarity of the chosen match
DATABASE_MEDIUM = 0.40
DATABASE_GAP_AMBIGUOUS = 0.03  # small top1-top2 gap → cap at medium

_BAND_RANK = {"high": 3, "medium": 2, "low": 1}


def _min_band(*bands: Band | None) -> Band | None:
    present = [b for b in bands if b is not None]
    if not present:
        return None
    return min(present, key=lambda b: _BAND_RANK[b])


def _logprob_band(value: float | None, high: float, medium: float) -> Band | None:
    """Missing layer is skipped (None), not treated as zero."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def _score_band(value: float | None, high: float, medium: float) -> Band | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def compute_band(
    asr: float | None = None,
    semantic: float | None = None,
    database: float | None = None,
    *,
    database_gap: float | None = None,
    extraction_failed: bool = False,
    fallback: Band | None = None,
) -> Band:
    """Combine present layers into a single high|medium|low band.

    Missing layers are skipped. Any exception/failure in signal extraction
    must set extraction_failed=True so the band becomes low (hard rule 1)
    rather than blocking the log. When every layer is missing, ``fallback``
    (GPT whole-parse sanity) is used.
    """
    if extraction_failed:
        return "low"
    try:
        band = _min_band(
            _logprob_band(asr, ASR_HIGH, ASR_MEDIUM),
            _logprob_band(semantic, SEMANTIC_HIGH, SEMANTIC_MEDIUM),
            _score_band(database, DATABASE_HIGH, DATABASE_MEDIUM),
        )
        if band is None:
            return fallback or "medium"
        if (
            database_gap is not None
            and database_gap < DATABASE_GAP_AMBIGUOUS
            and _BAND_RANK[band] > _BAND_RANK["medium"]
        ):
            return "medium"
        return band
    except Exception:
        logger.exception("compute_band failed; defaulting to low")
        return "low"


def field_confidence(
    *,
    asr: float | None = None,
    semantic: float | None = None,
    database: float | None = None,
    database_gap: float | None = None,
    extraction_failed: bool = False,
    fallback: Band | None = None,
) -> FieldConfidence:
    return FieldConfidence(
        band=compute_band(
            asr,
            semantic,
            database,
            database_gap=database_gap,
            extraction_failed=extraction_failed,
            fallback=fallback,
        ),
        asr=asr,
        semantic=semantic,
        database=database,
        database_gap=database_gap,
    )


def extract_semantic_logprob(response: Any, value_text: str | None = None) -> float | None:
    """Average token logprob from a chat.completions response.

    Prefers tokens whose text appears in ``value_text`` when given; otherwise
    uses the whole-message average. Returns None when logprobs are absent
    (missing layer, skipped). Raises on malformed payloads so the caller can
    mark extraction_failed.
    """
    choice = response.choices[0]
    logprobs = getattr(choice, "logprobs", None)
    if logprobs is None:
        return None
    content = getattr(logprobs, "content", None)
    if not isinstance(content, list) or not content:
        return None

    token_logprobs: list[float] = []
    needle = (value_text or "").lower()
    matched: list[float] = []
    for token_info in content:
        lp = getattr(token_info, "logprob", None)
        if lp is None and isinstance(token_info, dict):
            lp = token_info.get("logprob")
        token = getattr(token_info, "token", None)
        if token is None and isinstance(token_info, dict):
            token = token_info.get("token")
        if lp is None:
            continue
        token_logprobs.append(float(lp))
        if needle and token and str(token).lower() in needle:
            matched.append(float(lp))

    chosen = matched or token_logprobs
    if not chosen:
        return None
    return sum(chosen) / len(chosen)


def extract_asr_logprob(verbose_response: Any) -> float | None:
    """Utterance-level Whisper avg_logprob from verbose_json."""
    segments = getattr(verbose_response, "segments", None)
    if segments is None and isinstance(verbose_response, dict):
        segments = verbose_response.get("segments")
    if not isinstance(segments, list) or not segments:
        # Some SDKs expose avg_logprob at the top level.
        top = getattr(verbose_response, "avg_logprob", None)
        if top is None and isinstance(verbose_response, dict):
            top = verbose_response.get("avg_logprob")
        return float(top) if top is not None else None

    values: list[float] = []
    for segment in segments:
        lp = getattr(segment, "avg_logprob", None)
        if lp is None and isinstance(segment, dict):
            lp = segment.get("avg_logprob")
        if lp is not None:
            values.append(float(lp))
    if not values:
        return None
    return sum(values) / len(values)
