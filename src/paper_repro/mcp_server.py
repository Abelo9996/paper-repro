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
paper-repro records a reproduction attempt of a paper's released code as evidence.
Workflow: inspect_repo -> pick a claim id -> create_env -> run_command (smallest faithful run
first) -> extract_metrics -> compare_claim -> write_report. You choose the commands; the tool
records them. Never type a number into compare_claim that you did not get from extract_metrics
unless you say so; never change the paper's method to make a run succeed. If the code cannot
run, call compare_claim with could_not_run=true and report the blocking error.
Every tool takes an optional `study` path; by default it acts on the study created by the last
inspect_repo call in the workspace.
"""

mcp = _Server("paper-repro", instructions=INSTRUCTIONS)


def _err(exc: Exception) -> dict:
    """Surface a user-facing error as an MCP tool error (isError: true)."""
    raise ToolError(str(exc)) from exc


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
    """Shallow-clone a git repo (URL or owner/repo) or copy a local path into a new study, and
    report languages, dependency files, Python version hints, README run commands, entry points,
    data/weight downloads, GPU hints and every number the README claims (ids c1, c2, ...)."""
    from .inspect_repo import inspect_repo as run

    try:
        e = run(source, ref=ref, name=name, workspace=workspace)
    except StudyError as exc:
        return _err(exc)
    return {k: v for k, v in e.items() if k not in ("prev", "hash")}


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
    """Create an isolated uv virtualenv for the repo and install its dependencies with pins as
    written. Records every install command, the exact error on failure, and a lock file.
    `from_readme` installs the packages named in a README `pip install` line when the repo has no
    dependency file. `extra`, `unpin` and `from_readme` are recorded as deviations."""
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
    e.pop("packages", None)
    return e


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
    """Run a shell command from the repo root inside the study env. Captures stdout/stderr to
    files, exit code, wall time, peak memory and files written. scope: full (the configuration
    the claim is about), shortened (fewer epochs/steps/data; note required), smoke, or setup."""
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
    return _compact_run(e)


@mcp.tool()
def extract_metrics(
    run_ids: list[str] | None = None,
    files: list[str] | None = None,
    names: list[str] | None = None,
    study: str | None = None,
) -> dict[str, Any]:
    """Extract metric values (accuracy: 0.91, acc=91.3%, F1 81.2, JSON/CSV results) from runs'
    output and files they wrote, each with its source line. Returns a per-metric summary with
    ids; select values for compare_claim as 'm1.42' or 'm1:val_loss:last' (first|last|min|max)."""
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
    """Record a claim the README scan missed (for example from the paper's table). `source` must
    say where it is stated. Returns the new claim id (u1, u2, ...)."""
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
    """Compare measured values (metric selectors, one per run or seed) with a claim. Verdict is
    reproduced, close, not_reproduced or could_not_run, with the numbers and reasoning. Default
    tolerance is 1% relative (widened to the rounding of the stated value); close is 3x that."""
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
        k: e[k]
        for k in ("id", "verdict", "scope", "counts_as_reproduction", "headline", "reasoning")
    }


@mcp.tool()
def add_note(text: str, kind: str = "observation", study: str | None = None) -> dict[str, Any]:
    """Record a note for the report. kind: observation, deviation (anything you changed from the
    authors' setup), not_checked (something the report must say was not verified), blocker."""
    from .report import add_note as run

    try:
        e = run(resolve_study(study), text, kind)
    except StudyError as exc:
        return _err(exc)
    return {"ok": True, "kind": e["note_kind"], "text": e["text"]}


@mcp.tool()
def write_report(bundle: str | None = None, study: str | None = None) -> dict[str, Any]:
    """Write report.md and report.json from the evidence log. With `bundle`, also copy the
    shareable evidence (reports, log, lock file, run outputs; not the repo or env) there."""
    from .report import write_report as run

    try:
        return run(resolve_study(study), bundle=bundle)
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
