# Changelog

## 0.1.0 (unreleased)

First version.

- `inspect`: shallow clone (or copy of a local path), detection of languages, dependency
  files, Python version hints, README commands and `pip install` lines, entry points,
  data and weight downloads, GPU hints, and claimed numbers (tables, sentences, ranges,
  `±` values).
- `env`: uv virtualenv per study, requirements and conda files (conda translated to pip),
  `--from-readme`, `--unpin` and `--extra` recorded as deviations, `lock.txt` from
  `uv pip freeze`, exact error on failure.
- `run`: shell command in the repo with the study env active, timeout that kills the
  process tree, CPU-time limit, peak memory, stdout/stderr to files with SHA-256, files
  written, and copies of small result files taken when the run ends.
- `metrics`: `name: value`, `name=value%`, `name value`, `n/d` fractions, JSON, JSON lines,
  CSV/TSV, each with its source line; selectors such as `m1:val_loss:last@each`.
- `compare`: verdicts reproduced, close, not reproduced, could not run; percent/fraction
  rescaling, rounding-aware tolerance, ranges, repeated runs, shortened runs never count.
- `report`: `report.md` and `report.json` with commit, environment, commands, claim,
  measured values with sources, reasoning, deviations and what was not checked.
- Hash-chained `evidence.jsonl` and `verify`.
- MCP server (`paper-repro mcp`), `setup` for Claude Code, Codex and Cursor, and the
  `paper-repro` agent skill.
