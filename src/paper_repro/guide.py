"""The next step after each operation, in plain words, for people and agents alike.

Each function looks at what a step just recorded and says what usually comes next. The CLI
prints it as a `next:` line; the MCP tools return it as `next`.
"""

from __future__ import annotations

from .study import Study


def after_inspect(e: dict) -> str:
    claims = e.get("claims") or []
    papers = e.get("papers") or []
    parts = []
    if claims:
        parts.append(
            f"pick the claim the user asked about ({claims[0]['id']} to {claims[-1]['id']}) and say why"
        )
    else:
        parts.append("the README states no numbers")
    if papers:
        parts.append(
            f"if the number is only in the paper, scan it: `paper-repro paper` "
            f"(MCP scan_paper) reads arXiv:{papers[0]['arxiv']}, linked at {papers[0]['source']}"
        )
    elif not claims:
        parts.append(
            "pass the paper with `paper-repro paper <arXiv id or PDF>` (MCP scan_paper), or record "
            "the number with `paper-repro claim` (MCP add_claim)"
        )
    deps = e.get("dependency_files") or []
    hints = e.get("readme_install_hints") or []
    if deps:
        env = "`paper-repro env` (MCP create_env) installs from " + deps[0]["path"]
    elif hints:
        env = (
            "`paper-repro env --from-readme` (MCP create_env with from_readme=true) installs "
            f"the packages in {hints[0]['source']}"
        )
    else:
        env = "`paper-repro env --extra <packages>` (MCP create_env with extra=[...])"
    parts.append(f"then build the environment: {env}")
    return "; ".join(parts) + "."


def after_paper(e: dict) -> str:
    n = len(e.get("claims") or [])
    if not n:
        return (
            f"No numbers were recognized. Read {e['paper']['text_path']} and record the claim with "
            "`paper-repro claim` (MCP add_claim), giving the page and table as the source."
        )
    return (
        f"{n} claimed numbers recorded as p-ids. Table rows from PDFs are low confidence: check "
        f"the quoted row (or {e['paper']['text_path']}) before using one. If the one you need is "
        "missing or misread, record it with `paper-repro claim` (MCP add_claim)."
    )


def after_env(e: dict) -> str:
    hints = e.get("hints") or []
    if e["status"] == "ok" and not any(h.startswith("Nothing was installed") for h in hints):
        return (
            "Start with a cheap smoke run (scope smoke) to catch import and path errors, put data "
            "downloads and preprocessing in scope setup runs, then run the claim's configuration "
            "with scope full."
        )
    if hints:
        return hints[0]
    return (
        "Read the error. If no fix keeps the authors' method intact, record it with "
        "`paper-repro compare --claim <id> --could-not-run` (MCP compare_claim with "
        "could_not_run=true)."
    )


def after_run(e: dict) -> str:
    rid = e["id"]
    if e.get("timed_out"):
        return (
            f"{rid} hit the time limit. Re-run with a longer timeout, or cut the run and label it "
            "scope shortened with a note saying what was cut."
        )
    if e.get("exit_code") != 0:
        return (
            f"{rid} failed: read the stderr tail. Fix the environment if a package is missing "
            "(create_env again with extra or unpin), but never edit the method. If it cannot be "
            "fixed, compare the claim with could_not_run=true."
        )
    if e.get("scope") == "setup":
        return "Setup step recorded. Next, a smoke run, then the full run."
    if e.get("scope") == "smoke":
        return (
            "It starts. Now run the configuration the claim refers to with scope full "
            "(or scope shortened with a note, if the full run is out of reach)."
        )
    return f"Extract the numbers: `paper-repro metrics --run {rid}` (MCP extract_metrics)."


def after_metrics(e: dict) -> str:
    mid = e["id"]
    names = [s["name"] for s in e.get("summary") or []]
    if not names:
        return (
            "No metric values were recognized. If the run wrote a results file, pass it with "
            "--file (MCP files=[...]); otherwise check the run's stdout for the line that holds "
            "the number."
        )
    example = names[0]
    for preferred in ("val_loss", "test_accuracy", "accuracy", "test_acc", "f1", "bleu"):
        if preferred in names:
            example = preferred
            break
    return (
        f"Pick the value that matches the claim (usually the final evaluation) and compare: "
        f"`paper-repro compare --claim <id> --measured {mid}:{example}:last` (MCP compare_claim "
        f"with measured=['{mid}:{example}:last']). For several runs, use {mid}:{example}:last@each."
    )


def after_compare(e: dict) -> str:
    if e["verdict"] == "inconclusive":
        return (
            "A shortened or smoke run cannot settle the claim. Run the full configuration if it "
            "is feasible; otherwise write the report and say plainly that the claim was not tested "
            "at full size."
        )
    return (
        "Record anything you did not verify with `paper-repro note --kind not_checked` (MCP "
        "add_note), then write the report: `paper-repro report` (MCP write_report)."
    )


def after_report(study: Study) -> str:
    return (
        f"Give the user the verdict line, the measured numbers, {study.root / 'report.md'}, and "
        "the main items under 'What was not checked'."
    )
