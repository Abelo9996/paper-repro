"""The gallery: papers whose official code was run on a CPU laptop with a stored recipe.

A recipe pins everything `repro` needs so that nobody has to author anything: the repo and
commit, the Python version, how to build the environment, setup steps, the exact command (with
the seeds to run), which metric to read and which claim to compare it with. Each entry also
records what happened when it was vetted, measured on a named machine, whatever the verdict.

The data lives in gallery.yaml next to this file and ships in the wheel.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .study import StudyError

GALLERY_FILE = Path(__file__).parent / "data" / "gallery.yaml"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CLAIM_SOURCES = ("readme", "paper", "manual")
VERDICTS = (
    "reproduced",
    "close",
    "not_reproduced",
    "reimplemented",
    "inconclusive",
    "could_not_run",
)


def gallery_path() -> Path:
    """$PAPER_REPRO_GALLERY replaces the shipped gallery (tests, or a private gallery)."""
    env = os.environ.get("PAPER_REPRO_GALLERY")
    return Path(env).expanduser() if env else GALLERY_FILE


def load_gallery(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or gallery_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("papers") or []
    problems = [f"{e.get('slug', '?')}: {p}" for e in entries for p in validate_recipe(e)]
    if problems:
        raise StudyError(f"Invalid gallery {path}:\n" + "\n".join(problems))
    return entries


def validate_recipe(r: dict[str, Any]) -> list[str]:
    """Problems with one recipe, as sentences. An empty list means it is usable."""
    out: list[str] = []

    def need(key: str, kind: type | tuple[type, ...], where: dict = r, label: str = "") -> Any:
        v = where.get(key)
        if not isinstance(v, kind):
            out.append(f"{label or key} must be {getattr(kind, '__name__', kind)}")
        return v

    slug = need("slug", str)
    if isinstance(slug, str) and not SLUG_RE.match(slug):
        out.append("slug must be lowercase letters, digits and hyphens")
    need("title", str)
    need("area", str)
    need("repo", str)
    commit = r.get("commit")
    if commit is not None and not (isinstance(commit, str) and SHA_RE.match(commit)):
        out.append("commit must be a full 40-character SHA")
    if r.get("arxiv") is not None and not re.fullmatch(r"\d{4}\.\d{4,5}", str(r["arxiv"])):
        out.append("arxiv must be an id like 1609.02907")
    py = r.get("python")
    if py is not None and not re.fullmatch(r"3\.\d+", str(py)):
        out.append("python must be a version like 3.12")
    env = r.get("env") or {}
    if not isinstance(env, dict):
        out.append("env must be a mapping")
        env = {}
    for key in ("requirements", "extra"):
        if key in env and not (
            isinstance(env[key], list) and all(isinstance(x, str) for x in env[key])
        ):
            out.append(f"env.{key} must be a list of strings")
    for key in ("from_readme", "unpin", "install_project", "no_deps_file"):
        if key in env and not isinstance(env[key], bool):
            out.append(f"env.{key} must be true or false")
    setup = r.get("setup") or []
    if not (isinstance(setup, list) and all(isinstance(x, str) for x in setup)):
        out.append("setup must be a list of commands")
    cmd = need("command", str)
    seeds = r.get("seeds")
    if seeds is not None:
        if not (isinstance(seeds, list) and seeds and all(isinstance(s, int) for s in seeds)):
            out.append("seeds must be a non-empty list of integers")
        elif isinstance(cmd, str) and "{seed}" not in cmd and len(seeds) > 1:
            out.append("several seeds need {seed} in the command")
    elif isinstance(cmd, str) and "{seed}" in cmd:
        out.append("the command uses {seed} but no seeds are listed")
    if "timeout" in r and not isinstance(r["timeout"], int | float):
        out.append("timeout must be a number of seconds")
    if "authored" in r and not isinstance(r["authored"], bool):
        out.append("authored must be true or false")
    metric = r.get("metric")
    if not isinstance(metric, dict) or not isinstance(metric.get("name"), str):
        out.append("metric.name must be a string")
    elif metric.get("select", "last") not in ("last", "first", "min", "max"):
        out.append("metric.select must be last, first, min or max")
    claim = r.get("claim")
    if not isinstance(claim, dict):
        out.append("claim must be a mapping")
    else:
        src = claim.get("source")
        if src not in CLAIM_SOURCES:
            out.append(f"claim.source must be one of {', '.join(CLAIM_SOURCES)}")
        if not isinstance(claim.get("value"), int | float) and not (
            isinstance(claim.get("range"), list) and len(claim["range"]) == 2
        ):
            out.append("claim needs a value (or a range of two numbers)")
        if src == "paper" and not r.get("arxiv") and not claim.get("arxiv"):
            out.append("a paper claim needs the recipe's arxiv id")
        if src == "manual":
            for key in ("metric", "where", "text"):
                if not isinstance(claim.get(key), str):
                    out.append(f"a manual claim needs claim.{key} (a string)")
    tol = r.get("tolerance")
    if tol is not None:
        if not isinstance(tol, dict) or not any(k in tol for k in ("abs", "rel")):
            out.append("tolerance needs abs or rel")
        elif not isinstance(tol.get("why"), str):
            out.append("tolerance.why must say why the tolerance is right")
    vetted = r.get("vetted")
    if vetted is not None:
        if not isinstance(vetted, dict):
            out.append("vetted must be a mapping")
        else:
            if vetted.get("verdict") not in VERDICTS:
                out.append(f"vetted.verdict must be one of {', '.join(VERDICTS)}")
            for key in ("date", "host", "paper_repro"):
                if not isinstance(vetted.get(key), str):
                    out.append(f"vetted.{key} must be a string")
    return out


def find_recipe(target: str, entries: list[dict] | None = None) -> dict | None:
    """The recipe for a slug, a repo (owner/name or URL) or an arXiv id, if there is one."""
    entries = load_gallery() if entries is None else entries
    t = target.strip().rstrip("/").removesuffix(".git")
    for e in entries:
        if e["slug"] == t.lower():
            return e
    repo = repo_key(t)
    by_repo = [e for e in entries if repo and repo_key(e["repo"]) == repo]
    if by_repo:
        return by_repo[0]
    aid = re.sub(
        r"v\d+$", "", re.sub(r"^(?:arxiv:|https?://arxiv\.org/(?:abs|pdf)/)", "", t, flags=re.I)
    )
    by_paper = [e for e in entries if e.get("arxiv") and str(e["arxiv"]) == aid]
    return by_paper[0] if by_paper else None


def recipes_for_repo(repo: str, entries: list[dict] | None = None) -> list[dict]:
    entries = load_gallery() if entries is None else entries
    key = repo_key(repo)
    return [e for e in entries if key and repo_key(e["repo"]) == key]


def repo_key(s: str) -> str | None:
    """owner/name, lowercased, from a GitHub URL or owner/name; None for anything else."""
    s = s.strip().rstrip("/").removesuffix(".git")
    m = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+)", s)
    if m:
        return f"{m.group(1)}/{m.group(2)}".lower()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", s) and not Path(s).exists():
        return s.lower()
    return None
