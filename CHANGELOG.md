# Changelog

## 0.1.3

### Fixed

- Require mcp 1.30 or newer. The old floor (`mcp>=1.2`) allowed releases that no longer import with current pydantic; the MCP server's tests pass on 1.30.0 and 2.3.0.

## 0.1.2

Results tables in paper PDFs are now read from word positions instead of plain text.

- `paper` / `scan_paper` rebuild each table from word boxes (new dependency: `pdfminer.six`).
  Columns are placed by the x-position of the numbers and named from every header line above
  them, so two-level headers work: the Transformer paper's Table 2 now gives
  `[Transformer (big) | BLEU EN-DE] 28.4`, where 0.1.1 gave no column name.
- Captions below their table and tables stacked on one page are handled. In 0.1.1 the ResNet
  paper's Table 4 values were reported as Table 3.
- Section rows (`Ours`, `Published`), blank cells that repeat the label above, labels centered
  on several rows, drawn column rules, `±` spreads after a `%`, `a/b` cells and a citation
  column next to its number (ELMo's "Previous SOTA") are read.
- Setup columns (depth, params, cost, `N`, `d_model`) are no longer reported as results; they
  name rows that would otherwise repeat, as in `DenseNet (k = 12) (Depth 40)`.
- Every table claim carries `table`, `page`, the exact `row` and `column` labels, `row_group`,
  and a `confidence` (high, medium, low) with `confidence_score` and `confidence_notes`. The CLI
  prints the table and confidence; `compare` and the report quote the table cell.
- `top-1 err.` columns are named `top_1_error` (lower is better). 0.1.1 named them
  `top1_accuracy`, which would have judged lower error as worse.
- The rebuilt tables are saved to `paper/<name>.tables.md` for checking a claim against its
  table. MCP claims no longer repeat the caption in every `text`.
- If pdfminer cannot read a file, the old text reader is used and the paper record says so.
- `inspect` of a local path no longer fails when git deletes a lock file while the repo is
  being copied (seen once on macOS CI).
- Regression set: 13 tables from 8 arXiv papers with hand-transcribed cells, word-box fixtures
  for offline tests, and `scripts/table_regression.py` to score either reader. Precision on the
  9 dev tables went from 0.64 (0.1.1) to 1.00; on 4 held-out tables the first run scored 0.33
  and, after fixes, 0.99. The README explains why neither 1.00 nor 0.99 is a promise for new
  papers.

## 0.1.1

Fixes from a fresh-install audit and two real headless Claude Code sessions.

- New `paper` command and `scan_paper` MCP tool: reads the paper itself (the arXiv paper the
  README links, any arXiv id or URL, or a local PDF or text file), saves its text in the study,
  and records the numbers it states as `p1`, `p2`, ... with page, table row and column. Tables
  are read heuristically and marked low confidence. `inspect` now lists linked arXiv papers.
  Adds `pypdf` as a dependency.
- A failed `env` attempt no longer deletes the working environment: the previous env and
  `lock.txt` are put back, and the report names the env the runs actually used.
- `env` says what to try when it fails (newer Python, `--unpin`) and warns when nothing was
  installed because the repo has no dependency file but its README has a `pip install` line.
- New verdict **inconclusive** for any comparison that uses a smoke or shortened run. These were
  reported as "not reproduced" or "reproduced" before, which overstated what a cut-down run shows.
  Headlines now say how far the value is from the claim and which band it fell in.
- Comparing a claim again supersedes the earlier verdict: the report's headline and verdict list
  use the latest one and still show the earlier one as superseded. Before, both counted.
- Every CLI step prints a `next:` line, and every MCP result has a `next` field.
- MCP tool descriptions rewritten to say when to use each tool and what comes next.
  `inspect_repo` returns a compact result without log internals.
- Runs started at the same time (agents sometimes call `run_command` in parallel) get distinct
  ids, the evidence log is locked against concurrent writes, and overlapping runs are noted in
  the report.
- Re-inspecting a repo written differently (`owner/repo` versus its URL) no longer errors, and a
  failed clone no longer leaves an empty study directory. The clone error says what to check.
- `setup` prints what to do after applying, says when no agent was found, and exits non-zero
  if an action failed.
- Distances in reasons are written as `122%` instead of `1.2e+02%`.

## 0.1.0

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
