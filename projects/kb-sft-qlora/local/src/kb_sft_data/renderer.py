from __future__ import annotations

from typing import Any

from .io_utils import now_iso, sha256_text
from .templates import build_messages, render_assistant, user_content


def build_sample(
    candidate: dict[str, Any],
    bundle: dict[str, Any],
    contexts: list[dict[str, Any]],
    *,
    generator_model: str = "",
    prompt_version: str = "qa-v1",
) -> dict[str, Any]:
    label_to_chunk_id = {int(k.lstrip("C")): v for k, v in bundle.get("evidence_labels", {}).items()}
    candidate = {**candidate, "expected_behavior": bundle["expected_behavior"]}
    assistant, cited_numbers, cited_chunks = render_assistant(
        candidate, contexts=contexts, label_to_chunk_id=label_to_chunk_id
    )
    user = user_content(contexts, bundle.get("item_names", []), candidate["question"])
    messages = build_messages(user, assistant)

    chunk_by_id = {c["chunk_id"]: c for c in contexts}
    evidence = [
        {
            "label": f"C{label}",
            "chunk_id": chunk_id,
            "doc_id": chunk_by_id.get(chunk_id, {}).get("doc_id", ""),
            "file_title": chunk_by_id.get(chunk_id, {}).get("file_title", ""),
        }
        for label, chunk_id in label_to_chunk_id.items()
    ]

    claims: list[dict[str, Any]] = []
    for i, claim in enumerate(candidate.get("claims", []) or [], 1):
        labels = claim.get("evidence_labels") or claim.get("labels") or []
        chunk_ids = [
            label_to_chunk_id[int(str(label).lstrip("C"))]
            for label in labels
            if int(str(label).lstrip("C")) in label_to_chunk_id
        ]
        claims.append(
            {
                "claim_id": claim.get("claim_id", f"c{i}"),
                "text": claim.get("text", ""),
                "evidence_chunk_ids": chunk_ids,
                "support": claim.get("support", "full"),
            }
        )

    citations = [
        {
            "n": n,
            "chunk_id": chunk["chunk_id"],
            "file_title": chunk.get("file_title", ""),
            "title": chunk.get("display_title") or chunk.get("title", ""),
            "url": chunk.get("url", ""),
        }
        for n, chunk in cited_chunks
    ]

    evidence_chunks = [chunk_by_id[cid] for cid in label_to_chunk_id.values() if cid in chunk_by_id]
    source_type = "real" if any(c.get("source_type") == "real" for c in evidence_chunks) else "synthetic"
    doc_type = evidence_chunks[0].get("doc_type", "") if evidence_chunks else ""
    question = str(candidate["question"]).strip()
    sample_id = "kbqa-" + sha256_text(bundle["bundle_id"] + question + assistant)[:12]

    return {
        "id": sample_id,
        "task_type": bundle["task_type"],
        "subtype": bundle.get("subtype", ""),
        "messages": messages,
        "contexts": contexts,
        "evidence": evidence,
        "claims": claims,
        "citations": citations,
        "expected_behavior": bundle["expected_behavior"],
        "metadata": {
            "split": bundle["split"],
            "item_names": bundle.get("item_names", []),
            "source_type": source_type,
            "doc_type": doc_type,
            "difficulty": candidate.get("difficulty", "medium"),
            "format_template": candidate.get("format_template", "plain"),
            "terminology_used": candidate.get("terminology_used", []),
            "prompt_version": prompt_version,
            "generator_model": generator_model,
            "bundle_id": bundle["bundle_id"],
            "question": question,
            "question_hash": sha256_text(question),
            "conflict_values": candidate.get("conflict_values", bundle.get("conflict_values", [])),
            "missing_info": candidate.get("missing_info", []),
            "created_at": now_iso(),
            "token_counts": {
                "prompt": max(1, len(user) // 2),
                "answer": max(1, len(assistant) // 2),
            },
            "rule_pass": None,
            "judge": None,
        },
        "gold": False,
    }
