from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.io_utils import read_jsonl, write_json, write_jsonl  # noqa: E402
from kb_sft_data.judge import judge_batch  # noqa: E402
from kb_sft_data.llm_client import AsyncLLMClient, LLMError  # noqa: E402
from kb_sft_data.pipeline import load_prompt  # noqa: E402


def _verdict_ok(verdict: dict | None) -> bool:
    return bool(verdict and verdict.get("accept"))


async def main_async(args: argparse.Namespace) -> None:
    cfg = DataConfig.load(args.config)
    src = cfg.path("verified_dir") / "verified.jsonl"
    if not src.exists():
        raise SystemExit(f"missing {src}; run 08_verify_rule.py")
    samples = list(read_jsonl(src))
    prompt = load_prompt("judge.md")

    if args.skip:
        for sample in samples:
            sample["metadata"]["judge"] = {"skipped": True, "accept": None}
        out = cfg.path("verified_dir") / "judged.jsonl"
        write_jsonl(out, samples)
        write_json(cfg.path("verified_dir") / "judge_stats.json",
                   {"judged": len(samples), "accepted": 0, "skipped": True})
        print(f"skipped judge; wrote {len(samples)} -> {out}")
        return

    try:
        client = AsyncLLMClient(budget_usd=cfg.generation.budget_usd,
                                timeout_s=cfg.generation.timeout_s,
                                max_retries=cfg.generation.max_retries)
    except LLMError as exc:
        raise SystemExit(f"{exc}\nUse --skip to build an unjudged smoke dataset.") from exc

    pending = [s for s in samples if args.force or not s.get("metadata", {}).get("judge")]
    concurrency = args.concurrency or cfg.generation.concurrency
    print(f"judging {len(pending)}/{len(samples)} samples (concurrency={concurrency})")
    verdicts: dict[str, dict] = {}
    for start in range(0, len(pending), 100):
        batch = pending[start : start + 100]
        results = await judge_batch(batch, client, prompt, concurrency=concurrency)
        for item in results:
            if item["verdict"] is None:
                verdicts[item["id"]] = {"accept": False, "error": item["error"]}
            else:
                verdicts[item["id"]] = item["verdict"]
        print(f"judged {min(start + 100, len(pending))}/{len(pending)}", flush=True)

    for sample in samples:
        if sample["id"] in verdicts:
            sample["metadata"]["judge"] = verdicts[sample["id"]]
    out = cfg.path("verified_dir") / "judged.jsonl"
    write_jsonl(out, samples)
    accepted = sum(1 for s in samples if _verdict_ok(s.get("metadata", {}).get("judge")))
    stats = {
        "judged": len(samples),
        "accepted": accepted,
        "accept_rate": round(accepted / max(len(samples), 1), 4),
        "client": client.stats(),
        "output": str(out),
    }
    write_json(cfg.path("verified_dir") / "judge_stats.json", stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="local/configs/data.yaml")
    parser.add_argument("--skip", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--concurrency", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
