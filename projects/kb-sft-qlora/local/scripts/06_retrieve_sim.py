from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.corpus import load_corpus  # noqa: E402
from kb_sft_data.io_utils import write_jsonl  # noqa: E402
from kb_sft_data.retriever import HybridRetriever  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--split", default="train")
    parser.add_argument("--audit", type=int, default=0)
    args = parser.parse_args()

    cfg = DataConfig.load()
    corpus = load_corpus(cfg.path("corpus_dir") / "corpus.jsonl")
    embeddings = cfg.path("corpus_dir") / "embeddings.npz"
    retriever = HybridRetriever(corpus, cfg.retrieval, embeddings)
    rng = random.Random(cfg.seed)

    if args.query:
        contexts = retriever.retrieve(
            args.query, args.query, [], args.split, "", rng, entity_filter=False, distractor_rate=0
        )
        for chunk in contexts:
            print(f"[{chunk['idx']}] score={chunk['score']:.4f} {chunk['file_title']} | {chunk.get('display_title')}")
            print(chunk["content"][:160].replace("\n", " "), "\n")
        return

    if not args.audit:
        raise SystemExit("use --query or --audit N")
    pool = [c for c in corpus if c.get("split") == args.split]
    seen_docs: set[str] = set()
    samples = []
    for chunk in pool:
        if chunk["doc_id"] in seen_docs:
            continue
        seen_docs.add(chunk["doc_id"])
        query = (chunk.get("display_title") or chunk["file_title"]) + " " + chunk["content"][:80]
        contexts = retriever.retrieve(
            query, query, [chunk["chunk_id"]], chunk["split"], chunk.get("product_model", ""),
            rng, entity_filter=False, distractor_rate=0,
        )
        hit = any(c["chunk_id"] == chunk["chunk_id"] for c in contexts)
        samples.append({"query": query, "expected": chunk["chunk_id"], "hit": hit,
                        "contexts": [c["chunk_id"] for c in contexts]})
        if len(samples) >= args.audit:
            break
    hit_rate = sum(s["hit"] for s in samples) / max(len(samples), 1)
    out = cfg.path("corpus_dir") / "retrieval_audit.jsonl"
    write_jsonl(out, samples)
    print(f"audit={len(samples)} hit_rate={hit_rate:.3f} -> {out}")
    if hit_rate < 0.95:
        print("[warn] evidence hit rate < 95%; increase top_k or check chunking.")


if __name__ == "__main__":
    main()
