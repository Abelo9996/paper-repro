# Notes for contributors and coding agents

paper-repro is a deterministic recorder. The host agent decides what to run; this package
runs it, captures it, and writes reports. It never calls an LLM.

## Layout

```
src/paper_repro/
  study.py         Study directory, append-only hash-chained evidence.jsonl, state replay
  inspect_repo.py  clone/copy, dependency and entry-point detection, README scan
  claims.py        claimed numbers from Markdown (tables, sentences, ranges, ±)
  paper.py         claimed numbers from the paper (arXiv PDF or local file, pypdf, heuristic tables)
  guide.py         the `next` step after each operation (CLI `next:` line, MCP `next` field)
  metrics.py       metric values from logs, JSON, CSV; selectors (m1:acc:last@each)
  envs.py          uv venv + installs, conda translation, unpin, lock.txt
  runner.py        run one shell command with limits, capture outputs and written files
  compare.py       verdict logic (tolerance, rounding, ranges, scale, scope)
  report.py        report.json and report.md, built only from the log
  agent_setup.py   `setup` for Claude Code, Codex, Cursor
  mcp_server.py    MCP tools over stdio, thin wrappers
  cli.py           argparse CLI, --json everywhere
skills/paper-repro/SKILL.md   the workflow the agent follows (shipped in the wheel)
examples/                     real evidence bundles from real runs
```

## Invariants

- Writers hold the study lock (`Study.lock`, `@locked`); agents may call tools in parallel.
- `evidence.jsonl` is append-only. Every derived view (status, reports) replays it.
  Never mutate an entry; add a new one.
- A shortened or smoke run can never yield `counts_as_reproduction: true`.
- Values typed in by hand are flagged `unsourced` and can never count as a reproduction.
- `setup` must show its plan, require `--yes` or an interactive yes, back up what it edits,
  and be idempotent. Tests run it against a temp HOME only.
- No em dashes or en dashes in code, docs or messages.
