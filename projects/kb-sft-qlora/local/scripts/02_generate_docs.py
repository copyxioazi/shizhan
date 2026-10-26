from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

import yaml  # noqa: E402

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.synthetic import DOC_SPECS, TERMS, fact_registry, render_doc  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", type=int, default=0, help="only write the first N docs")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = DataConfig.load()
    docs_dir = cfg.path("corpus_dir") / "docs"
    canon_dir = cfg.path("canon_dir")
    docs_dir.mkdir(parents=True, exist_ok=True)
    canon_dir.mkdir(parents=True, exist_ok=True)

    specs = DOC_SPECS[: args.docs] if args.docs else DOC_SPECS
    written = 0
    lengths: list[int] = []
    for spec in specs:
        path = docs_dir / f"{spec['doc_id']}.md"
        if path.exists() and not args.force:
            text = path.read_text(encoding="utf-8")
        else:
            text = render_doc(spec)
            path.write_text(text, encoding="utf-8")
            written += 1
        lengths.append(len(text))

    (canon_dir / "fact_registry.yaml").write_text(
        yaml.safe_dump(fact_registry(), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (canon_dir / "doc_outlines.yaml").write_text(
        yaml.safe_dump(DOC_SPECS, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (canon_dir / "terminology_glossary.tsv").write_text(
        "\n".join(f"{term}\t{definition}" for term, definition in TERMS) + "\n", encoding="utf-8"
    )
    print(
        f"docs={len(specs)} written={written} avg_chars={sum(lengths)//max(len(lengths),1)} "
        f"dir={docs_dir}"
    )


if __name__ == "__main__":
    main()
