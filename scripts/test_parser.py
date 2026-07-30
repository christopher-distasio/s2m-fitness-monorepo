"""
Quick isolated test: what does food_parser.py extract for "turkey sandwich"
before it ever hits Pinecone?

Run from repo root: poetry run python scripts/test_parser.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.food_parser import parse_food_input  # adjust import if function name differs

import asyncio

test_cases = [
    ("chicken thigh", "generic"),
    ("boneless skinless chicken thigh", "generic"),
]


async def main():
    for phrase, source_filter in test_cases:
        result = await parse_food_input(phrase, source_filter=source_filter)
        print(f"Input: {phrase!r} | source_filter: {source_filter}")
        print(f"Parsed: {result}")
        print("---")


asyncio.run(main())