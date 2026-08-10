"""
Verify (or rule out) the hypothesis: does a repeated word in a branded food's
constructed name (brand + description both containing the query word) inflate
its embedding similarity score for that query — versus a name that mentions
the word only once?

If true, this points to a fixable root cause in process_branded.py's name
construction (brand + description concatenation doesn't dedupe overlapping
words), rather than needing a blunt "prefer generic over branded" filter.

Usage:
    poetry run python3 verify_word_repetition_bias.py
"""

import asyncio
import re

from nutrition_service import openai_client, index, EMBEDDING_MODEL

TEST_QUERIES = ["banana", "milk", "chicken"]
TOP_K = 30


def count_word_occurrences(name: str, word: str) -> int:
    return len(re.findall(rf"\b{re.escape(word)}\b", name, re.IGNORECASE))


async def check_query(query: str):
    print(f"\n{'='*60}")
    print(f"Query: {query!r}")
    print(f"{'='*60}")

    response = await openai_client.embeddings.create(model=EMBEDDING_MODEL, input=query)
    vector = response.data[0].embedding
    results = index.query(vector=vector, top_k=TOP_K, include_metadata=True)

    rows = []
    for match in results["matches"]:
        name = match["metadata"].get("name", "")
        occurrences = count_word_occurrences(name, query)
        rows.append((match["score"], occurrences, name))

    # Group by occurrence count, show average score per group
    from collections import defaultdict
    by_occurrence = defaultdict(list)
    for score, occ, name in rows:
        by_occurrence[occ].append(score)

    print(f"\nAverage score by word-occurrence count (top {TOP_K} results):")
    for occ in sorted(by_occurrence.keys()):
        scores = by_occurrence[occ]
        avg = sum(scores) / len(scores)
        print(f"  {occ}x occurrence: {len(scores)} results, avg score {avg:.4f}")

    print(f"\nTop 10 individual results:")
    for score, occ, name in rows[:10]:
        print(f"  score={score:.4f}  occurrences={occ}  name={name!r}")


async def main():
    for query in TEST_QUERIES:
        await check_query(query)


if __name__ == "__main__":
    asyncio.run(main())