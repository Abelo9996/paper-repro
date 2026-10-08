"""Command line interface. Every subcommand accepts --json for machine-readable output."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, guide
from .study import StudyError, resolve_study

EPILOG = """\
typical flow (each step prints what to do next):
  paper-repro inspect https://github.com/owner/repo     clone it, list the numbers it claims
  paper-repro paper                                     optional: numbers from the linked arXiv paper
  paper-repro env                                       build an isolated env from its dependencies
  paper-repro run --scope smoke -- python train.py --epochs 1
  paper-repro run -- python train.py                    the configuration the claim refers to
  paper-repro metrics                                   pull numbers out of the latest run
  paper-repro compare --claim c3 --measured m1:accuracy:last
  paper-repro report                                    write report.md with the verdict and evidence

studies live in ./paper-repro-runs (or $PAPER_REPRO_HOME); later steps act on the last inspected repo.
"""


def _p(args, data, human) -> None:
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(human(data))


def cmd_inspect(args) -> int:
    from .inspect_repo import inspect_repo

    e = inspect_repo(
        args.source, ref=args.ref, name=args.name, workspace=args.workspace, study_dir=args.study
    )

    def human(e) -> str:
        r = e["repo"]
        lines = [
            f"study: {e['study']}",
            f"repo: {r.get('url') or r.get('origin_path')} @ {r.get('commit') or 'no commit'}",
            f"language: {e['primary_language']} | files: {e['size']['files']}",
            "dependency files: "
            + (", ".join(f"{d['path']} ({d['kind']})" for d in e["dependency_files"]) or "none"),
            f"python: {e['suggested_python']['version']} ({e['suggested_python']['reason']})",
            f"gpu: {e['gpu']['summary']}",
            f"downloads referenced: {len(e['downloads'])}",
            "entry points: " + (", ".join(p["path"] for p in e["entry_points"][:8]) or "none"),
            "README commands:" + ("" if e["readme_commands"] else " none"),
        ]
        lines += [f"  {c['source']}: {c['command']}" for c in e["readme_commands"][:12]]
        lines.append(f"claimed numbers ({len(e['claims'])}):")
        for c in e["claims"][:25]:
            val = c["value_text"] if c["value"] is not None else f"{c['lo_text']} to {c['hi_text']}"
            pct = "%" if c["percent"] else ""
            row = f" [{c['row']}]" if c.get("row") else ""
            lines.append(
                f"  {c['id']}: {c['raw_metric']} = {val}{pct}{row}  ({c['source']}:{c['line']})"
            )
        if len(e["claims"]) > 25:
            lines.append(f"  ... {len(e['claims']) - 25} more (use --json)")
        for p in e.get("papers") or []:
            lines.append(f"paper linked: arXiv:{p['arxiv']} ({p['source']})")
        lines.append(f"next: {e['next']}")
        return "\n".join(lines)

    e["next"] = guide.after_inspect(e)
    _p(args, e, human)
    return 0


def cmd_env(args) -> int:
    from .envs import create_env

    study = resolve_study(args.study, args.workspace)
    e = create_env(
        study,
        python=args.python,
        requirements=args.requirements,
        install_project=args.install_project,
        extra=args.extra,
        unpin_versions=args.unpin,
        no_deps_file=args.no_deps_file,
        from_readme=args.from_readme,
        timeout=args.timeout,
    )

    def human(e) -> str:
        lines = [f"{e['id']}: {e['status']} | python {e.get('python')} | {e.get('uv')}"]
        for s in e["steps"]:
            if "skipped" in s:
                lines.append(f"  - {s['step']}: skipped ({s['skipped']})")
            else:
                lines.append(f"  - {s['step']}: exit {s['exit_code']} in {s['wall_seconds']}s")
        if e.get("lock"):
            lines.append(
                f"lock: {e['lock']['packages']} packages, sha256 {e['lock']['sha256'][:16]}"
            )
        for d in e["deviations"]:
            lines.append(f"deviation: {d}")
        if e.get("failure"):
            lines.append(f"FAILED at {e['failure']['step']}: {e['failure']['command']}")
            lines.append(e["failure"]["error"])
        for h in e.get("hints") or []:
            if h != e["next"]:
                lines.append(f"hint: {h}")
        lines.append(f"next: {e['next']}")
        return "\n".join(lines)

    e["next"] = guide.after_env(e)
    _p(args, e, human)
    return 0 if e["status"] == "ok" else 1


def _parse_env(pairs: list[str] | None) -> dict[str, str]:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise StudyError(f"--env expects KEY=VALUE, got {p!r}")
        k, v = p.split("=", 1)
        out[k] = v
    return out


def cmd_run(args) -> int:
    from .runner import run_command

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise StudyError("No command given. Usage: paper-repro run -- python train.py")
    cmd = command[0] if len(command) == 1 else " ".join(_shell_quote(c) for c in command)
    study = resolve_study(args.study, args.workspace)
    e = run_command(
        study,
        cmd,
        timeout=args.timeout,
        cpu_seconds=args.cpu_seconds,
        memory_mb=args.memory_mb,
        env=_parse_env(args.env),
        seed=args.seed,
        scope=args.scope,
        note=args.note,
        use_env=not args.no_env,
    )

    def human(e) -> str:
        status = "TIMED OUT" if e["timed_out"] else f"exit {e['exit_code']}"
        lines = [
            f"{e['id']}: {status} in {e['wall_seconds']:.1f}s, peak memory {e.get('peak_rss_mb')} MB, "
            f"{e['files']['written_count']} files written",
            f"stdout: {e['stdout']['path']} ({e['stdout']['bytes']} bytes)",
            f"stderr: {e['stderr']['path']} ({e['stderr']['bytes']} bytes)",
        ]
        if e["stdout"]["tail"]:
            lines += ["--- stdout (tail) ---", e["stdout"]["tail"]]
        if e["stderr"]["tail"]:
            lines += ["--- stderr (tail) ---", e["stderr"]["tail"]]
        lines.append(f"next: {e['next']}")
        return "\n".join(lines)

    e["next"] = guide.after_run(e)
    _p(args, e, human)
    return 0 if e["exit_code"] == 0 and not e["timed_out"] else 1


def _shell_quote(s: str) -> str:
    import shlex

    return shlex.quote(s)


def cmd_metrics(args) -> int:
    from .metrics import extract_metrics

    study = resolve_study(args.study, args.workspace)
    e = extract_metrics(study, run_ids=args.run, files=args.file, names=args.name)

    def human(e) -> str:
        lines = [f"{e['id']}: {len(e['values'])} values from {len(e['sources'])} sources"]
        for s in e["summary"]:
            if s["count"] == 1:
                lines.append(f"  {s['name']}: {s['last']['value']}  [{s['last']['id']}]")
            else:
                lines.append(
                    f"  {s['name']}: {s['count']} values, last {s['last']['value']} [{s['last']['id']}], "
                    f"min {s['min']['value']} [{s['min']['id']}], max {s['max']['value']} [{s['max']['id']}]"
                )
        lines.append(f"next: {e['next']}")
        return "\n".join(lines)

    e["next"] = guide.after_metrics(e)
    _p(args, e, human)
    return 0


def cmd_claim(args) -> int:
    from .compare import add_claim

    study = resolve_study(args.study, args.workspace)
    lo = hi = None
    if args.range:
        lo, hi = args.range
    e = add_claim(
        study,
        metric=args.metric,
        value=args.value,
        lo=lo,
        hi=hi,
        percent=args.percent,
        source=args.source,
        text=args.text,
    )
    _p(
        args,
        e,
        lambda e: (
            f"recorded claim {e['claim']['id']}: {e['claim']['raw_metric']} ({e['claim']['source']})"
        ),
    )
    return 0


def cmd_paper(args) -> int:
    from .paper import scan_paper

    study = resolve_study(args.study, args.workspace)
    e = scan_paper(study, args.source)
    e["next"] = guide.after_paper(e)

    def human(e) -> str:
        p = e["paper"]
        lines = [
            f"paper: {p['label']} ({p['pages']} pages, {p['characters']} characters of text)",
            f"file: {p['file']['path']} sha256 {p['file']['sha256'][:16]}",
            f"text: {p['text_path']}",
        ]
        if p.get("warning"):
            lines.append(f"warning: {p['warning']}")
        lines.append(f"claimed numbers ({len(e['claims'])}):")
        shown = e["claims"] if args.all else e["claims"][:40]
        for c in shown:
            val = c["value_text"] if c["value"] is not None else f"{c['lo_text']} to {c['hi_text']}"
            pct = "%" if c["percent"] else ""
            pm = f" ± {c['plus_minus']:g}" if c.get("plus_minus") else ""
            cell = " | ".join(x for x in (c.get("row"), c.get("column")) if x)
            cell = f" [{cell}]" if cell else ""
            lines.append(f"  {c['id']}: {c['raw_metric']} = {val}{pm}{pct}{cell}  ({c['source']})")
        if len(e["claims"]) > len(shown):
            lines.append(f"  ... {len(e['claims']) - len(shown)} more (use --all or --json)")
        lines.append(f"next: {e['next']}")
        return "\n".join(lines)

    _p(args, e, human)
    return 0


def cmd_compare(args) -> int:
    from .compare import compare_claim

    study = resolve_study(args.study, args.workspace)
    e = compare_claim(
        study,
        claim_id=args.claim,
        measured=args.measured,
        unsourced=args.value,
        tol=args.tol,
        rel_tol=args.rel_tol,
        close_tol=args.close_tol,
        close_rel_tol=args.close_rel_tol,
        why=args.why,
        could_not_run=args.could_not_run,
        blocking=args.blocking,
    )

    def human(e) -> str:
        return "\n".join(
            [
                f"{e['id']}: {e['verdict'].replace('_', ' ').upper()}",
                e["headline"],
                *[f"  - {r}" for r in e["reasoning"]],
                f"next: {e['next']}",
            ]
        )

    e["next"] = guide.after_compare(e)
    _p(args, e, human)
    return 0


def cmd_note(args) -> int:
    from .report import add_note

    study = resolve_study(args.study, args.workspace)
    e = add_note(study, " ".join(args.text), args.kind)
    _p(args, e, lambda e: f"noted ({e['note_kind']}): {e['text']}")
    return 0


def cmd_report(args) -> int:
    from .report import write_report

    study = resolve_study(args.study, args.workspace)
    out = write_report(study, bundle=args.bundle)

    def human(o) -> str:
        lines = [o["overall"], f"wrote {o['report_md']}", f"wrote {o['report_json']}"]
        if o.get("bundle"):
            lines.append(f"bundle: {o['bundle']}")
        return "\n".join(lines)

    out["next"] = guide.after_report(study)

    _p(args, out, human)
    return 0


def cmd_status(args) -> int:
    from .report import status

    study = resolve_study(args.study, args.workspace)
    s = status(study)

    def human(s) -> str:
        lines = [
            f"study: {s['study']}",
            f"repo: {s['repo']} @ {s['commit']}",
            f"claims: {s['claims']}",
        ]
        lines += [f"env {e['id']}: {e['status']} (python {e['python']})" for e in s["envs"]]
        lines += [
            f"run {r['id']}: exit {r['exit_code']}{' TIMEOUT' if r['timed_out'] else ''} "
            f"{r['wall_seconds']:.1f}s [{r['scope']}] {r['command']}"
            for r in s["runs"]
        ]
        lines += [
            f"metrics {m['id']}: {m['values']} values ({', '.join(m['names'][:8])})"
            for m in s["metrics"]
        ]
        lines += [f"compare {k['id']}: {k['headline']}" for k in s["comparisons"]]
        return "\n".join(lines)

    _p(args, s, human)
    return 0


def cmd_verify(args) -> int:
    study = resolve_study(args.study, args.workspace)
    v = study.verify()
    _p(
        args,
        v,
        lambda v: (
            f"ok: {v['entries']} entries, head {v['head']}"
            if v["ok"]
            else "FAILED\n" + "\n".join(v["problems"])
        ),
    )
    return 0 if v["ok"] else 1


def cmd_mcp(args) -> int:
    from .mcp_server import serve

    serve()
    return 0


def cmd_setup(args) -> int:
    from .agent_setup import run_setup

    project = Path(args.project).resolve() if args.project else None
    plan = run_setup(apply=False, project_dir=project)
    lines = [
        "Detected: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in plan["detected"].items())
    ]
    for a in plan["actions"]:
        state = "will do" if a["needed"] else a.get("result", "nothing to do")
        lines.append(f"  [{a['agent']}] {a['action']}: {a['target']} ({state})")
    if not any(a["needed"] for a in plan["actions"]):
        if not any(plan["detected"].values()):
            lines.append(
                "No agent found (looked for the claude CLI or ~/.claude, ~/.codex, ~/.cursor). "
                "Register the server by hand: `uvx paper-repro mcp` over stdio."
            )
        _p(args, plan, lambda _: "\n".join([*lines, "Nothing to change."]))
        return 0
    apply = args.yes
    if not apply and not args.json and sys.stdin.isatty():
        print("\n".join(lines))
        apply = input("Apply these changes? [y/N] ").strip().lower() in ("y", "yes")
        lines = []
    if not apply:
        _p(args, plan, lambda _: "\n".join([*lines, "Dry run. Re-run with --yes to apply."]))
        return 0
    done = run_setup(apply=True, project_dir=project)
    out = []
    for a in done["actions"]:
        if a.get("error"):
            out.append(f"  [{a['agent']}] {a['action']}: ERROR {a['error']}")
        elif a.get("result"):
            out.append(f"  [{a['agent']}] {a['action']}: {a['result']}")
    done["next"] = SETUP_NEXT
    _p(args, done, lambda _: "\n".join([*lines, *out, "", SETUP_NEXT]))
    return 0 if not any(a.get("error") for a in done["actions"]) else 1


SETUP_NEXT = (
    "Done. Start a new agent session (restart Claude Code, Codex or Cursor so it loads the "
    "server), then ask, for example:\n"
    '  "Does github.com/karpathy/nanoGPT reproduce the loss of 1.88 its README claims for the '
    'CPU run?"'
)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print JSON instead of text")
    common.add_argument(
        "--study", help="study directory (default: the current study in the workspace)"
    )
    common.add_argument(
        "--workspace", help="workspace root (default: $PAPER_REPRO_HOME or ./paper-repro-runs)"
    )

    p = argparse.ArgumentParser(
        prog="paper-repro",
        description="Get a paper's code running and check whether its headline number reproduces.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"paper-repro {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser(
        "inspect", parents=[common], help="clone or copy a repo and describe how to run it"
    )
    s.add_argument("source", help="git URL, owner/repo on GitHub, or a local path")
    s.add_argument("--ref", help="branch, tag or commit to check out")
    s.add_argument("--name", help="study name (default: derived from the repo)")
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser(
        "env", parents=[common], help="create an isolated uv environment for the repo"
    )
    s.add_argument(
        "--python", help="Python version (default: the version the repo asks for, else 3.11)"
    )
    s.add_argument(
        "-r",
        "--requirements",
        action="append",
        help="requirements or environment.yml file (repeatable)",
    )
    s.add_argument(
        "--install-project", action="store_true", help="also `pip install -e` the repo itself"
    )
    s.add_argument("--extra", nargs="+", help="extra packages to install (recorded as a deviation)")
    s.add_argument(
        "--unpin", action="store_true", help="drop version pins (recorded as a deviation)"
    )
    s.add_argument(
        "--no-deps-file", action="store_true", help="do not auto-select a dependency file"
    )
    s.add_argument(
        "--from-readme",
        action="store_true",
        help="install the packages from the README's `pip install` line",
    )
    s.add_argument(
        "--timeout", type=float, default=3600, help="seconds per install step (default 3600)"
    )
    s.set_defaults(func=cmd_env)

    s = sub.add_parser("run", parents=[common], help="run a command in the repo env and record it")
    s.add_argument("command", nargs=argparse.REMAINDER, help="the command, after --")
    s.add_argument(
        "--timeout", type=float, default=3600, help="wall-clock limit in seconds (default 3600)"
    )
    s.add_argument("--cpu-seconds", type=int, help="CPU-time limit per process (POSIX)")
    s.add_argument("--memory-mb", type=int, help="address-space limit (enforced on Linux only)")
    s.add_argument("--env", action="append", metavar="KEY=VALUE", help="extra environment variable")
    s.add_argument(
        "--seed", type=int, help="seed label for this run (also exported as PAPER_REPRO_SEED)"
    )
    s.add_argument(
        "--scope",
        choices=["full", "shortened", "smoke", "setup"],
        default="full",
        help="full: the configuration the claim refers to; shortened: fewer epochs/steps/data; "
        "smoke: does it start at all; setup: data download or preprocessing",
    )
    s.add_argument("--note", help="what this run is, and for shortened runs what was cut")
    s.add_argument("--no-env", action="store_true", help="run without activating the study env")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser(
        "metrics", parents=[common], help="extract metric values from run output or files"
    )
    s.add_argument("--run", action="append", help="run id (repeatable; default: the latest run)")
    s.add_argument(
        "--file", action="append", help="file to read, relative to the repo (repeatable)"
    )
    s.add_argument("--name", action="append", help="only keep these metric names (repeatable)")
    s.set_defaults(func=cmd_metrics)

    s = sub.add_parser(
        "paper",
        parents=[common],
        help="find the numbers the paper claims (arXiv PDF or a local PDF or text file)",
        description="Download the paper from arXiv (or read a local PDF or text file), save its "
        "text, and record the numbers it claims as p1, p2, ... Results tables are read "
        "heuristically and marked low confidence: check the quoted row before using one.",
    )
    s.add_argument(
        "source",
        nargs="?",
        help="arXiv id or URL, or a local PDF/text path (default: the arXiv paper the README links)",
    )
    s.add_argument("--all", action="store_true", help="list every claim, not the first 40")
    s.set_defaults(func=cmd_paper)

    s = sub.add_parser("claim", parents=[common], help="record a claim the README scan missed")
    s.add_argument("--metric", required=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--value", type=float)
    g.add_argument("--range", type=float, nargs=2, metavar=("LO", "HI"))
    s.add_argument("--percent", action="store_true", help="the value is a percentage")
    s.add_argument(
        "--source", required=True, help="where it is stated, e.g. 'paper Table 2' or README.md:40"
    )
    s.add_argument("--text", help="the sentence or table row, quoted")
    s.set_defaults(func=cmd_claim)

    s = sub.add_parser(
        "compare", parents=[common], help="compare measured values with a claim; give a verdict"
    )
    s.add_argument("--claim", required=True, help="claim id from inspect (c3) or claim (u1)")
    s.add_argument(
        "--measured",
        action="append",
        help="metric selector: m2.17 or m2:val_loss:last (repeatable, one per run)",
    )
    s.add_argument(
        "--value",
        type=float,
        action="append",
        help="a value typed in by hand (flagged as unsourced)",
    )
    s.add_argument("--tol", type=float, help="absolute tolerance")
    s.add_argument("--rel-tol", type=float, help="relative tolerance (default 0.01)")
    s.add_argument(
        "--close-tol", type=float, help="absolute width of the 'close' band (default 3x tolerance)"
    )
    s.add_argument("--close-rel-tol", type=float, help="relative width of the 'close' band")
    s.add_argument("--why", help="why this tolerance is appropriate")
    s.add_argument(
        "--could-not-run", action="store_true", help="record that no number could be measured"
    )
    s.add_argument("--blocking", help="env or run id that blocked (default: the latest failure)")
    s.set_defaults(func=cmd_compare)

    s = sub.add_parser(
        "note", parents=[common], help="record an observation, deviation or unchecked item"
    )
    s.add_argument("text", nargs="+")
    s.add_argument(
        "--kind",
        default="observation",
        choices=["observation", "deviation", "not_checked", "blocker"],
    )
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("report", parents=[common], help="write report.md and report.json")
    s.add_argument(
        "--bundle", help="also copy the shareable evidence (no repo, no env) to this directory"
    )
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("status", parents=[common], help="show what the study has recorded so far")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser(
        "verify", parents=[common], help="check the evidence log's hash chain and output hashes"
    )
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("mcp", help="run the MCP server over stdio")
    s.set_defaults(func=cmd_mcp, json=False)

    s = sub.add_parser(
        "setup", help="register the MCP server and skill with Claude Code, Codex and Cursor"
    )
    s.add_argument("--yes", action="store_true", help="apply without asking")
    s.add_argument("--json", action="store_true")
    s.add_argument(
        "--project", help="write a project .mcp.json in this directory instead of user scope"
    )
    s.set_defaults(func=cmd_setup)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except StudyError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
