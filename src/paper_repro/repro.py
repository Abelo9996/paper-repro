"""`repro`: one command from a paper (gallery slug, arXiv id or repo) to a verdict and a card.

It drives the same steps an agent would (inspect, paper, env, run, metrics, compare, report,
verify), each recorded in the study's evidence log, and ends in one of the verdicts with its
report and a shareable card. With a gallery recipe nothing is authored: the commit, Python,
environment, command, seeds, metric and claim are all pinned. Without one, `repro` gets as far
as it can on its own and stops with COULD NOT RUN and the exact reason, unless it is given a
command to run.
"""

from __future__ import annotations

import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .compare import REASONS, add_claim, compare_claim, verdict_label
from .envs import create_env
from .gallery import find_recipe, load_gallery, recipes_for_repo, repo_key
from .inspect_repo import inspect_repo
from .metrics import extract_metrics
from .paper import scan_paper
from .report import add_note, write_report
from .resolve import arxiv_id, resolve_arxiv
from .runner import run_command
from .study import Study, StudyError, slug_for, workspace_root

Progress = Callable[[str], None]
DEFAULT_TIMEOUT = 1800


def _free_name(ws: Path, base: str) -> str:
    """A study name not used yet: repro always starts a fresh study, so its log is one attempt."""
    if not (ws / base).exists():
        return base
    n = 2
    while (ws / f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


def _dur(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    m, sec = divmod(int(round(s)), 60)
    return f"{m}m {sec:02d}s" if m < 60 else f"{m // 60}h {m % 60:02d}m"


def _num(x: float) -> str:
    return f"{x:g}"


def _find_readme_claim(claims: list[dict], spec: dict) -> dict | None:
    for c in claims:
        if spec.get("line") is not None and c.get("line") != spec["line"]:
            continue
        if spec.get("range"):
            if [c.get("lo"), c.get("hi")] != list(spec["range"]):
                continue
        elif c.get("value") != spec.get("value"):
            continue
        return c
    return None


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9+]", "", (s or "").lower())


def _find_paper_claim(claims: list[dict], spec: dict) -> dict | None:
    for c in claims:
        if spec.get("table") and c.get("table") != spec["table"]:
            continue
        if spec.get("row") and _norm(c.get("row")) != _norm(spec["row"]):
            continue
        if spec.get("column") and _norm(c.get("column")) != _norm(spec["column"]):
            continue
        if c.get("value") != spec.get("value"):
            continue
        return c
    return None


def _gpu_only(insp: dict) -> bool:
    """CUDA-specific code with no device check or flag anywhere: it will not run on a CPU."""
    gpu = insp.get("gpu") or {}
    return bool(gpu.get("code")) and not gpu.get("availability_checks")


def _host_line(study: Study, recipe: dict | None) -> str:
    from .util import host_info

    st = study.state()
    host = (st["envs"][-1].get("host") if st["envs"] else None) or host_info()
    os_name = {"Darwin": "macOS"}.get(host.get("os") or "", host.get("os") or "")
    parts = [host.get("cpu") or host.get("machine") or "unknown CPU"]
    parts.append(f"{os_name} {host.get('os_version') or host.get('os_release') or ''}".strip())
    if host.get("memory_gb"):
        parts.append(f"{host['memory_gb']:g} GB RAM")
    if recipe and recipe.get("device") == "cpu":
        parts.append("CPU only")
    return ", ".join(parts)


def repro(
    target: str,
    *,
    workspace: str | None = None,
    name: str | None = None,
    seeds: int | None = None,
    command: str | None = None,
    metric: str | None = None,
    claim: str | None = None,
    authored: bool = False,
    python: str | None = None,
    timeout: float | None = None,
    make_card: bool = True,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Run the whole flow for `target` and return the verdict, paths and timings."""
    say = progress or (lambda _msg: None)
    t0 = time.monotonic()
    ws = workspace_root(workspace)
    entries = load_gallery()

    # 1. What to run: a recipe, a repo, or a paper whose repo has to be found.
    resolution: dict[str, Any] | None = None
    aid = arxiv_id(target)
    recipe = find_recipe(target, entries) if not aid else None
    repo: str
    if aid:
        cache = ws / ".arxiv" / f"{aid}.pdf"
        say(f"resolve  arXiv:{aid}: looking for the official code (arXiv page, then the PDF)")
        resolution = resolve_arxiv(aid, cache)
        if not resolution.get("repo"):
            raise StudyError(
                f"arXiv:{aid} ({resolution.get('title')}): no code repository is linked from "
                "the arXiv page or the paper, and GitHub search found none. Pass the repo "
                "instead: paper-repro repro <owner/name>."
            )
        repo = resolution["repo"]
        how = {
            "arxiv-page": "linked on the arXiv page",
            "paper-pdf": "linked in the paper",
            "github-search": "GitHub search, NOT stated by the authors",
        }[resolution["method"]]
        say(f"         {resolution.get('title')}")
        say(f"         -> {repo} ({how}; {resolution['evidence'][:140]})")
        matches = recipes_for_repo(repo, entries)
        recipe = next((r for r in matches if str(r.get("arxiv")) == aid), None) or (
            matches[0] if matches else None
        )
        others = [r for r in entries if str(r.get("arxiv")) == aid and r is not recipe]
        if others and not recipe:
            say(
                "         the gallery has a recipe for this paper on another repo: "
                + ", ".join(f"{r['slug']} ({r['repo']})" for r in others)
            )
    elif recipe:
        repo = recipe["repo"]
    else:
        if not repo_key(target) and not Path(target).expanduser().exists():
            raise StudyError(
                f"{target!r} is not a gallery slug, an arXiv id or a repository. "
                "See `paper-repro gallery` for slugs."
            )
        repo = target
    if recipe and (command or metric or claim):
        raise StudyError(
            f"{recipe['slug']} has a gallery recipe; --command, --metric and --claim are for "
            "repos without one. Run the steps by hand (paper-repro inspect ...) to change it."
        )

    base = name or (recipe["slug"] if recipe else slug_for(repo))
    study_name = _free_name(ws, base)
    say(
        f"inspect  {repo}"
        + (f" @ {recipe['commit'][:7]}" if recipe and recipe.get("commit") else "")
        + (f" (gallery recipe {recipe['slug']})" if recipe else " (no gallery recipe)")
    )
    insp = inspect_repo(repo, ref=(recipe or {}).get("commit"), name=study_name, workspace=str(ws))
    study = Study(Path(insp["study"]))
    commit = insp["repo"].get("commit")
    study.append(
        "repro",
        {
            "target": target,
            "recipe": recipe,
            "resolution": resolution,
            "title": (recipe or {}).get("title") or (resolution or {}).get("title"),
            "verify_with": f"uvx paper-repro repro {recipe['slug'] if recipe else target}",
        },
    )
    say(f"         study {study.root}")
    say(f"         commit {commit}, {len(insp['claims'])} numbers in the README")

    def finish(k: dict | None, why_no_verdict: str | None = None) -> dict[str, Any]:
        wall = time.monotonic() - t0
        st = study.state()
        run_wall = sum(
            r["wall_seconds"] for r in st["runs"].values() if r["scope"] in ("full", "smoke")
        )
        study.append(
            "repro_done",
            {"wall_seconds": round(wall, 1), "run_wall_seconds": round(run_wall, 1)},
        )
        rep = write_report(study)
        say(f"report   {rep['report_md']}")
        v = study.verify()
        say(
            f"verify   {'ok' if v['ok'] else 'FAILED'}: {v['entries']} hash-chained entries, "
            f"head {(v['head'] or '')[:16]}"
        )
        out: dict[str, Any] = {
            "study": str(study.root),
            "target": target,
            "recipe": recipe["slug"] if recipe else None,
            "repo": repo,
            "commit": commit,
            "resolution": resolution,
            "verdict": k["verdict"] if k else None,
            "label": verdict_label(k) if k else "NO VERDICT",
            "headline": k["headline"] if k else why_no_verdict,
            "comparison": k["id"] if k else None,
            "wall_seconds": round(wall, 1),
            "run_wall_seconds": round(run_wall, 1),
            "report_md": rep["report_md"],
            "report_json": rep["report_json"],
            "verify": v,
        }
        if make_card:
            from .card import write_card

            out["card"] = write_card(study)
        return out

    # 2. The claim.
    claim_entry: dict | None = None
    spec = (recipe or {}).get("claim") or {}
    paper_id = (recipe or {}).get("arxiv") or spec.get("arxiv") or aid
    if not paper_id and not recipe:
        links = insp.get("papers") or []
        paper_id = links[0]["arxiv"] if links else None
    paper_claims: list[dict] = []
    if paper_id and (not recipe or spec.get("source") == "paper"):
        cached = ws / ".arxiv" / f"{paper_id}.pdf"
        dest = study.root / "paper" / f"arxiv-{paper_id}.pdf"
        if cached.exists() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached, dest)
        try:
            pe = scan_paper(study, paper_id)
            paper_claims = pe["claims"]
            say(f"paper    arXiv:{paper_id}: {len(paper_claims)} numbers read")
        except StudyError as exc:
            say(f"paper    arXiv:{paper_id}: not read ({exc})")
    if recipe:
        src = spec["source"]
        if src == "readme":
            claim_entry = _find_readme_claim(insp["claims"], spec)
        elif src == "paper":
            claim_entry = _find_paper_claim(paper_claims, spec)
        if claim_entry is None:
            # The recipe states the claim and where it is; record it as such. A README or paper
            # cell the extractor did not reach is still the authors' number.
            rng = spec.get("range")
            where = spec.get("where") or (
                f"{'README' if src == 'readme' else 'arXiv:' + str(paper_id)}"
                + (f" {spec['table']}" if spec.get("table") else "")
            )
            e = add_claim(
                study,
                metric=spec.get("metric") or recipe["metric"]["name"],
                value=None if rng else spec["value"],
                lo=rng[0] if rng else None,
                hi=rng[1] if rng else None,
                percent=bool(spec.get("percent")),
                source=where,
                text=spec.get("text"),
                value_text=spec.get("value_text"),
            )
            claim_entry = e["claim"]
            if src != "manual":
                add_note(
                    study,
                    f"The recipe's claim was not found by the {src} reader, so it was recorded "
                    f"from the recipe: {where}.",
                    "observation",
                )
    elif claim:
        st = study.state()
        claim_entry = st["claims"].get(claim)
        if not claim_entry:
            raise StudyError(
                f"Unknown claim {claim!r}. Known: {', '.join(list(st['claims'])[:30])}"
            )
    if claim_entry:
        c = claim_entry
        val = c["value_text"] if c.get("value") is not None else f"{c['lo_text']} to {c['hi_text']}"
        pm = f" ± {c['plus_minus']:g}" if c.get("plus_minus") else ""
        cell = " | ".join(x for x in (c.get("row"), c.get("column")) if x)
        say(
            f"claim    {c['id']}: {c['raw_metric']} = {val}{pm}{'%' if c.get('percent') else ''}"
            + (f" [{cell}]" if cell else "")
            + f" ({c['source']}"
            + (f":{c['line']}" if c.get("line") else "")
            + (f", {c['table']}" if c.get("table") else "")
            + ")"
        )

    def could_not_run(reason: str | None, blocking: str | None, text: str) -> dict[str, Any]:
        add_note(study, text, "blocker")
        target_claim = claim_entry
        if target_claim is None:
            st = study.state()
            table = [c for c in st["claims"].values() if c.get("confidence") == "high"]
            pool = [c for c in st["claims"].values() if c["id"].startswith("c")] or table
            if not pool:
                say(
                    f"verdict  NO VERDICT: {text} (and no claimed number was found to attach it to)"
                )
                return finish(None, text)
            target_claim = pool[0]
            add_note(
                study,
                f"No claim was chosen; the verdict is attached to the first one found "
                f"({target_claim['id']}). Pass --claim to choose.",
                "observation",
            )
        k = compare_claim(
            study,
            claim_id=target_claim["id"],
            could_not_run=True,
            blocking=blocking,
            reason=reason,
        )
        say(f"verdict  {verdict_label(k)}: {text}")
        return finish(k)

    # 3. Feasibility before installing anything, when there is no recipe or command.
    if not recipe and not command:
        if _gpu_only(insp):
            gpu = insp["gpu"]
            return could_not_run(
                "gpu_required",
                None,
                f"The code calls CUDA directly ({gpu['code'][0]['source']}: "
                f"`{gpu['code'][0]['text'][:80]}`) and has no device check or flag, so it needs "
                "an NVIDIA GPU; there is no CPU path to run.",
            )
        cmds = [c["command"] for c in insp.get("readme_commands") or []]
        listed = "; ".join(f"`{c}`" for c in cmds[:5]) or "none"
        return could_not_run(
            "no_command",
            None,
            "No gallery recipe for this repo and no --command given, so nothing was run. "
            f"README commands found: {listed}. Run one with --command (and --claim, --metric), "
            "or ask your agent to work through it with the paper-repro skill.",
        )

    # 4. Environment.
    env_spec = (recipe or {}).get("env") or {}
    py = python or (recipe or {}).get("python")
    say(f"env      building with uv (python {py or 'from the repo'})")
    e = create_env(
        study,
        python=py,
        requirements=env_spec.get("requirements"),
        extra=env_spec.get("extra"),
        unpin_versions=env_spec.get("unpin", False),
        from_readme=env_spec.get("from_readme", False),
        install_project=env_spec.get("install_project", False),
        no_deps_file=env_spec.get("no_deps_file", False),
    )
    if e["status"] != "ok":
        f = e.get("failure") or {}
        return could_not_run(
            "broken_deps",
            e["id"],
            f"The environment did not build: {f.get('step')} failed (`{f.get('command')}`).",
        )
    lock = e.get("lock") or {}
    say(f"         {e['id']} ok: python {e.get('python')}, {lock.get('packages', '?')} packages")

    # 5. Setup and runs.
    run_timeout = timeout or (recipe or {}).get("timeout") or DEFAULT_TIMEOUT
    run_env = {k: str(v) for k, v in ((recipe or {}).get("env_vars") or {}).items()}
    for cmd in (recipe or {}).get("setup") or []:
        r = run_command(study, cmd, scope="setup", timeout=run_timeout, env=run_env)
        say(f"setup    {r['id']}: {cmd} -> exit {r['exit_code']} in {_dur(r['wall_seconds'])}")
        if r["exit_code"] != 0 or r["timed_out"]:
            return could_not_run(None, r["id"], f"Setup step {r['id']} failed: `{cmd}`.")
    cmd_template = command or recipe["command"]
    seed_list = (recipe or {}).get("seeds") or [None]
    if seeds is not None:
        seed_list = seed_list[: max(1, seeds)]
    full_runs = []
    for seed in seed_list:
        cmd = cmd_template.replace("{seed}", str(seed)) if seed is not None else cmd_template
        r = run_command(
            study,
            cmd,
            env=run_env,
            seed=seed,
            scope="full",
            timeout=run_timeout,
            authored=authored or bool((recipe or {}).get("authored")),
            note=(recipe or {}).get("note"),
        )
        status = "timed out" if r["timed_out"] else f"exit {r['exit_code']}"
        say(
            f"run      {r['id']}{f' seed {seed}' if seed is not None else ''}: {status} in "
            f"{_dur(r['wall_seconds'])}, peak memory {r.get('peak_rss_mb')} MB"
            + (" [command written by the agent]" if r.get("origin") == "authored" else "")
        )
        if r["exit_code"] != 0 or r["timed_out"]:
            return could_not_run(None, r["id"], f"Run {r['id']} failed: `{cmd}`.")
        full_runs.append(r["id"])

    # 6. Metrics and verdict.
    if claim_entry is None:
        return could_not_run(
            "other", None, "The command ran, but no claim was given to compare it with (--claim)."
        )
    mspec = (recipe or {}).get("metric") or {}
    mname = metric or mspec.get("name") or claim_entry["metric"]
    m = extract_metrics(study, run_ids=full_runs, names=[mname], files=mspec.get("files"))
    if not m["values"]:
        return could_not_run(
            "no_metric",
            full_runs[-1],
            f"The runs finished but printed no {mname!r} value to compare.",
        )
    vals = [s for s in m["summary"]]
    say(
        f"metrics  {m['id']}: "
        + ", ".join(
            f"{s['name']} last {_num(s['last']['value'])} ({s['count']} values)" for s in vals
        )
    )
    tol = (recipe or {}).get("tolerance") or {}
    k = compare_claim(
        study,
        claim_id=claim_entry["id"],
        measured=[f"{m['id']}:{mname}:{mspec.get('select', 'last')}@each"],
        tol=tol.get("abs"),
        rel_tol=tol.get("rel"),
        close_tol=tol.get("close_abs"),
        why=tol.get("why"),
    )
    for item in (recipe or {}).get("not_checked") or []:
        add_note(study, item, "not_checked")
    for item in (recipe or {}).get("deviations") or []:
        add_note(study, item, "deviation")
    say(f"verdict  {verdict_label(k)}")
    say(f"         {k['headline']}")
    return finish(k)


__all__ = ["repro", "REASONS"]
