"""MCP server over stdio. Thin wrappers over the same functions the CLI uses."""

from __future__ import annotations

from typing import Any

try:  # mcp >= 2 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError

from .study import StudyError, resolve_study

INSTRUCTIONS = """\
paper-repro checks whether a paper's released code reproduces a number it claims, and records
every step as evidence. You decide what to run; the tools run it and keep the receipts.
Workflow: inspect_repo -> pick a claim id (scan_paper if the number is only in the paper) ->
create_env -> run_command (smoke first, then the claim's configuration with scope full) ->
extract_metrics -> compare_claim -> write_report. Every result has a `next` field saying what
usually comes next. Never type in a number you did not get from extract_metrics; never change
the paper's method to make a run succeed. If the code cannot run, call compare_claim with
could_not_run=true and report the blocking error. Every tool takes an optional `study` path; by
default it acts on the study created by the last inspect_repo call in the server's working
directory.
"""

mcp = _Server("paper-repro", instructions=INSTRUCTIONS)


def _err(exc: Exception) -> dict:
    """Surface a user-facing error as an MCP tool error (isError: true)."""
    raise ToolError(str(exc)) from exc


def _drop_empty(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, [], {}, "")}


def _compact_claim(c: dict) -> dict:
    keep = (
        "id",
        "metric",
        "value",
        "lo",
        "hi",
        "plus_minus",
        "percent",
        "source",
        "line",
        "row",
        "column",
        "confidence",
        "text",
    )
    return _drop_empty({k: c.get(k) for k in keep}) | {"percent": bool(c.get("percent"))}


def _compact_run(e: dict) -> dict:
    return {
        k: e.get(k)
        for k in (
            "id",
            "command",
            "exit_code",
            "signal",
            "timed_out",
            "wall_seconds",
            "peak_rss_mb",
            "scope",
            "note",
            "limits",
            "stdout",
            "stderr",
        )
    } | {
        "files_written": [f["path"] for f in e["files"]["written"][:50]],
        "files_written_count": e["files"]["written_count"],
    }


@mcp.tool()
def inspect_repo(
    source: str, ref: str | None = None, name: str | None = None, workspace: str | None = None
) -> dict[str, Any]:
    """Start here. Shallow-clone a repo (GitHub URL or owner/repo) or copy a local path into a
    study directory, and report how to run it: dependency files, suggested Python, README
    commands and `pip install` lines, entry points, data downloads, GPU hints, linked arXiv
    papers, and every number the README claims (ids c1, c2, ... with file, line and the quoted
    sentence). Calling it again on the same repo reuses the checkout. Next: pick the claim, or
    scan_paper if the number is only in the paper, then create_env."""
    from . import guide
    from .inspect_repo import inspect_repo as run

    try:
        e = run(source, ref=ref, name=name, workspace=workspace)
    except StudyError as exc:
        return _err(exc)
    repo = e["repo"]
    gpu = e.get("gpu") or {}
    return {
        "study": e["study"],
        "repo": {k: repo.get(k) for k in ("url", "source", "commit", "commit_date") if repo.get(k)},
        "primary_language": e.get("primary_language"),
        "dependency_files": [
            {"path": d["path"], "kind": d["kind"]} for d in e.get("dependency_files", [])
        ],
        "readme_install_hints": e.get("readme_install_hints"),
        "suggested_python": e.get("suggested_python"),
        "readme_commands": e.get("readme_commands"),
        "entry_points": [
            _drop_empty({"path": p["path"], "flags": p.get("flags", [])[:15]})
            for p in e.get("entry_points", [])[:20]
        ],
        "downloads": e.get("downloads", [])[:20],
        "gpu": {
            "summary": gpu.get("summary"),
            "examples": [f"{x['source']}: {x['text']}" for x in (gpu.get("code") or [])[:5]],
        },
        "papers": e.get("papers", []),
        "claims": [_compact_claim(c) for c in e.get("claims", [])],
        "next": guide.after_inspect(e),
    }


@mcp.tool()
def scan_paper(source: str | None = None, study: str | None = None) -> dict[str, Any]:
    """Find the numbers the paper itself claims, for when the README does not state the one you
    need. `source` is an arXiv id or URL, or a local PDF or text file; by default it reads the
    arXiv paper the README links (see `papers` in inspect_repo). Downloads the PDF into the
    study, saves its text to paper/<name>.txt, and records claims as p1, p2, ... with page,
    table row and column. Table rows from PDFs are low confidence: check the quoted `text` (or
    read the saved text file) before comparing against one; if the number you need is missing,
    record it with add_claim."""
    from . import guide
    from .paper import scan_paper as run

    try:
        e = run(resolve_study(study), source)
    except StudyError as exc:
        return _err(exc)
    return {
        "paper": e["paper"],
        "claims": [_compact_claim(c) for c in e["claims"]],
        "next": guide.after_paper(e),
    }


@mcp.tool()
def create_env(
    python: str | None = None,
    requirements: list[str] | None = None,
    install_project: bool = False,
    extra: list[str] | None = None,
    unpin: bool = False,
    from_readme: bool = False,
    study: str | None = None,
) -> dict[str, Any]:
    """Build the study's isolated Python environment with uv and install the repo's dependency
    file (requirements.txt, environment.yml translated to pip, or setup.py/pyproject) with pins
    as written. All arguments are optional: by default it uses the Python the repo asks for and
    the dependency file inspect_repo found. If the repo has no dependency file but its README has
    a `pip install` line, pass from_readme=true. Fixes when it fails, least invasive first: a
    newer `python`, then unpin=true, or `extra` packages the repo forgot; each is recorded as a
    deviation. A failed attempt keeps the last working environment. The result has `hints` and
    `next` saying what to try."""
    from . import guide
    from .envs import create_env as run

    try:
        s = resolve_study(study)
        e = run(
            s,
            python=python,
            requirements=requirements,
            install_project=install_project,
            extra=extra,
            unpin_versions=unpin,
            from_readme=from_readme,
        )
    except StudyError as exc:
        return _err(exc)
    out = {
        k: e.get(k)
        for k in (
            "id",
            "status",
            "python",
            "requirements",
            "readme_packages",
            "extra",
            "unpinned",
            "deviations",
            "failure",
            "restored_env",
            "hints",
        )
    }
    out["steps"] = [
        {k: v for k, v in st.items() if k != "stderr_tail" or e["status"] != "ok"}
        for st in e.get("steps", [])
    ]
    out["lock"] = e.get("lock")
    out["key_packages"] = {
        k: v
        for k, v in (e.get("packages") or {}).items()
        if k in ("torch", "tensorflow", "jax", "numpy", "scipy", "scikit-learn", "transformers")
    }
    out["next"] = guide.after_env(e)
    return _drop_empty(out) | {"status": e["status"]}


@mcp.tool()
def run_command(
    command: str,
    timeout_seconds: float = 3600,
    scope: str = "full",
    note: str | None = None,
    seed: int | None = None,
    env: dict[str, str] | None = None,
    cpu_seconds: int | None = None,
    memory_mb: int | None = None,
    study: str | None = None,
) -> dict[str, Any]:
    """Run one shell command from the repo root inside the study env, and record stdout,
    stderr (with SHA-256), exit code, wall time, peak memory and files written. Blocks until it
    finishes or `timeout_seconds` passes (then the whole process tree is killed). scope says
    what the run is: smoke (does it start at all, a few steps), setup (data download or
    preprocessing), full (exactly the configuration the claim refers to), or shortened (fewer
    epochs/steps/data than the claim; `note` must say what was cut, and it can never count as
    a reproduction). Next: extract_metrics on a finished full run."""
    from . import guide
    from .runner import run_command as run

    try:
        s = resolve_study(study)
        e = run(
            s,
            command,
            timeout=timeout_seconds,
            scope=scope,
            note=note,
            seed=seed,
            env=env,
            cpu_seconds=cpu_seconds,
            memory_mb=memory_mb,
        )
    except StudyError as exc:
        return _err(exc)
    return _compact_run(e) | {"next": guide.after_run(e)}


@mcp.tool()
def extract_metrics(
    run_ids: list[str] | None = None,
    files: list[str] | None = None,
    names: list[str] | None = None,
    study: str | None = None,
) -> dict[str, Any]:
    """Pull metric values out of runs' stdout/stderr and the result files they wrote
    (accuracy: 0.91, acc=91.3%, F1 81.2, val loss 1.88, JSON/JSON lines/CSV), each with its
    source file, line and text. Defaults to the latest run; pass run_ids for several. Returns a
    per-metric summary (first, last, min, max with ids). Select values for compare_claim as an
    exact id ('m1.42'), 'm1:val_loss:last' (first|last|min|max), or 'm1:val_loss:last@each' for
    one value per run. Usually the claim is the final evaluation, not a training-step line."""
    from . import guide
    from .metrics import extract_metrics as run

    try:
        s = resolve_study(study)
        e = run(s, run_ids=run_ids, files=files, names=names)
    except StudyError as exc:
        return _err(exc)
    return {
        "id": e["id"],
        "sources": e["sources"],
        "count": len(e["values"]),
        "summary": e["summary"],
        "sample": e["values"][-10:],
        "next": guide.after_metrics(e),
    }


@mcp.tool()
def add_claim(
    metric: str,
    source: str,
    value: float | None = None,
    lo: float | None = None,
    hi: float | None = None,
    percent: bool = False,
    text: str | None = None,
    study: str | None = None,
) -> dict[str, Any]:
    """Record a claimed number that inspect_repo and scan_paper missed or misread. Give `value`
    (or `lo` and `hi` for a range), `percent=true` if it is a percentage, and `source` saying
    exactly where it is stated (for example "arXiv:1609.02907 Table 2, row GCN, column Cora").
    Returns the new claim id (u1, u2, ...) to pass to compare_claim."""
    from .compare import add_claim as run

    try:
        s = resolve_study(study)
        e = run(
            s, metric=metric, value=value, lo=lo, hi=hi, percent=percent, source=source, text=text
        )
    except StudyError as exc:
        return _err(exc)
    return e["claim"]


@mcp.tool()
def compare_claim(
    claim_id: str,
    measured: list[str] | None = None,
    tol: float | None = None,
    rel_tol: float | None = None,
    close_tol: float | None = None,
    why: str | None = None,
    could_not_run: bool = False,
    blocking: str | None = None,
    study: str | None = None,
) -> dict[str, Any]:
    """Put measured values next to a claim and get a verdict with reasons. `measured` is a list
    of selectors from extract_metrics, one per run or seed (or one '@each' selector). Verdicts:
    reproduced (within tolerance), close (within the close band), not_reproduced, inconclusive
    (any value came from a smoke or shortened run), could_not_run (pass could_not_run=true when
    the code would not run; the latest failure is cited). Default tolerance is 1% relative,
    widened to the rounding of the stated value; close band is 3x. Give your own `tol` (absolute)
    or `rel_tol` when you can defend it, with the reason in `why`. Comparing the same claim again
    replaces the earlier verdict in the report, which still lists it as superseded."""
    from . import guide
    from .compare import compare_claim as run

    try:
        s = resolve_study(study)
        e = run(
            s,
            claim_id=claim_id,
            measured=measured,
            tol=tol,
            rel_tol=rel_tol,
            close_tol=close_tol,
            why=why,
            could_not_run=could_not_run,
            blocking=blocking,
        )
    except StudyError as exc:
        return _err(exc)
    return {
        k: e.get(k)
        for k in (
            "id",
            "verdict",
            "numbers_alone",
            "scope",
            "counts_as_reproduction",
            "headline",
            "reasoning",
        )
    } | {"next": guide.after_compare(e)}


@mcp.tool()
def add_note(text: str, kind: str = "observation", study: str | None = None) -> dict[str, Any]:
    """Record a note that goes into the report. kind: observation, deviation (anything you
    changed from the authors' setup, such as a code edit or a different config), not_checked
    (something the report must say was not verified: other claims, data checksums, GPU paths,
    seed variance), or blocker."""
    from .report import add_note as run

    try:
        e = run(resolve_study(study), text, kind)
    except StudyError as exc:
        return _err(exc)
    return {"ok": True, "kind": e["note_kind"], "text": e["text"]}


@mcp.tool()
def write_report(bundle: str | None = None, study: str | None = None) -> dict[str, Any]:
    """Finish here. Write report.md (for people) and report.json from the evidence log: verdict,
    claim, measured values with source lines, commands, environment, deviations and what was not
    checked. With `bundle`, also copy the shareable evidence (reports, log, lock file, run
    outputs; not the checkout or env) to that directory."""
    from . import guide
    from .report import write_report as run

    try:
        s = resolve_study(study)
        return run(s, bundle=bundle) | {"next": guide.after_report(s)}
    except StudyError as exc:
        return _err(exc)


@mcp.tool()
def study_status(study: str | None = None) -> dict[str, Any]:
    """Summarize what the study has recorded: envs, runs, metric extractions, comparisons."""
    from .report import status

    try:
        return status(resolve_study(study))
    except StudyError as exc:
        return _err(exc)


@mcp.tool()
def verify_evidence(study: str | None = None) -> dict[str, Any]:
    """Recheck the evidence log's hash chain and the hashes of captured output files."""
    try:
        return resolve_study(study).verify()
    except StudyError as exc:
        return _err(exc)


def serve() -> None:
    mcp.run()
