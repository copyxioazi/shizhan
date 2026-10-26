from __future__ import annotations

import re
from typing import Any, Iterable

from .config import SHARED_DIR

CITATION_HEADER = "【参考来源】"
PARTIAL_HEADER = "【无法确认的部分】"
LABEL_RE = re.compile(r"\[C(\d+)\]")
NUM_RE = re.compile(r"\[(\d+)\]")
THINK_RE = re.compile(r"<think\b.*?</think\s*>", re.DOTALL | re.IGNORECASE)


def _load(name: str) -> str:
    return (SHARED_DIR / "templates" / name).read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _load("system_prompt.txt")
USER_TEMPLATE = _load("user_template.txt")


def context_block(chunks: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for idx, chunk in enumerate(chunks, 1):
        parts.append(
            f"[{idx}][{chunk.get('source', 'local')}]"
            f"[{chunk.get('file_title', '')}]"
            f"[{chunk.get('url', '')}]\n{chunk.get('content', '')}\n\n"
        )
    return "".join(parts)


def user_content(chunks: Iterable[dict[str, Any]], item_names: Iterable[str], question: str) -> str:
    names = "、".join(n for n in item_names if n) or "无"
    return USER_TEMPLATE.format(context=context_block(chunks), item_names=names, question=question.strip())


def split_source_block(text: str) -> tuple[str, str]:
    if CITATION_HEADER not in text:
        return text.strip(), ""
    body, _, block = text.partition(CITATION_HEADER)
    return body.strip(), (CITATION_HEADER + block).strip()


def parse_citation_numbers(text: str) -> list[int]:
    body, _ = split_source_block(text)
    return sorted({int(m.group(1)) for m in NUM_RE.finditer(body)})


def citation_block(cited: list[tuple[int, dict[str, Any]]]) -> str:
    lines = [CITATION_HEADER]
    for n, chunk in cited:
        title = chunk.get("display_title") or chunk.get("title", "")
        lines.append(f"[{n}] {chunk.get('file_title', '')} | {title} | {chunk.get('url', '')}")
    return "\n".join(lines)


def remap_labels(text: str, label_to_n: dict[int, int]) -> str:
    def repl(match: re.Match[str]) -> str:
        label = int(match.group(1))
        return f"[{label_to_n[label]}]" if label in label_to_n else match.group(0)

    return LABEL_RE.sub(repl, text)


def strip_think(text: str) -> str:
    text = THINK_RE.sub("", text)
    text = re.sub(r"^\s*思考过程[:：].*?\n", "", text, flags=re.DOTALL)
    return text.strip()


def ensure_partial_section(body: str, missing_info: list[str]) -> str:
    if PARTIAL_HEADER in body or not missing_info:
        return body
    lines = [PARTIAL_HEADER]
    lines.extend(f"{i}. {item}" for i, item in enumerate(missing_info, 1))
    return body.rstrip() + "\n\n" + "\n".join(lines)


def render_assistant(
    candidate: dict[str, Any],
    *,
    contexts: list[dict[str, Any]],
    label_to_chunk_id: dict[int, str],
) -> tuple[str, list[int], list[tuple[int, dict[str, Any]]]]:
    """Return (assistant_text, cited_numbers, cited_chunks).

    The candidate writes answer_text with stable [C1], [C2] labels. This
    function is the only place that maps those labels to shuffled context
    positions and appends the source block.
    """
    chunk_by_id = {c["chunk_id"]: c for c in contexts}
    chunk_to_n = {c["chunk_id"]: int(c["idx"]) for c in contexts if c.get("idx")}
    label_to_n = {
        label: chunk_to_n[chunk_id]
        for label, chunk_id in label_to_chunk_id.items()
        if chunk_id in chunk_to_n
    }

    body = strip_think(candidate["answer_text"])
    body = remap_labels(body, label_to_n)
    behavior = candidate.get("expected_behavior", "answer")

    if behavior == "refuse":
        # A refusal must not carry a source block.
        body, _ = split_source_block(body)
        return body.strip(), [], []

    if behavior == "partial":
        body = ensure_partial_section(body, candidate.get("missing_info", []))

    nums = parse_citation_numbers(body)
    cited = [(n, chunk_by_id_by_n(contexts, n)) for n in nums]
    cited = [(n, c) for n, c in cited if c is not None]
    if not cited:
        return body.strip(), [], []
    return (body.rstrip() + "\n\n" + citation_block(cited)).strip(), [n for n, _ in cited], cited


def chunk_by_id_by_n(contexts: list[dict[str, Any]], n: int) -> dict[str, Any] | None:
    for chunk in contexts:
        if int(chunk.get("idx", -1)) == n:
            return chunk
    return None


def build_messages(user: str, assistant: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]
