"""`report`: turn the evidence log into report.md and report.json."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from . import __version__
from .study import Study, StudyError
from .util import host_info, normalize_metric, now_iso

NOTE_KINDS = ("observation", "deviation", "not_checked", "blocker")


def add_note(study: Study, text: str, kind: str = "observation") -> dict:
    if kind not in NOTE_KINDS:
        raise StudyError(f"kind must be one of: {', '.join(NOTE_KINDS)}")
    if not text.strip():
        raise StudyError("Empty note.")
    return study.append("note", {"note_kind": kind, "text": text.strip()})


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(round(seconds)), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _num(x: Any) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.6g}"
    return str(x)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _key_packages(st: dict, env: dict | None) -> dict[str, str]:
    if not env:
        return {}
    pkgs = env.get("packages") or {}
    names: list[str] = []
    insp = st["inspect"] or {}
    for d in insp.get("dependency_files", []):
        p = d.get("parsed", {})
        for r in p.get("requirements", []) + p.get("pip", []) + p.get("dependencies", []):
            if isinstance(r, str):
                m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", r)
                if m:
                    names.append(m.group(1))
        for c in p.get("conda", []):
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", str(c).split("::")[-1])
            if m:
                names.append({"pytorch": "torch"}.get(m.group(1), m.group(1)))
    for x in env.get("extra", []) + env.get("readme_packages", []):
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", x)
        if m:
            names.append(m.group(1))
    out = {}
    for n in names:
        key = n.lower().replace("_", "-")
        for cand in (key, key.replace("-", "_"), n.lower()):
            if cand in pkgs:
                out[cand] = pkgs[cand]
                break
    return dict(sorted(out.items()))


def _not_checked(st: dict) -> list[str]:
    items: list[str] = []
    insp = st["inspect"] or {}
    compared = {c["claim"]["id"] for c in st["comparisons"]}
    others = [c for cid, c in st["claims"].items() if cid not in compared]
    if others:
        sample = ", ".join(
            f"{c['raw_metric']} {_num(c['value']) if c['value'] is not None else str(c['lo']) + '-' + str(c['hi'])}"
            f" ({c['source']}:{c['line']})"
            for c in others[:6]
        )
        more = f" and {len(others) - 6} more" if len(others) > 6 else ""
        items.append(
            f"{len(others)} other numbers found in the README were not compared: {sample}{more}."
        )
    for k in st["comparisons"]:
        if k["scope"] == "shortened":
            items.append(
                f"{k['claim']['raw_metric']} ({k['id']}) was measured on a shortened run only; "
                "the full-length run was not done."
            )
        if k.get("stats") and k["stats"]["n"] == 1:
            items.append(
                f"{k['claim']['raw_metric']} ({k['id']}) was measured once; seed-to-seed variation is unknown."
            )
    gpu = insp.get("gpu") or {}
    if gpu.get("code") or gpu.get("readme"):
        host = (st["envs"][-1].get("host") if st["envs"] else None) or host_info()
        items.append(
            f"The repo mentions GPUs or CUDA ({gpu.get('summary', '')}); this run was on "
            f"{host.get('os')} {host.get('machine')}"
            + (f" ({host['cpu']})" if host.get("cpu") else "")
            + ". Numerical results can differ across hardware and kernels."
        )
    if insp.get("downloads"):
        n = len(insp["downloads"])
        items.append(
            f"{n} data or weight download references were found; their checksums against the authors' "
            "copies were not verified unless a note below says so."
        )
    if not st["runs"]:
        items.append("No commands were run.")
    items.append(
        "Whether the code matches the method described in the paper was not checked; this report "
        "only compares the code's output with the stated number."
    )
    for n in st["notes"]:
        if n["note_kind"] == "not_checked":
            items.append(n["text"])
    return items


def build_report(study: Study) -> dict:
    st = study.state()
    insp = st["inspect"]
    if not insp:
        raise StudyError("Nothing to report: run `paper-repro inspect` first.")
    env = st["envs"][-1] if st["envs"] else None
    repo = insp["repo"]
    runs = list(st["runs"].values())
    deviations = []
    for e in st["envs"]:
        deviations.extend(f"[{e['id']}] {d}" for d in e.get("deviations", []))
    for r in runs:
        if r["scope"] in ("shortened", "smoke") and r.get("note"):
            deviations.append(f"[{r['id']}] {r['scope']} run: {r['note']}")
    deviations.extend(n["text"] for n in st["notes"] if n["note_kind"] == "deviation")
    verify = study.verify()
    measured_ids = {v.get("id") for k in st["comparisons"] for v in k.get("measured", [])}
    return {
        "tool": {"name": "paper-repro", "version": __version__},
        "generated_at": now_iso(),
        "repo": {
            "source": repo.get("source"),
            "url": repo.get("url") or repo.get("origin_path"),
            "commit": repo.get("commit"),
            "commit_date": repo.get("commit_date"),
            "ref_requested": repo.get("ref_requested"),
            "dirty": repo.get("dirty"),
        },
        "host": (env or {}).get("host") or host_info(),
        "environment": None
        if not env
        else {
            "id": env["id"],
            "status": env["status"],
            "python": env.get("python"),
            "uv": env.get("uv"),
            "requirements": env.get("requirements"),
            "extra": env.get("extra"),
            "unpinned": env.get("unpinned"),
            "lock": env.get("lock"),
            "key_packages": _key_packages(st, env),
            "failure": env.get("failure"),
            "steps": env.get("steps"),
        },
        "environment_attempts": len(st["envs"]),
        "commands": [
            {
                "id": r["id"],
                "command": r["command"],
                "scope": r["scope"],
                "seed": r.get("seed"),
                "note": r.get("note"),
                "exit_code": r["exit_code"],
                "timed_out": r["timed_out"],
                "wall_seconds": r["wall_seconds"],
                "peak_rss_mb": r.get("peak_rss_mb"),
                "started": r["started"],
                "stdout": {k: r["stdout"][k] for k in ("path", "bytes", "sha256")},
                "stderr": {k: r["stderr"][k] for k in ("path", "bytes", "sha256")},
                "files_written": r["files"]["written_count"],
            }
            for r in runs
        ],
        "comparisons": [
            {
                "id": k["id"],
                "verdict": k["verdict"],
                "scope": k["scope"],
                "counts_as_reproduction": k["counts_as_reproduction"],
                "headline": k["headline"],
                "claim": k["claim"],
                "measured": [
                    {
                        key: v.get(key)
                        for key in (
                            "id",
                            "selector",
                            "name",
                            "value",
                            "value_on_claim_scale",
                            "source",
                            "line",
                            "text",
                            "run",
                            "unsourced",
                        )
                        if v.get(key) is not None
                    }
                    for v in k["measured"]
                ],
                "stats": k.get("stats"),
                "tolerance": k.get("tolerance"),
                "tolerance_reason": k.get("tolerance_reason"),
                "blocking": k.get("blocking"),
                "reasoning": k["reasoning"],
            }
            for k in st["comparisons"]
        ],
        "deviations": deviations,
        "observations": [
            n["text"] for n in st["notes"] if n["note_kind"] in ("observation", "blocker")
        ],
        "not_checked": _not_checked(st),
        "claims_found": len(st["claims"]),
        "metrics_extracted": sum(len(m["values"]) for m in st["metrics"].values()),
        "measured_value_ids": sorted(i for i in measured_ids if i),
        "evidence": {
            "log": "evidence.jsonl",
            "entries": verify["entries"],
            "head_sha256": verify["head"],
            "chain_ok": verify["ok"],
            "problems": verify["problems"],
        },
    }


VERDICT_WORDS = {
    "reproduced": "Reproduced",
    "close": "Close",
    "not_reproduced": "Not reproduced",
    "could_not_run": "Could not run",
}


def _overall(rep: dict) -> str:
    ks = rep["comparisons"]
    if not ks:
        return "No verdict: no claim was compared."
    if len(ks) == 1:
        return ks[0]["headline"]
    counts: dict[str, int] = {}
    for k in ks:
        label = VERDICT_WORDS[k["verdict"]] + (
            " (shortened run)" if k["scope"] == "shortened" else ""
        )
        counts[label] = counts.get(label, 0) + 1
    return (
        f"{len(ks)} claims compared: "
        + ", ".join(f"{v} {k.lower()}" for k, v in counts.items())
        + "."
    )


def render_markdown(rep: dict) -> str:
    repo = rep["repo"]
    name = repo.get("url") or repo.get("source") or "repository"
    short = re.sub(r"^https?://(www\.)?github\.com/", "", name).removesuffix(".git")
    L: list[str] = []
    L.append(f"# Reproduction report: {short}")
    L.append("")
    L.append(f"**{_overall(rep)}**")
    L.append("")
    env = rep.get("environment") or {}
    host = rep["host"]
    os_name = {"Darwin": "macOS"}.get(host.get("os") or "", host.get("os"))
    host_s = f"{os_name} {host.get('os_version') or host.get('os_release')} {host.get('machine')}"
    if host.get("cpu"):
        host_s += f", {host['cpu']}"
    if host.get("memory_gb"):
        host_s += f", {host['memory_gb']} GB RAM"
    cmds = rep["commands"]
    total = sum(c["wall_seconds"] or 0 for c in cmds)
    ok = sum(1 for c in cmds if c["exit_code"] == 0 and not c["timed_out"])
    commit = repo.get("commit") or "unknown (not a git checkout)"
    L += [
        "| | |",
        "|---|---|",
        f"| Repository | {name} |",
        f"| Commit | `{commit}`"
        + (f" ({repo['commit_date'][:10]})" if repo.get("commit_date") else "")
        + " |",
        f"| Machine | {host_s} |",
        f"| Python | {env.get('python') or 'n/a'} |",
        f"| Commands | {len(cmds)} run, {ok} exited 0, {_dur(total)} total |",
        f"| Generated | {rep['generated_at'][:19].replace('T', ' ')} UTC by paper-repro {rep['tool']['version']} |",
        "",
    ]

    for k in rep["comparisons"]:
        c = k["claim"]
        L.append(f"## {VERDICT_WORDS[k['verdict']]}: {c['raw_metric']} ({k['id']})")
        L.append("")
        where = c["source"] + (f", line {c['line']}" if c.get("line") else "")
        if c.get("table_header") and c.get("text"):
            L.append(f"The claim, from the table at {where}:")
            L.append("")
            header = [h.strip() for h in c["table_header"].split(" | ")]
            L.append("| " + " | ".join(header) + " |")
            L.append("|" + "---|" * len(header))
            L.append(c["text"].strip())
        elif c.get("text"):
            L.append(f"The claim, from {where}:")
            L.append("")
            L.append(f"> {c['text']}")
        else:
            L.append(f"The claim is from {where}.")
        L.append("")
        if k["measured"]:
            L.append("| Value | On claim's scale | Run | Source |")
            L.append("|---|---|---|---|")
            for v in k["measured"]:
                src = v.get("source", "")
                if v.get("line"):
                    src += f":{v['line']}"
                text = f" `{_md_escape(v['text'][:120])}`" if v.get("text") else ""
                L.append(
                    f"| {_num(v['value'])} | {_num(v.get('value_on_claim_scale'))} | {v.get('run', 'n/a')} | {_md_escape(src)}{text} |"
                )
            L.append("")
        if k.get("blocking"):
            b = k["blocking"]
            L.append(f"Blocked at {b['kind']} {b['id']}: `{b.get('command')}`")
            L.append("")
            L.append("```")
            L.append((b.get("error") or "").strip()[-3000:])
            L.append("```")
            L.append("")
        L.append("How the verdict was reached:")
        L.append("")
        for r in k["reasoning"]:
            L.append(f"- {r}")
        L.append("")

    L.append("## Commands")
    L.append("")
    if cmds:
        L.append("| # | Command | Scope | Seed | Exit | Wall time | Peak memory |")
        L.append("|---|---|---|---|---|---|---|")
        for c in cmds:
            exit_s = "timeout" if c["timed_out"] else str(c["exit_code"])
            mem = f"{c['peak_rss_mb']:.0f} MB" if c.get("peak_rss_mb") is not None else "n/a"
            seed = "" if c.get("seed") is None else str(c["seed"])
            L.append(
                f"| {c['id']} | `{_md_escape(c['command'])}` | {c['scope']} | {seed} | {exit_s} | {_dur(c['wall_seconds'])} | {mem} |"
            )
        L.append("")
        noted = [c for c in cmds if c.get("note")]
        if noted:
            for c in noted:
                L.append(f"- {c['id']}: {c['note']}")
            L.append("")
        L.append(
            "Full stdout and stderr for each command are in `runs/<id>/`, with SHA-256 hashes recorded "
            "in `evidence.jsonl`. Commands ran inside the study's virtual environment, from the repo root."
        )
    else:
        L.append("No commands were run.")
    L.append("")

    L.append("## Environment")
    L.append("")
    if env:
        L.append(f"- Status: {env['status']}")
        L.append(f"- Python {env.get('python') or 'n/a'}, built with {env.get('uv') or 'uv'}")
        if env.get("requirements"):
            L.append(f"- Installed from: {', '.join(env['requirements'])}")
        if env.get("extra"):
            L.append(f"- Extra packages requested: {' '.join(env['extra'])}")
        if env.get("lock"):
            lk = env["lock"]
            L.append(
                f"- Resolved packages: {lk['packages']} (`{lk['path']}`, sha256 `{lk['sha256'][:16]}...`)"
            )
        if env.get("key_packages"):
            L.append(
                "- Key packages: " + ", ".join(f"{k} {v}" for k, v in env["key_packages"].items())
            )
        if env.get("failure"):
            f = env["failure"]
            L.append("")
            L.append(f"Setup failed at **{f['step']}**: `{f['command']}` (exit {f['exit_code']})")
            L.append("")
            L.append("```")
            L.append((f.get("error") or "").strip()[-3000:])
            L.append("```")
        if rep["environment_attempts"] > 1:
            L.append(
                f"- Environment attempts: {rep['environment_attempts']} (all recorded in the log)"
            )
    else:
        L.append("No environment was created.")
    L.append("")

    L.append("## Deviations from the authors' setup")
    L.append("")
    if rep["deviations"]:
        for d in rep["deviations"]:
            L.append(f"- {d}")
    else:
        L.append("None recorded.")
    L.append("")

    if rep["observations"]:
        L.append("## Notes")
        L.append("")
        for o in rep["observations"]:
            L.append(f"- {o}")
        L.append("")

    L.append("## What was not checked")
    L.append("")
    for item in rep["not_checked"]:
        L.append(f"- {item}")
    L.append("")

    ev = rep["evidence"]
    L.append("## Evidence")
    L.append("")
    L.append(
        f"`evidence.jsonl` holds {ev['entries']} hash-chained entries; head `{(ev['head_sha256'] or '')[:16]}...`. "
        f"Chain check: {'ok' if ev['chain_ok'] else 'FAILED: ' + '; '.join(ev['problems'])}. "
        "Run `paper-repro verify --study <dir>` to recheck the chain and the output-file hashes."
    )
    L.append("")
    return "\n".join(L)


BUNDLE_FILES = ("report.md", "report.json", "evidence.jsonl", "lock.txt", "inspect.json")


def write_report(study: Study, bundle: str | None = None) -> dict:
    rep = build_report(study)
    md = render_markdown(rep)
    (study.root / "report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (study.root / "report.md").write_text(md, encoding="utf-8")
    out = {
        "report_md": str(study.root / "report.md"),
        "report_json": str(study.root / "report.json"),
    }
    if bundle:
        dest = Path(bundle).expanduser().resolve()
        dest.mkdir(parents=True, exist_ok=True)
        for name in BUNDLE_FILES:
            src = study.root / name
            if src.exists():
                shutil.copy2(src, dest / name)
        if study.runs_dir.exists():
            shutil.copytree(study.runs_dir, dest / "runs", dirs_exist_ok=True)
        if (study.root / "env-inputs").exists():
            shutil.copytree(study.root / "env-inputs", dest / "env-inputs", dirs_exist_ok=True)
        out["bundle"] = str(dest)
    out["overall"] = _overall(rep)
    out["verdicts"] = [
        {"id": k["id"], "verdict": k["verdict"], "scope": k["scope"], "headline": k["headline"]}
        for k in rep["comparisons"]
    ]
    return out


def status(study: Study) -> dict:
    st = study.state()
    insp = st["inspect"] or {}
    return {
        "study": str(study.root),
        "repo": (insp.get("repo") or {}).get("url") or (insp.get("repo") or {}).get("source"),
        "commit": (insp.get("repo") or {}).get("commit"),
        "claims": len(st["claims"]),
        "envs": [
            {"id": e["id"], "status": e["status"], "python": e.get("python")} for e in st["envs"]
        ],
        "runs": [
            {
                "id": r["id"],
                "command": r["command"],
                "exit_code": r["exit_code"],
                "timed_out": r["timed_out"],
                "wall_seconds": r["wall_seconds"],
                "scope": r["scope"],
            }
            for r in st["runs"].values()
        ],
        "metrics": [
            {
                "id": m["id"],
                "values": len(m["values"]),
                "names": sorted({v["name"] for v in m["values"]})[:30],
            }
            for m in st["metrics"].values()
        ],
        "comparisons": [
            {"id": k["id"], "verdict": k["verdict"], "headline": k["headline"]}
            for k in st["comparisons"]
        ],
        "notes": len(st["notes"]),
    }


__all__ = [
    "add_note",
    "build_report",
    "render_markdown",
    "write_report",
    "status",
    "normalize_metric",
]
