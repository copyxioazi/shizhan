from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.corpus import load_corpus  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("BGE_MODEL_PATH", "D:/AAAA/models/models/BAAI--bge-m3/snapshots/master"))
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = DataConfig.load()
    corpus_path = cfg.path("corpus_dir") / "corpus.jsonl"
    out = cfg.path("corpus_dir") / "embeddings.npz"
    if out.exists() and not args.force:
        print(f"exists: {out} (pass --force to rebuild)")
        return
    chunks = load_corpus(corpus_path)
    if not chunks:
        raise SystemExit("empty corpus")

    try:
        import numpy as np
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as exc:
        print(f"[skip] FlagEmbedding/numpy unavailable ({exc}); BM25 fallback will be used.")
        return
    if not Path(args.model).exists():
        print(f"[skip] BGE-M3 model not found: {args.model}; BM25 fallback will be used.")
        return

    model = BGEM3FlagModel(args.model, use_fp16=False, device="cpu")
    vectors = []
    for start in range(0, len(chunks), args.batch_size):
        batch = chunks[start : start + args.batch_size]
        result = model.encode(
            [c["content"] for c in batch],
            batch_size=args.batch_size,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        vectors.extend(result["dense_vecs"])
        print(f"embedded {min(start + args.batch_size, len(chunks))}/{len(chunks)}")
    np.savez_compressed(
        out,
        dense=np.asarray(vectors, dtype="float32"),
        chunk_ids=np.asarray([c["chunk_id"] for c in chunks]),
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
