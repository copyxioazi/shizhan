from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

CITE_RE = re.compile(r"\[(\d+)\]")
SOURCE_LINE_RE = re.compile(r"^\[(\d+)\]\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*$")


def load_predictions(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _parse(answer: str) -> tuple[list[int], dict[int, dict[str, str]], str]:
    body = answer
    entries: dict[int, dict[str, str]] = {}
    if "【参考来源】" in answer:
        body, _, block = answer.partition("【参考来源】")
        for line in block.splitlines()[1:]:
            match = SOURCE_LINE_RE.match(line.strip())
            if match:
                entries[int(match.group(1))] = {
                    "file_title": match.group(2).strip(),
                    "title": match.group(3).strip(),
                    "url": match.group(4).strip(),
                }
    body_nums = [int(n) for n in CITE_RE.findall(body)]
    return body_nums, entries, body


def _row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    answer = row.get("prediction", "")
    behavior = row.get("expected_behavior", "")
    contexts = row.get("contexts", [])
    body_nums, entries, body = _parse(answer)
    valid_nums = [n for n in body_nums if 1 <= n <= len(contexts)]
    source_ok = True
    for n, entry in entries.items():
        if not (1 <= n <= len(contexts)):
            source_ok = False
            continue
        ctx = contexts[n - 1]
        if entry["file_title"] != ctx.get("file_title", ""):
            source_ok = False
        title = ctx.get("display_title") or ctx.get("title", "")
        if entry["title"] != title:
            source_ok = False
    refusal_like = ("无法" in body or "缺少" in body)
    has_source = bool(entries) or "【参考来源】" in answer
    think = ("<think" in answer.lower()) or ("思考过程" in answer)

    correct_behavior = False
    if behavior == "refuse":
        correct_behavior = refusal_like and not has_source
    elif behavior in ("answer", "partial"):
        correct_behavior = has_source and bool(body_nums)
    elif behavior == "conflict":
        values = row.get("metadata", {}).get("conflict_values", []) or []
        correct_behavior = has_source and len({n for n in valid_nums}) >= 2 and all(
            v in body for v in values if v
        )
    evidence_ids = {e.get("chunk_id") for e in row.get("evidence", []) if e.get("chunk_id")}
    cited_ids = {contexts[n - 1].get("chunk_id") for n in valid_nums if 1 <= n <= len(contexts)}
    recall = len(evidence_ids & cited_ids) / max(len(evidence_ids), 1) if evidence_ids else None
    return {
        "behavior_correct": correct_behavior,
        "format_pass": has_source if behavior != "refuse" else not has_source,
        "citation_valid": source_ok and all(n in range(1, len(contexts) + 1) for n in body_nums),
        "citation_precision_proxy": len(valid_nums) / max(len(body_nums), 1),
        "citation_recall_proxy": recall,
        "think_leakage": think,
        "refusal_like": refusal_like,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [_row_metrics(r) for r in rows]
    n = max(len(metrics), 1)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row, metric in zip(rows, metrics):
        by_type.setdefault(row.get("task_type", ""), []).append(metric)

    def mean(key: str, items: list[dict[str, Any]]) -> float | None:
        vals = [m[key] for m in items if m.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {
        "n": len(rows),
        "behavior_correct": mean("behavior_correct", metrics),
        "format_pass": mean("format_pass", metrics),
        "citation_valid": mean("citation_valid", metrics),
        "citation_precision_proxy": mean("citation_precision_proxy", metrics),
        "citation_recall_proxy": mean("citation_recall_proxy", metrics),
        "think_leakage_count": sum(1 for m in metrics if m["think_leakage"]),
        "by_type": {
            task_type: {
                "n": len(items),
                "behavior_correct": mean("behavior_correct", items),
                "format_pass": mean("format_pass", items),
                "citation_recall_proxy": mean("citation_recall_proxy", items),
            }
            for task_type, items in sorted(by_type.items())
        },
    }
    return summary


def compare(base_rows: list[dict[str, Any]], adapter_rows: list[dict[str, Any]], output_dir: str | Path) -> dict[str, Any]:
    base = aggregate(base_rows)
    adapter = aggregate(adapter_rows)
    delta = {
        key: (round(adapter[key] - base[key], 4) if isinstance(base.get(key), (int, float)) and isinstance(adapter.get(key), (int, float)) else None)
        for key in ("behavior_correct", "format_pass", "citation_valid", "citation_precision_proxy", "citation_recall_proxy")
    }
    report = {"base": base, "adapter": adapter, "delta": delta}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Evaluation report",
        "",
        "| metric | base | adapter | delta |",
        "|---|---:|---:|---:|",
    ]
    for key in ("behavior_correct", "format_pass", "citation_valid", "citation_precision_proxy", "citation_recall_proxy"):
        lines.append(f"| {key} | {base.get(key)} | {adapter.get(key)} | {delta.get(key)} |")
    lines += [
        f"| think_leakage_count | {base['think_leakage_count']} | {adapter['think_leakage_count']} | - |",
        "",
        "`citation_precision_proxy` and `citation_recall_proxy` are rule-based proxies;",
        "claim-level faithfulness/completeness require an LLM judge (not computed here).",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
