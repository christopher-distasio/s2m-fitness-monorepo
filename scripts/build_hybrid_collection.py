"""
Build `food-vectors-hybrid`: a copy of `food-vectors` with a BM25 sparse
vector added, so search can match exact words (brands, "0%", "waffles")
as well as meaning.

Qdrant cannot add a new vector name to an existing collection (tested on
1.18.3: "Not existing vector name error"), so this copies every point into
a new collection. Nothing is re-embedded: dense vectors are copied as-is,
and Qdrant builds the BM25 vector server-side from the text we send
(model "qdrant/bm25"). The source collection is only read, never written.

The dense vector stays UNNAMED, as in the source, so existing dense-only
queries (no `using=`) work unchanged against the new collection.

BM25 text = description + brand_name + subbrand_name + category, where a
brand already present in the description is not repeated (repeating it
would double its weight). brand_owner is left out: company names like
"Global Garlic Inc." are not what people say.

Usage (run from the repo root, always via poetry):
    poetry run python scripts/build_hybrid_collection.py create
    poetry run python scripts/build_hybrid_collection.py copy --limit 50000
    poetry run python scripts/build_hybrid_collection.py copy          # resumes
    poetry run python scripts/build_hybrid_collection.py finalize
    poetry run python scripts/build_hybrid_collection.py verify

Source/target hosts come from --source / --target (default: this machine
-> the Mac Mini). Progress is saved to logs/hybrid_build_state.json after
every batch, so `copy` can be stopped and rerun safely.
"""
import argparse
import json
import os
import random
import sys
import time

from qdrant_client import QdrantClient, models

SOURCE_COLLECTION = "food-vectors"
TARGET_COLLECTION = "food-vectors-hybrid"
SPARSE_NAME = "bm25"
BM25_MODEL = "qdrant/bm25"
BATCH = 256
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "hybrid_build_state.json")
LOAD_INDEXING_THRESHOLD = 0  # 0 = don't build the HNSW graph while loading


def bm25_text(payload: dict) -> str:
    """Text the BM25 vector is built from. See module docstring."""
    desc = (payload.get("description") or "").strip()
    parts = [desc]
    seen = desc.lower()
    for field in ("brand_name", "subbrand_name"):
        v = (payload.get(field) or "").strip()
        if v and v.lower() not in seen:
            parts.append(v)
            seen += " " + v.lower()
    cat = (payload.get("branded_food_category") or payload.get("wweia_food_category") or "").strip()
    if cat:
        parts.append(cat)
    return " ".join(p for p in parts if p)


def clients(args):
    src = QdrantClient(host=args.source, grpc_port=6334, prefer_grpc=True, timeout=300)
    dst = QdrantClient(host=args.target, grpc_port=6334, prefer_grpc=True, timeout=1800,
                       cloud_inference=True)  # send Documents to the server for BM25
    return src, dst


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"offset": None, "copied": 0, "done": False}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)


def cmd_create(args):
    src, dst = clients(args)
    if dst.collection_exists(TARGET_COLLECTION):
        sys.exit(f"{TARGET_COLLECTION} already exists on {args.target}; not touching it.")
    s = src.get_collection(SOURCE_COLLECTION).config
    dst.create_collection(
        collection_name=TARGET_COLLECTION,
        vectors_config=models.VectorParams(size=s.params.vectors.size, distance=s.params.vectors.distance),
        sparse_vectors_config={SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        hnsw_config=models.HnswConfigDiff(m=s.hnsw_config.m, ef_construct=s.hnsw_config.ef_construct),
        on_disk_payload=True,
        optimizers_config=models.OptimizersConfigDiff(indexing_threshold=LOAD_INDEXING_THRESHOLD),
    )
    print(f"created {TARGET_COLLECTION} on {args.target} (HNSW building off while loading)")


def cmd_copy(args):
    src, dst = clients(args)
    state = load_state()
    if state["done"]:
        print("copy already finished; delete logs/hybrid_build_state.json to restart"); return
    target_total = args.limit
    t0, start_copied = time.time(), state["copied"]
    while True:
        if target_total is not None and state["copied"] >= target_total:
            break
        points, next_offset = src.scroll(
            SOURCE_COLLECTION, limit=BATCH, offset=state["offset"],
            with_payload=True, with_vectors=True,
        )
        if points:
            dst.upsert(TARGET_COLLECTION, wait=True, points=[
                models.PointStruct(
                    id=p.id,
                    vector={"": p.vector,
                            SPARSE_NAME: models.Document(text=bm25_text(p.payload or {}), model=BM25_MODEL)},
                    payload=p.payload,
                ) for p in points
            ])
        state["copied"] += len(points)
        state["offset"] = next_offset
        state["done"] = next_offset is None
        save_state(state)
        rate = (state["copied"] - start_copied) / max(time.time() - t0, 1e-9)
        print(f"{state['copied']:,} copied  {rate:,.0f}/s", flush=True)
        if state["done"]:
            print("copy finished"); break


def cmd_finalize(args):
    src, dst = clients(args)
    schema = src.get_collection(SOURCE_COLLECTION).payload_schema
    # Rerunnable: a dropped connection mid-run (seen 2026-11-19 on the 2M-point
    # copy) leaves some indexes built; skip those instead of rebuilding them.
    existing = set(dst.get_collection(TARGET_COLLECTION).payload_schema)
    for field, info in schema.items():
        if field in existing:
            continue
        dtype = info.data_type
        ftype = {"keyword": models.PayloadSchemaType.KEYWORD, "bool": models.PayloadSchemaType.BOOL,
                 "float": models.PayloadSchemaType.FLOAT, "integer": models.PayloadSchemaType.INTEGER,
                 "text": models.PayloadSchemaType.TEXT}[str(dtype.value if hasattr(dtype, "value") else dtype)]
        dst.create_payload_index(TARGET_COLLECTION, field, field_schema=ftype, wait=True)
        print(f"  index: {field}", flush=True)
    print(f"payload indexes: {len(schema) - len(existing)} created, {len(existing)} already there")
    thr = src.get_collection(SOURCE_COLLECTION).config.optimizer_config.indexing_threshold or 10000
    dst.update_collection(TARGET_COLLECTION, optimizers_config=models.OptimizersConfigDiff(indexing_threshold=thr))
    print(f"HNSW building on (indexing_threshold={thr}); Qdrant now builds the search index. "
          "Run `verify` until status is green.")


def cmd_verify(args):
    src, dst = clients(args)
    a = src.count(SOURCE_COLLECTION, exact=True).count
    info = dst.get_collection(TARGET_COLLECTION)
    b = dst.count(TARGET_COLLECTION, exact=True).count
    print(f"status={info.status}  indexed={info.indexed_vectors_count:,}  source={a:,}  target={b:,}  "
          f"{'MATCH' if a == b else 'MISMATCH'}")
    sample, _ = src.scroll(SOURCE_COLLECTION, limit=2000, offset=None, with_payload=True, with_vectors=True)
    sample = random.Random(0).sample(sample, min(50, len(sample)))
    got = {p.id: p for p in dst.retrieve(TARGET_COLLECTION, [p.id for p in sample],
                                          with_payload=True, with_vectors=True)}
    bad = 0
    for p in sample:
        q = got.get(p.id)
        dense = q.vector.get("") if q and isinstance(q.vector, dict) else None
        if q is None or dense != p.vector or q.payload != p.payload or SPARSE_NAME not in q.vector:
            bad += 1
    print(f"spot check: {len(sample) - bad}/{len(sample)} points identical with a bm25 vector")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create", "copy", "finalize", "verify"])
    ap.add_argument("--source", default="localhost")
    ap.add_argument("--target", default="192.168.1.236")
    ap.add_argument("--limit", type=int, default=None, help="stop once this many points are copied")
    args = ap.parse_args()
    {"create": cmd_create, "copy": cmd_copy, "finalize": cmd_finalize, "verify": cmd_verify}[args.cmd](args)
