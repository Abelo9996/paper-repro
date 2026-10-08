# Contributing

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts && uv run ruff format --check src tests scripts
```

Tests must stay offline and fast. They build small fixture repos in temp directories and
run real processes; they never touch your home directory (HOME is redirected) and keep uv
offline. If you add a metric format or a claim pattern, add a test with the exact line it
should match and one it should not.

Reading tables from PDFs is checked against `tests/data/tables/expected.json`, cells
transcribed by hand from real papers. The tests run on saved word boxes (no PDFs in the repo).
To score the reader on the PDFs themselves, or to add a paper:

```bash
uv run python scripts/table_regression.py score --pdf-dir /tmp/pdfs -v          # layout reader
uv run python scripts/table_regression.py score --pdf-dir /tmp/pdfs --reader text  # 0.1.1 reader
uv run python scripts/table_regression.py fixtures --pdf-dir /tmp/pdfs           # refresh fixtures
```

Transcribe a new paper's cells from the rendered page before running the reader on it, and
add it with `"split": "held-out"`, so its first score says something about new papers.

Two rules for changes: the tool must not call any model API, and nothing it writes to a
report may come from anywhere but the evidence log. See `AGENTS.md` for the layout.
