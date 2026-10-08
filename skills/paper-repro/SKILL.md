---
name: paper-repro
description: Check whether a paper's released code reproduces a number it claims. Use when asked to reproduce, verify, sanity-check or "get running" a paper's GitHub repo, or to find out whether a README's reported accuracy, loss, F1 or similar holds up. Also use when the user names a paper (arXiv id or PDF) and its code. Produces a verdict (reproduced, close, not reproduced, inconclusive, could not run) with an evidence bundle.
---

# Reproducing a paper's number with paper-repro

You drive; paper-repro records. It never decides what to run and never calls a model. Your job
is to get the authors' code to produce the number they claim, under their configuration, and
to report what happened, including when it did not work.

Use the MCP tools (`inspect_repo`, `scan_paper`, `create_env`, `run_command`,
`extract_metrics`, `compare_claim`, `add_claim`, `add_note`, `write_report`) or the CLI
(`paper-repro <subcommand> --json`). They are the same operations. Every result carries a
`next` field (a `next:` line in the CLI) with the usual next step; read it, but your judgment
about the claim and the method comes first.

## Workflow

1. **Inspect.** `inspect_repo(source)` (or `paper-repro inspect <url>`). Read the result:
   dependency files, suggested Python, README commands, entry points, downloads, GPU hints, and
   the claimed numbers with ids (`c1`, `c2`, ...).

2. **Pick the claim.** Choose one headline number the user cares about, ideally one the README
   ties to a specific configuration and command. Say which claim id you picked and why. If the
   number is only in the paper, call `scan_paper()` (it reads the arXiv paper the README links,
   or pass an arXiv id or a PDF path). Its claims (`p1`, `p2`, ...) carry page, table row and
   column, and table rows are low confidence: check the quoted `text`, or read the saved
   `paper/*.txt`, before using one. If the number is missing or misread, record it with
   `add_claim` and give its source (for example "arXiv:1609.02907 Table 2, row GCN, Cora").
   Also read what the README says about the code's relation to the paper (a re-implementation
   that "is not intended for reproduction" changes what a mismatch means; say so).

3. **Check feasibility before spending time.** Hardware (GPU-only code on a CPU machine),
   dataset size, licensed or gated data, and the run time the README states. If the full run
   is out of reach, say so up front and plan a shortened run, labeled as such.

4. **Set up the environment.** `create_env` with the repo's own dependency file and the Python
   version it asks for. Pins are kept as written. If setup fails, read the exact error.
   Acceptable fixes, each recorded as a deviation by the tool: a newer Python when the stated
   one has no build for this machine, `unpin` when old pins have no wheels, `extra` packages
   when the repo forgot to list one. Try the least invasive fix first.

5. **Smallest faithful run first.** Start with a smoke run (`scope="smoke"`, one batch or one
   step) to flush out import and path errors cheaply. Then run the configuration the claim
   refers to (`scope="full"`). If you must cut epochs, steps or data, use
   `scope="shortened"` and say in `note` exactly what was cut. Data downloads and
   preprocessing go in `scope="setup"` runs so they are on the record too.

6. **Extract.** `extract_metrics(run_ids=[...])`, then pick the value that corresponds to the
   claim (usually the final evaluation, not a training-step log line). Use selectors like
   `m2:val_loss:last` or an exact id like `m2.341`. If the run writes a results file, pass it
   with `files=[...]`.

7. **Repeat if variance matters.** If the claim is a mean over seeds or a range, run 2 to 5
   seeds when time allows and pass one selector per run to `compare_claim`.

8. **Compare.** `compare_claim(claim_id, measured=[...], tol=..., why=...)`. Choose a tolerance
   you can defend (the authors' reported std, the eval noise, the rounding of the stated
   value) and give the reason in `why`. Defaults: 1% relative, close band 3x that. Any value
   from a smoke or shortened run gives **inconclusive**: that is the honest verdict, not a
   failure to fix by relabeling the run.

9. **Report.** `write_report()`. Give the user the verdict line, the numbers, the path to
   `report.md`, and the main caveats from "What was not checked".

## Rules

- **Never fabricate or estimate a number.** Every measured value must come from
  `extract_metrics` on a recorded run. If you type a value by hand, it is flagged as unsourced.
- **Never change the method to make it work.** Do not edit model code, losses, data splits,
  evaluation code or hyperparameters the claim depends on. Fixing an import path or a removed
  library alias is a deviation you must record with `add_note(kind="deviation")`, and you
  should prefer pinning an older library over editing code.
- **When it does not run, stop and say so.** Call `compare_claim(claim_id, could_not_run=True)`
  and write the report. "Could not run" with the blocking error is a useful result.
- **A shortened run never reproduces the full claim.** The tool marks it; do not describe it
  as a reproduction in your summary either.
- **One verdict per claim.** Do not shop for a favorable metric after seeing the results.
  Comparing a claim again (for example after the full run finishes) replaces the earlier
  verdict, and the report still lists the earlier one as superseded.
- Record anything you did not verify (checksums of downloaded data, GPU code paths, other
  claims) with `add_note(kind="not_checked")`.
- Long runs: `run_command` blocks until the command finishes or `timeout_seconds` passes. For
  runs longer than your client's tool timeout, use the CLI from a shell
  (`paper-repro run --timeout 7200 -- python train.py`), which records the same evidence.
