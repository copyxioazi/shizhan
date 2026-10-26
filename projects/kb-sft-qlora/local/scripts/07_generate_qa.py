from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.corpus import load_corpus  # noqa: E402
from kb_sft_data.io_utils import append_jsonl, ensure_dir, now_iso, write_json  # noqa: E402
from kb_sft_data.llm_client import AsyncLLMClient, LLMError  # noqa: E402
from kb_sft_data.pipeline import (  # noqa: E402
    generation_prompt,
    make_sample,
    offline_candidates,
)
from kb_sft_data.retriever import HybridRetriever  # noqa: E402
from kb_sft_data.sampler import build_all_bundles  # noqa: E402
from kb_sft_data.schema import validate_candidate  # noqa: E402


def normalize_candidate(candidate: dict, bundle: dict) -> dict:
    candidate = dict(candidate)
    candidate.setdefault("task_type", bundle["task_type"])
    candidate.setdefault("subtype", bundle.get("subtype", ""))
    candidate.setdefault("answer_text", candidate.get("answer", ""))
    candidate.setdefault("hyde_text", "")
    candidate.setdefault("claims", [])
    candidate.setdefault("missing_info", [])
    candidate.setdefault("conflict_values", [])
    candidate.setdefault("format_template", "plain")
    candidate.setdefault("difficulty", "medium")
    candidate["expected_behavior"] = bundle["expected_behavior"]
    return candidate


async def main_async(args: argparse.Namespace) -> None:
    cfg = DataConfig.load(args.config)
    corpus = load_corpus(cfg.path("corpus_dir") / "corpus.jsonl")
    chunks_by_id = {c["chunk_id"]: c for c in corpus}
    embeddings = cfg.path("corpus_dir") / "embeddings.npz"
    retriever = HybridRetriever(corpus, cfg.retrieval, embeddings)

    bundles = build_all_bundles(corpus, cfg, seed=cfg.seed)
    if args.task:
        tasks = set(args.task)
        bundles = [b for b in bundles if b["task_type"] in tasks]
    if args.split:
        bundles = [b for b in bundles if b["split"] == args.split]
    if args.limit:
        bundles = bundles[: args.limit]

    out = cfg.path("candidates_dir") / "candidates.jsonl"
    ensure_dir(out.parent)
    if args.force and out.exists():
        out.unlink()

    done: set[str] = set()
    if out.exists():
        with open(out, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line).get("metadata", {}).get("bundle_id", ""))
    bundles = [b for b in bundles if b["bundle_id"] not in done]
    print(f"bundles: {len(bundles)} (skipped {len(done)} already generated)")

    client = None
    if not args.offline:
        try:
            client = AsyncLLMClient(
                budget_usd=cfg.generation.budget_usd,
                timeout_s=cfg.generation.timeout_s,
                max_retries=cfg.generation.max_retries,
            )
        except LLMError as exc:
            raise SystemExit(f"{exc}\nUse --offline for a deterministic smoke test.") from exc

    sem = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()
    errors_path = cfg.path("rejected_dir") / "generation_errors.jsonl"
    counts = {"bundles": 0, "samples": 0, "candidate_errors": 0, "bundle_errors": 0}
    started = now_iso()

    async def process(bundle: dict) -> None:
        async with sem:
            try:
                if args.offline:
                    candidates = offline_candidates(bundle, chunks_by_id)
                    generator_model = "offline"
                else:
                    system, user = generation_prompt(
                        bundle, chunks_by_id, cfg.generation.candidates_per_bundle
                    )
                    result = await client.chat_json(
                        system, user,
                        temperature=0.7,
                        max_tokens=3500,
                        json_mode=True,
                    )
                    candidates = result.get("samples", result) if isinstance(result, dict) else result
                    if not isinstance(candidates, list):
                        raise LLMError(f"unexpected samples payload: {type(candidates)}")
                    generator_model = client.generator_model
                rng = random.Random(int(bundle["bundle_id"], 16) & 0xFFFFFFFF)
                accepted = 0
                for raw in candidates[: cfg.generation.candidates_per_bundle]:
                    if not isinstance(raw, dict):
                        continue
                    candidate = normalize_candidate(raw, bundle)
                    problems = validate_candidate(candidate)
                    if problems:
                        counts["candidate_errors"] += 1
                        async with write_lock:
                            append_jsonl(
                                errors_path,
                                {"bundle_id": bundle["bundle_id"], "stage": "candidate",
                                 "errors": problems, "candidate": candidate},
                            )
                        continue
                    sample = make_sample(
                        bundle, candidate, retriever, cfg, rng,
                        generator_model=generator_model,
                    )
                    async with write_lock:
                        append_jsonl(out, sample)
                    accepted += 1
                    counts["samples"] += 1
                counts["bundles"] += 1
                if counts["bundles"] % 50 == 0:
                    print(f"progress: bundles={counts['bundles']} samples={counts['samples']}", flush=True)
            except Exception as exc:  # keep going; one bad bundle must not kill the run
                counts["bundle_errors"] += 1
                async with write_lock:
                    append_jsonl(
                        errors_path,
                        {"bundle_id": bundle.get("bundle_id"), "stage": "bundle", "error": str(exc)},
                    )

    await asyncio.gather(*(process(b) for b in bundles))
    meta = {
        "started_at": started,
        "finished_at": now_iso(),
        "offline": args.offline,
        "counts": counts,
        "output": str(out),
        "client": client.stats() if client else None,
    }
    write_json(cfg.path("candidates_dir") / "candidates_meta.json", meta)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="local/configs/data.yaml")
    parser.add_argument("--task", action="append", choices=["faithful", "refusal", "multi", "term"])
    parser.add_argument("--split", choices=["train", "dev", "test"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=0)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    cfg = DataConfig.load(args.config)
    args.concurrency = args.concurrency or cfg.generation.concurrency
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
