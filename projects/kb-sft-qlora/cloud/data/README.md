# Cloud data

- `kb_sft_all.jsonl` — 2,884 rows; `split` / `metadata.split` gives
  2,308 train / 288 dev / 288 test.
- `gold_dev_100.jsonl`, `gold_test_100.jsonl` — 100 human-review rows each.
- `split_manifest.json` — counts and the random-split leakage note.
- `export_manifest.json` — source manifest from the local export.

The dev/test split is a stratified random sample-level split from train, so
some contexts/chunks appear in both. Use it for format/refusal/behavior
trends; do not treat groundedness numbers as a clean held-out benchmark.
