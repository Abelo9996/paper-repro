# Contributing

```bash
uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
```

Tests must stay offline and fast. They build small fixture repos in temp directories and
run real processes; they never touch your home directory (HOME is redirected) and keep uv
offline. If you add a metric format or a claim pattern, add a test with the exact line it
should match and one it should not.

Two rules for changes: the tool must not call any model API, and nothing it writes to a
report may come from anywhere but the evidence log. See `AGENTS.md` for the layout.
