from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import SHARED_DIR

TASK_TYPES = ("faithful", "refusal", "multi", "term")
BEHAVIORS = ("answer", "refuse", "partial", "conflict")
ROLES = ("system", "user", "assistant")


def sample_schema() -> dict[str, Any]:
    path = SHARED_DIR / "schema" / "sample.schema.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_sample(sample: dict[str, Any]) -> list[str]:
    """Return a list of errors; empty means valid."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return _manual_sample_errors(sample)
    validator = jsonschema.Draft202012Validator(sample_schema())
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(sample)]


def _manual_sample_errors(sample: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("id", "task_type", "messages", "contexts", "expected_behavior", "metadata"):
        if key not in sample:
            errors.append(f"missing {key}")
    if sample.get("task_type") not in TASK_TYPES:
        errors.append("bad task_type")
    if sample.get("expected_behavior") not in BEHAVIORS:
        errors.append("bad expected_behavior")
    messages = sample.get("messages", [])
    if len(messages) < 3 or [m.get("role") for m in messages[:3]] != list(ROLES):
        errors.append("messages must be system/user/assistant")
    return errors


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("task_type", "subtype", "question", "answer_text", "expected_behavior"):
        if not candidate.get(key):
            errors.append(f"missing {key}")
    if candidate.get("task_type") not in TASK_TYPES:
        errors.append("bad task_type")
    if candidate.get("expected_behavior") not in BEHAVIORS:
        errors.append("bad expected_behavior")
    if candidate.get("expected_behavior") in ("answer", "partial", "conflict"):
        if not candidate.get("claims"):
            errors.append("claims required for grounded answers")
    if candidate.get("expected_behavior") in ("refuse", "partial"):
        if not candidate.get("missing_info"):
            errors.append("missing_info required for refuse/partial")
    if candidate.get("expected_behavior") == "conflict":
        if len(candidate.get("conflict_values", [])) < 2:
            errors.append("at least two conflict_values required")
    if "<think" in candidate.get("answer_text", ""):
        errors.append("think tag in answer_text")
    return errors


def require_file(path: str | Path) -> Path:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"missing file: {p}")
    return p
