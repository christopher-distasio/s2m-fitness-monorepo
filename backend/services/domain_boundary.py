"""Narrow-domain decline. Runs AFTER the safety detector, never before.

S2M logs food. Off-topic requests get a brief, consistent decline.
Safety-relevant utterances must already have been intercepted.
"""

from __future__ import annotations

import re

OFF_DOMAIN_DECLINE = "I can only help with logging food."

_OFF_DOMAIN_RE = re.compile(
    r"""
    \b(
        weather
        | forecast
        | temperature\s+outside
        | tell\s+me\s+a\s+joke
        | (tell|say)\s+a\s+joke
        | set\s+(a\s+|the\s+)?timer
        | what\s+time\s+is\s+it
        | play\s+(some\s+)?music
        | news\s+headlines?
        | who\s+won\s+the
        | sports\s+score
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_off_domain(text: str) -> bool:
    if not text or not text.strip():
        return False
    return bool(_OFF_DOMAIN_RE.search(text))


def off_domain_response(raw_input: str) -> dict:
    return {
        "error": "off_domain",
        "message": OFF_DOMAIN_DECLINE,
        "transcription": raw_input,
        "logged": False,
    }
