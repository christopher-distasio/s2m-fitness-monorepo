"""
Second hypothesis check: does a shorter/simpler name string score higher
than a longer one, regardless of word repetition? (Repetition hypothesis
was tested and disproven in verify_word_repetition_bias.py.)

Usage:
    poetry run python3 verify_length_bias.py
"""

import asyncio

from nutrition_service import openai_client, index, EMBEDDING_MODEL

TEST_QUERIES = ["banana", "milk", "chicken"]
TOP_K = 30


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
        rows.append((match["score"], len(name), name))

    # Correlation check: sort by length, see if score trends downward
    rows_by_length = sorted(rows, key=lambda r: r[1])
    short_half = rows_by_length[:len(rows_by_length)//2]
    long_half = rows_by_length[len(rows_by_length)//2:]

    avg_score_short = sum(r[0] for r in short_half) / len(short_half)
    avg_score_long = sum(r[0] for r in long_half) / len(long_half)
    avg_len_short = sum(r[1] for r in short_half) / len(short_half)
    avg_len_long = sum(r[1] for r in long_half) / len(long_half)

    print(f"Shorter-name half: avg length {avg_len_short:.0f} chars, avg score {avg_score_short:.4f}")
    print(f"Longer-name half:  avg length {avg_len_long:.0f} chars, avg score {avg_score_long:.4f}")

    print(f"\nAll results sorted by length (shortest first):")
    for score, length, name in rows_by_length:
        print(f"  len={length:3d}  score={score:.4f}  name={name!r}")


async def main():
    for query in TEST_QUERIES:
        await check_query(query)


if __name__ == "__main__":
    asyncio.run(main())