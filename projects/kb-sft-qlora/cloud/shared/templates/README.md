# Shared templates

These files are the single source of truth for prompt rendering. `local/` and
`cloud/` each have their own `renderer.py`, but both read these files; the
cloud test `tests/test_template_isomorphism.py` fails if the rendered user
message and token IDs drift.

- `system_prompt.txt` — canonical system prompt (8 rules).
- `user_template.txt` — canonical user template, byte-compatible with kb's
  context packing (`[n][source][file_title][url]`).
- `qwen3_nonthinking.jinja` — **not shipped**. Qwen3's chat template is taken
  from the downloaded model at runtime (`tokenizer.apply_chat_template(...,
  enable_thinking=False)`). `cloud/scripts/00_probe_cloud.py --dump-template`
  writes the exact template here for auditing and diffing against 0.6B.
