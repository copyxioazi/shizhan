from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .config import RetrievalConfig

TOKEN_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    text = TOKEN_RE.sub("", text.lower())
    chars = list(text)
    bigrams = [text[i : i + 2] for i in range(max(0, len(text) - 1))]
    return chars + bigrams


class BM25Retriever:
    def __init__(self, chunks: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.docs = [tokenize(c.get("content", "")) for c in chunks]
        self.doc_len = [len(d) for d in self.docs]
        self.avgdl = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.tf: list[Counter[str]] = [Counter(d) for d in self.docs]
        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(set(doc))
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}
        self.chunk_pos = {c["chunk_id"]: i for i, c in enumerate(chunks)}
        self.doc_index: dict[str, list[int]] = defaultdict(list)
        for i, chunk in enumerate(chunks):
            self.doc_index[chunk.get("doc_id", "")].append(i)

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out: list[float] = []
        for tf, dl in zip(self.tf, self.doc_len):
            score = 0.0
            for term in q:
                freq = tf.get(term, 0)
                if freq:
                    denom = freq + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1e-9))
                    score += self.idf.get(term, 0.0) * freq * (self.k1 + 1) / denom
            out.append(score)
        return out

    def search(
        self,
        query: str,
        top_k: int = 10,
        allowed_doc_ids: set[str] | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        scores = self.scores(query)
        items = []
        for i, score in enumerate(scores):
            chunk = self.chunks[i]
            if allowed_doc_ids is not None and chunk.get("doc_id") not in allowed_doc_ids:
                continue
            if score > 0:
                items.append((chunk, score))
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:top_k]


class HybridRetriever:
    """BGE dense (optional) + BM25 lexical + two-pass RRF + dynamic cut."""

    def __init__(self, chunks: list[dict[str, Any]], cfg: RetrievalConfig, embeddings_path: str | Path | None = None):
        self.chunks = chunks
        self.cfg = cfg
        self.bm25 = BM25Retriever(chunks)
        self.chunk_ids = [c["chunk_id"] for c in chunks]
        self.dense = None
        self.encoder = None
        if embeddings_path and Path(embeddings_path).exists():
            self._load_embeddings(Path(embeddings_path))

    def _load_embeddings(self, path: Path) -> None:
        try:
            import numpy as np
        except ImportError:
            return
        data = np.load(path, allow_pickle=True)
        if "dense" not in data or "chunk_ids" not in data:
            return
        self.dense = data["dense"].astype("float32")
        self.chunk_ids = [str(x) for x in data["chunk_ids"].tolist()]
        self.dense_index = {cid: i for i, cid in enumerate(self.chunk_ids)}
        # L2-normalize once.
        norms = np.linalg.norm(self.dense, axis=1, keepdims=True)
        self.dense = self.dense / np.maximum(norms, 1e-9)
        try:
            from FlagEmbedding import BGEM3FlagModel

            model_path = Path(
                __import__("os").getenv(
                    "BGE_MODEL_PATH",
                    "D:/AAAA/models/models/BAAI--bge-m3/snapshots/master",
                )
            )
            if model_path.exists():
                self.encoder = BGEM3FlagModel(str(model_path), use_fp16=False, device="cpu")
        except Exception:
            self.encoder = None

    def _dense_scores(self, query: str) -> dict[str, float]:
        if self.dense is None or self.encoder is None:
            return {}
        import numpy as np

        result = self.encoder.encode([query], return_dense=True, return_sparse=False, return_colbert_vecs=False)
        vec = np.asarray(result["dense_vecs"][0], dtype="float32")
        vec = vec / max(float(np.linalg.norm(vec)), 1e-9)
        scores = self.dense @ vec
        return {cid: float(scores[i]) for cid, i in self.dense_index.items()}

    @staticmethod
    def _minmax(scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        lo, hi = min(scores.values()), max(scores.values())
        if hi - lo < 1e-12:
            return {k: 0.0 for k in scores}
        return {k: (v - lo) / (hi - lo) for k, v in scores.items()}

    def _one_pass(
        self,
        query: str,
        top_k: int,
        allowed_doc_ids: set[str] | None,
    ) -> list[tuple[dict[str, Any], float]]:
        lexical = {c["chunk_id"]: s for c, s in self.bm25.search(query, top_k=10_000, allowed_doc_ids=allowed_doc_ids)}
        dense = self._dense_scores(query)
        if dense and allowed_doc_ids is not None:
            dense = {cid: s for cid, s in dense.items() if self._chunk(cid).get("doc_id") in allowed_doc_ids}
        weight_dense = self.cfg.dense_weight if dense else 0.0
        weight_lex = self.cfg.sparse_weight if dense else 1.0
        lex_norm = self._minmax(lexical)
        dense_norm = self._minmax(dense)
        combined: dict[str, float] = {}
        for cid in set(lex_norm) | set(dense_norm):
            combined[cid] = weight_dense * dense_norm.get(cid, 0.0) + weight_lex * lex_norm.get(cid, 0.0)
        items = [(self._chunk(cid), score) for cid, score in combined.items() if score > 0]
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:top_k]

    def _chunk(self, chunk_id: str) -> dict[str, Any]:
        if not hasattr(self, "_chunk_map"):
            self._chunk_map = {c["chunk_id"]: c for c in self.chunks}
        return self._chunk_map[chunk_id]

    def retrieve(
        self,
        question: str,
        hyde: str | None,
        evidence_chunk_ids: list[str],
        split: str,
        product_model: str = "",
        rng: random.Random | None = None,
        *,
        entity_filter: bool = True,
        distractor_rate: float = 0.30,
    ) -> list[dict[str, Any]]:
        rng = rng or random.Random(0)
        pool = self._split_pool(split)
        allowed_docs = {c["doc_id"] for c in pool}
        if entity_filter and product_model and rng.random() < self.cfg.entity_filter_rate:
            same = {c["doc_id"] for c in pool if c.get("product_model") == product_model}
            if same:
                allowed_docs = same

        pass1 = self._one_pass(question, self.cfg.top_k, allowed_docs)
        pass2 = self._one_pass(hyde or question, self.cfg.top_k, allowed_docs)
        fused = self._rrf([pass1, pass2])
        selected = self._dynamic_cut(fused)
        by_id = {c["chunk_id"]: (c, s) for c, s in fused}

        chosen: list[dict[str, Any]] = []
        for chunk, score in selected:
            chosen.append({**chunk, "score": round(float(score), 6), "injected": False})

        # Evidence must be in the context; inject missing evidence at rank 3-8.
        present = {c["chunk_id"] for c in chosen}
        for cid in evidence_chunk_ids:
            if cid in present:
                continue
            chunk = self._chunk(cid)
            pos = min(len(chosen), rng.randint(2, 7))
            chosen.insert(pos, {**chunk, "score": 0.0, "injected": True})
            present.add(cid)

        # Hard distractor: replace a non-evidence tail chunk with another product's chunk.
        if distractor_rate > 0 and rng.random() < distractor_rate:
            evidence = set(evidence_chunk_ids)
            others = [
                c for c in pool
                if c["chunk_id"] not in present
                and c.get("product_model") and c.get("product_model") != product_model
            ]
            if others:
                victim = next((i for i in range(len(chosen) - 1, -1, -1) if chosen[i]["chunk_id"] not in evidence), None)
                if victim is not None:
                    replacement = rng.choice(others)
                    chosen[victim] = {**replacement, "score": 0.0, "injected": False}

        if self.cfg.shuffle_contexts:
            rng.shuffle(chosen)
        # Keep at least min_context, at most max_context.
        chosen = chosen[: self.cfg.max_context]
        while len(chosen) < self.cfg.min_context:
            extra = rng.choice(pool)
            if extra["chunk_id"] not in {c["chunk_id"] for c in chosen}:
                chosen.append({**extra, "score": 0.0, "injected": False})
            else:
                break
        for idx, chunk in enumerate(chosen, 1):
            chunk["idx"] = idx
        return chosen

    def _split_pool(self, split: str) -> list[dict[str, Any]]:
        # Keep train/dev/test document pools disjoint.
        return [c for c in self.chunks if c.get("split") == split]

    @staticmethod
    def _rrf(passes: Iterable[list[tuple[dict[str, Any], float]]], k: int = 60) -> list[tuple[dict[str, Any], float]]:
        scores: dict[str, float] = defaultdict(float)
        by_id: dict[str, dict[str, Any]] = {}
        for ranked in passes:
            for rank, (chunk, _) in enumerate(ranked, 1):
                cid = chunk["chunk_id"]
                scores[cid] += 1.0 / (k + rank)
                by_id[cid] = chunk
        return sorted(((by_id[cid], score) for cid, score in scores.items()), key=lambda x: x[1], reverse=True)

    def _dynamic_cut(self, items: list[tuple[dict[str, Any], float]]) -> list[tuple[dict[str, Any], float]]:
        if not items:
            return []
        max_score = max(s for _, s in items) or 1.0
        normalized = [(c, s / max_score) for c, s in items]
        selected: list[tuple[dict[str, Any], float]] = []
        for i, (chunk, score) in enumerate(normalized):
            if i >= self.cfg.max_context:
                break
            if i >= self.cfg.min_context:
                prev = normalized[i - 1][1]
                abs_gap = prev - score
                rel_gap = abs_gap / max(prev, 1e-9)
                if abs_gap > self.cfg.abs_gap or rel_gap > self.cfg.rel_gap:
                    break
            selected.append((chunk, score))
        return selected
