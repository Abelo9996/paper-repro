"""`env`: build an isolated environment for the repo with uv and record exactly what resolved."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .study import Study, StudyError, locked
from .util import host_info, run_capture, sha256_file, tail, which

# Conda packages that have no pip equivalent or are part of the interpreter/toolchain.
CONDA_SKIP = {
    "python",
    "pip",
    "setuptools",
    "wheel",
    "cudatoolkit",
    "cudnn",
    "cuda",
    "mkl",
    "mkl-service",
    "blas",
    "libblas",
    "openblas",
    "nomkl",
    "ca-certificates",
    "certifi",
    "openssl",
    "libgcc-ng",
    "libstdcxx-ng",
    "ld_impl_linux-64",
    "readline",
    "sqlite",
    "tk",
    "xz",
    "zlib",
    "ncurses",
    "libffi",
    "_libgcc_mutex",
    "_openmp_mutex",
    "intel-openmp",
    "pytorch-cuda",
}
CONDA_RENAME = {"pytorch": "torch", "pytorch-cpu": "torch", "py-opencv": "opencv-python"}


def _uv() -> str:
    uv = which("uv")
    if not uv:
        raise StudyError(
            "uv is not on PATH. Install it (https://docs.astral.sh/uv/) so paper-repro can build "
            "isolated environments."
        )
    return uv


def conda_to_requirements(env_file: Path) -> tuple[list[str], list[str], str | None]:
    """Translate an environment.yml into pip requirement lines. Returns (reqs, skipped, python)."""
    data = yaml.safe_load(env_file.read_text(encoding="utf-8")) or {}
    reqs: list[str] = []
    skipped: list[str] = []
    python = None
    for dep in data.get("dependencies") or []:
        if isinstance(dep, dict):
            reqs.extend(str(p) for p in dep.get("pip", []) or [])
            continue
        spec = str(dep).split("::")[-1].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(?:([=<>!]=?)\s*([^=\s]+))?(?:=\S+)?$", spec)
        if not m:
            skipped.append(spec)
            continue
        name, op, ver = m.group(1).lower(), m.group(2), m.group(3)
        if name == "python":
            python = ver
            continue
        if name in CONDA_SKIP or name.startswith("lib"):
            skipped.append(spec)
            continue
        name = CONDA_RENAME.get(name, name)
        if op == "=" and ver:
            # conda `=1.2` means 1.2.*; `==` is exact
            reqs.append(f"{name}=={ver}" if ver.count(".") >= 2 else f"{name}=={ver}.*")
        elif op and ver:
            reqs.append(f"{name}{op}{ver}")
        else:
            reqs.append(name)
    return reqs, skipped, python


def unpin(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith(("#", "-", "git+", "http")):
            out.append(s)
            continue
        out.append(re.split(r"[=<>!~;\[ ]", s, maxsplit=1)[0])
    return out


def _has_requirements(path: Path) -> bool:
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            return True
    return False


@locked
def create_env(
    study: Study,
    *,
    python: str | None = None,
    requirements: list[str] | None = None,
    install_project: bool = False,
    extra: list[str] | None = None,
    unpin_versions: bool = False,
    no_deps_file: bool = False,
    from_readme: bool = False,
    recreate: bool = False,
    timeout: float = 3600,
) -> dict:
    """Create ``<study>/env`` with uv, install the repo's dependencies, write lock.txt."""
    study.require_repo()
    uv = _uv()
    st = study.state()
    insp = st["inspect"] or {}
    eid = study.next_id("e", "env")
    deviations: list[str] = []
    steps: list[dict[str, Any]] = []
    plan: list[tuple[str, list[str]]] = []

    suggested = insp.get("suggested_python") or {}
    if not python:
        python = suggested.get("version") or "3.11"
    elif suggested.get("reason", "").startswith("From ") and not python.startswith(
        suggested["version"]
    ):
        deviations.append(
            f"Python {python} used; the repo asks for {suggested['version']} "
            f"({suggested['reason'].split(' (')[0].removeprefix('From ')})."
        )

    # Keep a working env aside while trying a new one, so a failed attempt does not leave the
    # study without an environment. It is restored if this attempt fails.
    backup = study.root / "env.prev"
    lock_backup = study.root / "lock.txt.prev"
    active = st.get("active_env")
    if backup.exists():
        shutil.rmtree(backup)
    lock_backup.unlink(missing_ok=True)
    if study.env_dir.exists() and (recreate or st["envs"]):
        if active and not recreate:
            study.env_dir.rename(backup)
            if (study.root / "lock.txt").exists():
                shutil.copy2(study.root / "lock.txt", lock_backup)
        else:
            shutil.rmtree(study.env_dir)
    plan.append(("create venv", [uv, "venv", "--quiet", "--python", python, str(study.env_dir)]))
    py = str(study.env_python())
    install = [uv, "pip", "install", "--python", py]

    req_files: list[str] = []
    if requirements:
        req_files = list(requirements)
    elif not no_deps_file:
        for d in insp.get("dependency_files", []):
            if d["kind"] == "pip-requirements" and "/" not in d["path"]:
                req_files.append(d["path"])
                break
        if not req_files:
            for d in insp.get("dependency_files", []):
                if d["kind"] == "conda-environment" and "/" not in d["path"]:
                    req_files.append(d["path"])
                    break
        if not req_files and not install_project:
            kinds = {d["kind"] for d in insp.get("dependency_files", []) if "/" not in d["path"]}
            if kinds & {"pyproject", "setup.py", "setup.cfg"}:
                install_project = True

    generated_dir = study.root / "env-inputs"
    for rf in req_files:
        path = (study.repo / rf).resolve()
        if not path.exists():
            path = Path(rf).expanduser().resolve()
            if not path.exists():
                raise StudyError(f"Requirements file not found: {rf}")
            deviations.append(f"Used requirements file from outside the repo: {path}")
        if path.suffix in (".yml", ".yaml"):
            reqs, skipped, conda_py = conda_to_requirements(path)
            generated_dir.mkdir(exist_ok=True)
            out = generated_dir / f"{eid}-from-{path.stem}.txt"
            out.write_text("\n".join(reqs) + "\n", encoding="utf-8")
            deviations.append(
                f"Translated conda file {rf} to pip requirements ({out.name}); conda-only packages "
                f"skipped: {', '.join(skipped) or 'none'}. Conda builds may differ from PyPI wheels."
            )
            if conda_py and not python.startswith(conda_py.rstrip(".*")):
                deviations.append(f"{rf} asks for python {conda_py}; env uses {python}.")
            path = out
        if unpin_versions:
            generated_dir.mkdir(exist_ok=True)
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            out = generated_dir / f"{eid}-unpinned-{path.name}"
            out.write_text("\n".join(unpin(lines)) + "\n", encoding="utf-8")
            deviations.append(
                f"Removed version pins from {rf} ({out.name}); resolved versions are in lock.txt "
                "and may not match what the authors used."
            )
            path = out
        if _has_requirements(path):
            plan.append((f"install {rf}", [*install, "-r", str(path)]))
        else:
            steps.append({"step": f"install {rf}", "skipped": "file lists no requirements"})
    readme_pkgs: list[str] = []
    if from_readme:
        hints = insp.get("readme_install_hints") or []
        if not hints:
            raise StudyError("--from-readme: no `pip install <packages>` line found in the README.")
        for h in hints:
            readme_pkgs.extend(p for p in h["packages"] if p not in readme_pkgs)
        plan.append(("install packages named in README", [*install, *readme_pkgs]))
        srcs = ", ".join(h["source"] for h in hints)
        unpinned_n = sum(1 for p in readme_pkgs if not re.search(r"[=<>~]", p))
        deviations.append(
            f"Installed packages named in {srcs}: {' '.join(readme_pkgs)}"
            + (
                f" ({unpinned_n} without versions, so the latest compatible releases were used)"
                if unpinned_n
                else ""
            )
        )
    if install_project:
        plan.append(("install project", [*install, "-e", str(study.repo)]))
    if extra:
        plan.append(("install extra packages", [*install, *extra]))
        if req_files or install_project or readme_pkgs:
            deviations.append(f"Added packages not listed by the repo: {' '.join(extra)}")
        else:
            deviations.append(
                f"The repo declares no installable dependencies; packages chosen by the agent: {' '.join(extra)}"
            )
    if not req_files and not install_project and not extra and not readme_pkgs:
        steps.append({"step": "dependencies", "skipped": "no dependency file found or selected"})

    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env["NO_COLOR"] = "1"

    def show(cmd: list[str]) -> str:
        """The command as it should appear in a shareable report: no local absolute paths."""
        parts = []
        for c in cmd:
            if c == uv:
                c = "uv"
            c = c.replace(str(study.repo), "<repo>").replace(str(study.root), "<study>")
            parts.append(c)
        return " ".join(parts)

    status = "ok"
    failure = None
    for label, cmd in plan:
        r = run_capture(cmd, cwd=study.repo, timeout=timeout, env=env)
        step = {
            "step": label,
            "command": show(cmd),
            "exit_code": r["exit_code"],
            "timed_out": r["timed_out"],
            "wall_seconds": r["wall_seconds"],
            "stderr_tail": tail(r["stderr"], 60, 8000),
        }
        steps.append(step)
        if r["exit_code"] != 0:
            status = "failed"
            failure = {
                "step": label,
                "command": step["command"],
                "exit_code": r["exit_code"],
                "timed_out": r["timed_out"],
                "error": tail(r["stderr"] or r["stdout"], 60, 8000),
            }
            break

    restored = None
    if status != "ok" and backup.exists():
        if study.env_dir.exists():
            shutil.rmtree(study.env_dir)
        backup.rename(study.env_dir)
        if lock_backup.exists():
            lock_backup.replace(study.root / "lock.txt")
        restored = active["id"]
    elif backup.exists():
        shutil.rmtree(backup)
        lock_backup.unlink(missing_ok=True)

    lock = None
    versions: dict[str, Any] = {}
    if Path(py).exists() and not restored:
        r = run_capture([uv, "pip", "freeze", "--python", py], timeout=120, env=env)
        if r["exit_code"] == 0:
            lock_path = study.root / "lock.txt"
            lock_path.write_text(r["stdout"], encoding="utf-8")
            lock = {
                "path": "lock.txt",
                "sha256": sha256_file(lock_path),
                "packages": len([ln for ln in r["stdout"].splitlines() if ln.strip()]),
            }
            for ln in r["stdout"].splitlines():
                m = re.match(r"^([A-Za-z0-9_.\-]+)==(.+)$", ln.strip())
                if m:
                    versions[m.group(1).lower()] = m.group(2)
        r = run_capture(
            [
                py,
                "-c",
                "import platform,sys;print(platform.python_version());print(sys.executable)",
            ],
            timeout=60,
        )
        if r["exit_code"] == 0:
            lines = r["stdout"].split()
            versions["python"] = lines[0]
    uv_version = run_capture([uv, "--version"], timeout=30)["stdout"].strip()
    return study.append(
        "env",
        {
            "id": eid,
            "status": status,
            "python_requested": python,
            "python": versions.get("python"),
            "uv": uv_version,
            "requirements": req_files,
            "install_project": install_project,
            "extra": extra or [],
            "readme_packages": readme_pkgs,
            "unpinned": unpin_versions,
            "steps": steps,
            "failure": failure,
            "lock": lock,
            "packages": {k: v for k, v in versions.items() if k != "python"},
            "deviations": deviations,
            "restored_env": restored,
            "hints": _hints(status, failure, steps, insp, python, from_readme, unpin_versions)
            + (
                [f"The working environment from {restored} was put back, so runs still use it."]
                if restored
                else []
            ),
            "host": host_info(),
        },
    )


def _hints(
    status: str,
    failure: dict | None,
    steps: list[dict],
    insp: dict,
    python: str,
    from_readme: bool,
    unpinned: bool,
) -> list[str]:
    """What to try next, in plain words, based on what happened."""
    out: list[str] = []
    readme_hints = insp.get("readme_install_hints") or []
    if status == "ok" and any(s.get("step") == "dependencies" for s in steps) and not from_readme:
        if readme_hints:
            h = readme_hints[0]
            out.append(
                f"Nothing was installed: the repo has no dependency file, but {h['source']} says "
                f"`pip install {' '.join(h['packages'])}`. Re-run with from_readme=true "
                "(CLI: --from-readme)."
            )
        else:
            out.append(
                "Nothing was installed: no dependency file or README `pip install` line was found. "
                "Read the README and pass the packages it needs with extra=[...] (CLI: --extra), "
                "which is recorded as a deviation."
            )
    if status == "ok" or not failure:
        return out
    err = (failure.get("error") or "").lower()
    if failure.get("step") == "create venv":
        out.append(
            f"uv could not create a Python {python} environment. Try a newer Python, for example "
            "python='3.11' (CLI: --python 3.11); the change is recorded as a deviation."
        )
    elif failure.get("timed_out"):
        out.append("The install timed out. Re-run with a longer timeout (CLI: --timeout).")
    elif re.search(
        r"no solution|unsatisfiable|no matching distribution|not found in the package registry|has no wheels|no version of",
        err,
    ):
        if not unpinned:
            out.append(
                "The pinned versions could not be resolved for this Python and machine. Try, in "
                "order: the Python version the pins were made for, then unpin=true (CLI: --unpin). "
                "Both are recorded as deviations."
            )
        else:
            out.append(
                "Even without pins the packages could not be resolved. Check the error for a "
                "package with no build for this platform; if it cannot be installed, record "
                "could_not_run with this env id as the blocker."
            )
    elif "failed to build" in err or "build backend" in err or "error: command" in err:
        out.append(
            "A package failed to build from source. A newer Python often has prebuilt wheels "
            "(try python='3.11'), or unpin=true to allow a release that ships wheels."
        )
    return out
