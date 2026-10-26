from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .config import SHARED_DIR


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def split_of(sample: dict[str, Any]) -> str:
    return str(sample.get("split") or sample.get("metadata", {}).get("split", ""))


def sample_schema() -> dict[str, Any]:
    with open(SHARED_DIR / "schema" / "sample.schema.json", encoding="utf-8") as f:
        return json.load(f)


def validate_sample(sample: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("id", "task_type", "messages", "contexts", "expected_behavior"):
        if key not in sample:
            errors.append(f"missing {key}")
    messages = sample.get("messages", [])
    if len(messages) < 3:
        errors.append("messages < 3")
    else:
        roles = [m.get("role") for m in messages[:3]]
        if roles != ["system", "user", "assistant"]:
            errors.append(f"bad roles: {roles}")
    if not sample.get("contexts"):
        errors.append("empty contexts")
    if sample.get("expected_behavior") not in ("answer", "refuse", "partial", "conflict"):
        errors.append("bad expected_behavior")
    try:
        import jsonschema

        validator = jsonschema.Draft202012Validator(sample_schema())
        errors.extend(f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(sample))
    except ImportError:
        pass
    return errors


def load_split(
    path: str | Path,
    *,
    split: str | None = None,
    limit: int = 0,
    validate: bool = True,
) -> list[dict[str, Any]]:
    """Read a split file or a single all-in-one JSONL.

    If any row carries a split, filter to `split`. Files produced by
    local/scripts/13_export_upload.py carry both `split` and
    `metadata.split`; the separate train/dev/test files also work.
    """
    rows = list(read_jsonl(path))
    has_split = any(split_of(row) for row in rows)
    if split and has_split:
        rows = [row for row in rows if split_of(row) == split]
    if limit:
        rows = rows[:limit]
    if validate:
        for i, row in enumerate(rows):
            errors = validate_sample(row)
            if errors:
                raise SystemExit(f"{path} row {i} invalid: {errors[:5]}")
    if not rows:
        raise SystemExit(f"{path} has no rows for split={split!r}")
    return rows


def validate_split(path: str | Path, *, limit: int = 0) -> list[dict[str, Any]]:
    return load_split(path, limit=limit)
