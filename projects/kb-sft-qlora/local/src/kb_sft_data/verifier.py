from __future__ import annotations

import re
import unicodedata
from typing import Any

from .schema import validate_sample
from .templates import CITATION_HEADER, PARTIAL_HEADER, SYSTEM_PROMPT, split_source_block

NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")
CITE_RE = re.compile(r"\[\d+\]")
SOURCE_LINE_RE = re.compile(r"^\[(\d+)\]\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*$")
ADJUDICATION = ("应以", "正确的是", "建议以", "最终以", "以…为准", "以...为准")


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def numbers_in(text: str) -> list[str]:
    text = CITE_RE.sub("", text)
    out: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*\d+[.、)]\s*", "", line)
        out.extend(NUM_RE.findall(line))
    return out


def parse_source_block(answer: str) -> tuple[dict[int, dict[str, str]], str]:
    body, block = split_source_block(answer)
    entries: dict[int, dict[str, str]] = {}
    if not block:
        return entries, body
    for line in block.splitlines()[1:]:
        match = SOURCE_LINE_RE.match(line.strip())
        if match:
            entries[int(match.group(1))] = {
                "file_title": match.group(2).strip(),
                "title": match.group(3).strip(),
                "url": match.group(4).strip(),
            }
    return entries, body


def _context_by_n(contexts: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(c.get("idx", i + 1)): c for i, c in enumerate(contexts)}


def verify_sample(sample: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    reasons.extend(validate_sample(sample))
    messages = sample.get("messages", [])
    if len(messages) < 3:
        return False, reasons + ["messages too short"]
    system, user, assistant = (m.get("content", "") for m in messages[:3])
    if system.strip() != SYSTEM_PROMPT:
        reasons.append("system prompt mismatch")
    question = sample.get("metadata", {}).get("question", "")
    if question and question not in user:
        reasons.append("question missing from user message")
    if "【参考内容】" not in user:
        reasons.append("user message missing context header")
    if "<think" in assistant.lower() or "思考过程" in assistant:
        reasons.append("think leakage")
    if not assistant.strip():
        reasons.append("empty assistant")

    contexts = sample.get("contexts", [])
    if not contexts:
        reasons.append("empty contexts")
    ctx_by_n = _context_by_n(contexts)
    entries, body = parse_source_block(assistant)
    cited = sorted(entries)
    if cited and cited != sorted({n for n in cited if n in ctx_by_n}):
        reasons.append("citation refers to missing context")
    body_nums = sorted({int(n) for n in re.findall(r"\[(\d+)\]", body)})
    if sample.get("expected_behavior") != "refuse" and body_nums != cited:
        reasons.append("body citations and source block mismatch")

    behavior = sample.get("expected_behavior")
    if behavior == "answer":
        if not cited:
            reasons.append("answer has no citations")
        for n in cited:
            ctx = ctx_by_n.get(n)
            if not ctx:
                continue
            src = entries[n]
            expected_title = ctx.get("display_title") or ctx.get("title", "")
            if src["file_title"] != ctx.get("file_title", ""):
                reasons.append(f"citation {n} file_title mismatch")
            if normalize(src["title"]) != normalize(expected_title):
                reasons.append(f"citation {n} title mismatch")
            if src["url"] != ctx.get("url", ""):
                reasons.append(f"citation {n} url mismatch")
        cited_text = "\n".join(
            " ".join(
                [
                    ctx_by_n[n].get("content", ""),
                    ctx_by_n[n].get("file_title", ""),
                    ctx_by_n[n].get("display_title", ""),
                    ctx_by_n[n].get("title", ""),
                ]
            )
            for n in cited
            if n in ctx_by_n
        )
        question_numbers = set(numbers_in(sample.get("metadata", {}).get("question", "")))
        for num in numbers_in(body):
            if num in question_numbers:
                continue
            if num not in cited_text and normalize(num) not in normalize(cited_text):
                reasons.append(f"number {num} not supported by cited context")
    elif behavior == "refuse":
        if entries or CITE_RE.search(body):
            reasons.append("refusal cites sources")
        if "无法" not in body and "缺少" not in body:
            reasons.append("refusal does not state inability/missing info")
        if not sample.get("metadata", {}).get("missing_info"):
            reasons.append("refusal missing missing_info")
    elif behavior == "partial":
        if not cited:
            reasons.append("partial answer has no citations")
        if PARTIAL_HEADER not in body and "无法确认" not in body:
            reasons.append("partial answer missing gaps section")
        if not sample.get("metadata", {}).get("missing_info"):
            reasons.append("partial missing missing_info")
    elif behavior == "conflict":
        cited_chunks = {ctx_by_n[n]["chunk_id"] for n in cited if n in ctx_by_n}
        if len(cited_chunks) < 2:
            reasons.append("conflict must cite two chunks")
        for value in sample.get("metadata", {}).get("conflict_values", []) or []:
            if value and normalize(value) not in normalize(body):
                reasons.append(f"conflict value missing: {value}")
        if any(phrase in body for phrase in ADJUDICATION):
            reasons.append("conflict adjudicates")
    else:
        reasons.append("bad expected_behavior")

    if sample.get("task_type") == "multi":
        cited_chunks = {ctx_by_n[n]["chunk_id"] for n in cited if n in ctx_by_n}
        if len(cited_chunks) < 2:
            reasons.append("multi-chunk sample cites fewer than 2 chunks")
        claim_chunks = {
            cid for claim in sample.get("claims", []) for cid in claim.get("evidence_chunk_ids", [])
        }
        if len(claim_chunks) < 2:
            reasons.append("multi-chunk claims cover fewer than 2 chunks")

    return not reasons, reasons
