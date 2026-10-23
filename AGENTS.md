# Notes for contributors and coding agents

paper-repro is a deterministic recorder. The host agent decides what to run; this package
runs it, captures it, and writes reports. It never calls an LLM.

## Layout

```
src/paper_repro/
  study.py         Study directory, append-only hash-chained evidence.jsonl, state replay
  inspect_repo.py  clone/copy, dependency and entry-point detection, README scan
  claims.py        claimed numbers from Markdown (tables, sentences, ranges, ±)
  paper.py         claimed numbers from the paper (arXiv PDF or local file, pypdf text)
  pdf_tables.py    results tables rebuilt from word positions (pdfminer.six), confidence per cell
  guide.py         the `next` step after each operation (CLI `next:` line, MCP `next` field)
  metrics.py       metric values from logs, JSON, CSV; selectors (m1:acc:last@each)
  envs.py          uv venv + installs, conda translation, unpin, lock.txt
  runner.py        run one shell command with limits, capture outputs and written files
  compare.py       verdict logic (tolerance, rounding, ranges, scale, scope)
  report.py        report.json and report.md, built only from the log
  repro.py         `repro`: one command from a slug, arXiv id or repo to verdict, report, card
  resolve.py       arXiv id to the official repo (arXiv page, PDF links, GitHub search last)
  gallery.py       recipe schema and lookup; data/gallery.yaml holds the vetted recipes
  card.py          1200x630 verdict card (PNG via Pillow, SVG) and a README badge
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
- A value from an agent-written command (run origin `authored`) gets the verdict
  `reimplemented` and can never be shown or counted as a reproduction.
- Gallery numbers come only from `scripts/vet_gallery.py` (a recorded run's report.json);
  `scripts/gallery_docs.py` renders docs/gallery.md and the README table from them.
- `setup` must show its plan, require `--yes` or an interactive yes, back up what it edits,
  and be idempotent. Tests run it against a temp HOME only.
- No em dashes or en dashes in code, docs or messages.
