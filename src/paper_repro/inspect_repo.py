"""`inspect`: get the code into a workspace and describe what it would take to run it."""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

import yaml

from .claims import extract_claims
from .study import Study, StudyError, set_current, slug_for, workspace_root
from .util import SKIP_DIRS, run_capture

LANG_BY_EXT = {
    ".py": "Python",
    ".ipynb": "Jupyter Notebook",
    ".r": "R",
    ".rmd": "R",
    ".jl": "Julia",
    ".m": "MATLAB",
    ".cpp": "C++",
    ".cc": "C++",
    ".cu": "CUDA",
    ".c": "C",
    ".h": "C/C++ header",
    ".hpp": "C++",
    ".lua": "Lua",
    ".java": "Java",
    ".scala": "Scala",
    ".rs": "Rust",
    ".go": "Go",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".sh": "Shell",
    ".rb": "Ruby",
}

DEP_PATTERNS = [
    (re.compile(r"^requirements.*\.(txt|in)$", re.I), "pip-requirements"),
    (re.compile(r"^environment.*\.ya?ml$", re.I), "conda-environment"),
    (re.compile(r"^conda.*\.ya?ml$", re.I), "conda-environment"),
    (re.compile(r"^pyproject\.toml$"), "pyproject"),
    (re.compile(r"^setup\.py$"), "setup.py"),
    (re.compile(r"^setup\.cfg$"), "setup.cfg"),
    (re.compile(r"^Pipfile(\.lock)?$"), "pipenv"),
    (re.compile(r"^poetry\.lock$"), "poetry-lock"),
    (re.compile(r"^uv\.lock$"), "uv-lock"),
    (re.compile(r"^Dockerfile.*$"), "dockerfile"),
    (re.compile(r"^DESCRIPTION$"), "r-description"),
    (re.compile(r"^renv\.lock$"), "renv-lock"),
    (re.compile(r"^Project\.toml$"), "julia-project"),
    (re.compile(r"^package\.json$"), "npm"),
    (re.compile(r"^\.python-version$"), "python-version"),
    (re.compile(r"^runtime\.txt$"), "runtime.txt"),
]

ENTRY_NAMES = {
    "train",
    "main",
    "eval",
    "evaluate",
    "test",
    "run",
    "demo",
    "predict",
    "inference",
    "infer",
    "reproduce",
    "experiment",
    "experiments",
    "benchmark",
}

COMMAND_RE = re.compile(
    r"^\s*(?:\$\s*|>\s*)?(?:[A-Z_][A-Z0-9_]*=\S+\s+)*"
    r"(python3?|python -m|pip3?|conda|bash|sh|\./\S+|make|torchrun|accelerate|deepspeed|"
    r"julia|Rscript|wget|curl|git|cd|export|uv|uvx|jupyter|mpirun|srun)\b"
)
INLINE_CMD_RE = re.compile(r"`((?:python3?|bash|sh|make|torchrun|accelerate)\s[^`]+)`")
URL_RE = re.compile(r"https?://[^\s\"'<>)\]`]+")
DATA_EXT_RE = re.compile(
    r"\.(zip|tar|tgz|gz|bz2|xz|7z|pt|pth|ckpt|bin|h5|hdf5|safetensors|npz|npy|pkl|pickle|mat|"
    r"csv|tsv|json|jsonl|parquet|txt|onnx|tflite|model|weights)(\?.*)?$",
    re.I,
)
DATA_HOSTS = (
    "drive.google.com",
    "docs.google.com/uc",
    "dropbox.com",
    "zenodo.org",
    "huggingface.co",
    "figshare",
    "s3.amazonaws.com",
    "storage.googleapis.com",
    "1drv.ms",
    "onedrive",
    "box.com",
    "kaggle.com",
    "raw.githubusercontent.com",
    "github.com/.*/releases/download",
    "dl.fbaipublicfiles.com",
    "openaipublic",
)
DOWNLOAD_CODE_RE = re.compile(
    r"(urlretrieve|requests\.get|wget\.download|download_url|load_dataset\(|from_pretrained\(|"
    r"hf_hub_download|snapshot_download|gdown|torch\.hub\.load|download=True|"
    r"tfds\.load|keras\.datasets|fetch_openml|load_state_dict_from_url)"
)
GPU_CODE_RE = re.compile(
    r"(\.cuda\(\)|torch\.device\(['\"]cuda|['\"]cuda:\d['\"]|device\s*=\s*['\"]cuda|nvidia-smi|"
    r"CUDA_VISIBLE_DEVICES|import cupy|from apex|import apex|flash_attn|bitsandbytes|"
    r"torch\.distributed|DistributedDataParallel|nccl|tf\.config\.list_physical_devices\(.GPU)"
)
GPU_CHECK_RE = re.compile(
    r"(torch\.cuda\.is_available\(\)|torch\.backends\.mps|--no-cuda|--device)"
)
GPU_TEXT_RE = re.compile(
    r"\b(GPUs?|CUDA|A100|H100|V100|P100|T4|Titan|RTX\s?\d+|GTX\s?\d+|TPU|GRAM|VRAM|"
    r"\d+\s?GB of (?:GPU|video) memory)\b"
)
PY_VERSION_RE = re.compile(r"\bpython\s*(?:version\s*)?(?:>=|==|=)?\s*v?(3\.\d{1,2}|2\.7)\b", re.I)

MAX_FILES = 50_000
MAX_SCAN_BYTES = 1_000_000


def acquire(source: str, dest: Path, ref: str | None = None) -> dict:
    """Shallow-clone a git URL (or copy a local directory) into ``dest``."""
    info: dict[str, Any] = {"source": source, "ref_requested": ref}
    local = Path(source).expanduser()
    if dest.exists() and any(dest.iterdir()):
        info["reused_checkout"] = True
    elif local.exists() and local.is_dir():
        info["mode"] = "copy"
        ignore = shutil.ignore_patterns(*SKIP_DIRS - {".git"})
        shutil.copytree(local, dest, ignore=ignore, symlinks=True)
        info["origin_path"] = str(local.resolve())
    else:
        url = source
        if re.fullmatch(r"[\w.-]+/[\w.-]+", source):
            url = f"https://github.com/{source}"
        info["mode"] = "git-clone"
        info["url"] = url
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", "--depth", "1", "--quiet"]
        if ref:
            cmd += ["--branch", ref]
        r = run_capture([*cmd, url, str(dest)], timeout=900)
        if r["exit_code"] != 0 and ref:
            # ref may be a commit SHA, which --branch does not accept
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True)
            steps = [
                ["git", "init", "--quiet"],
                ["git", "remote", "add", "origin", url],
                ["git", "fetch", "--depth", "1", "--quiet", "origin", ref],
                ["git", "checkout", "--quiet", "FETCH_HEAD"],
            ]
            for s in steps:
                r = run_capture(s, cwd=dest, timeout=900)
                if r["exit_code"] != 0:
                    break
        info["clone"] = {k: r[k] for k in ("argv", "exit_code", "wall_seconds")}
        if r["exit_code"] != 0:
            shutil.rmtree(dest, ignore_errors=True)
            raise StudyError(
                f"git clone failed for {url}:\n{r['stderr'].strip()}\n"
                "Check the URL or owner/repo spelling (private repos need git credentials), "
                "or pass a local path to a checkout."
            )
    git_dir = dest / ".git"
    if git_dir.exists():
        sha = run_capture(["git", "rev-parse", "HEAD"], cwd=dest, timeout=30)
        if sha["exit_code"] == 0:
            info["commit"] = sha["stdout"].strip()
        remote = run_capture(["git", "config", "--get", "remote.origin.url"], cwd=dest, timeout=30)
        if remote["exit_code"] == 0 and remote["stdout"].strip():
            info.setdefault("url", remote["stdout"].strip())
        status = run_capture(["git", "status", "--porcelain"], cwd=dest, timeout=60)
        if status["exit_code"] == 0:
            info["dirty"] = bool(status["stdout"].strip())
        when = run_capture(["git", "log", "-1", "--format=%cI"], cwd=dest, timeout=30)
        if when["exit_code"] == 0:
            info["commit_date"] = when["stdout"].strip()
    else:
        info["commit"] = None
        info["note"] = "Not a git checkout; no commit SHA available."
    return info


def _walk(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for f in sorted(filenames):
            files.append(Path(dirpath) / f)
            if len(files) >= MAX_FILES:
                return files
    return files


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_dep_file(path: Path, kind: str) -> dict:
    text = _read(path)
    out: dict[str, Any] = {}
    if kind == "pip-requirements":
        reqs = [
            ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
        ]
        out["requirements"] = reqs
        out["pinned"] = sum(1 for r in reqs if "==" in r)
    elif kind == "conda-environment":
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            out["parse_error"] = str(exc)
            return out
        deps = data.get("dependencies") or []
        out["channels"] = data.get("channels") or []
        out["conda"] = [d for d in deps if isinstance(d, str)]
        pip = [d.get("pip") for d in deps if isinstance(d, dict) and "pip" in d]
        out["pip"] = pip[0] if pip else []
    elif kind == "pyproject":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            out["parse_error"] = str(exc)
            return out
        proj = data.get("project", {})
        out["requires_python"] = proj.get("requires-python")
        out["dependencies"] = proj.get("dependencies", [])
        out["scripts"] = proj.get("scripts", {})
        poetry = data.get("tool", {}).get("poetry", {})
        if poetry:
            out["poetry_dependencies"] = poetry.get("dependencies", {})
        out["build_backend"] = data.get("build-system", {}).get("build-backend")
    elif kind == "setup.py":
        m = re.search(r"python_requires\s*=\s*['\"]([^'\"]+)", text)
        if m:
            out["requires_python"] = m.group(1)
        m = re.search(r"install_requires\s*=\s*\[([^\]]*)\]", text, re.S)
        if m:
            out["install_requires"] = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
    elif kind == "dockerfile":
        out["from"] = re.findall(r"^\s*FROM\s+(\S+)", text, re.M | re.I)
    elif kind == "r-description":
        for field in ("Depends", "Imports"):
            m = re.search(rf"^{field}:\s*(.+?)(?=^\S|\Z)", text, re.M | re.S)
            if m:
                out[field.lower()] = [
                    x.strip() for x in m.group(1).replace("\n", " ").split(",") if x.strip()
                ]
    elif kind in ("python-version", "runtime.txt"):
        out["value"] = text.strip()
    return out


def _python_hints(deps: list[dict], readme_texts: list[tuple[str, str]]) -> list[dict]:
    hints = []
    for d in deps:
        info = d.get("parsed", {})
        if d["kind"] in ("pyproject", "setup.py") and info.get("requires_python"):
            hints.append({"source": d["path"], "spec": info["requires_python"]})
        if d["kind"] == "conda-environment":
            for c in info.get("conda", []):
                m = re.match(r"python\s*[=<>]+\s*([\d.]+)", c)
                if m:
                    hints.append({"source": d["path"], "spec": c})
        if d["kind"] in ("python-version", "runtime.txt") and info.get("value"):
            hints.append({"source": d["path"], "spec": info["value"]})
        if d["kind"] == "dockerfile":
            for img in info.get("from", []):
                m = re.match(r"python:(\d\.\d+)", img)
                if m:
                    hints.append({"source": d["path"], "spec": m.group(1)})
    for path, text in readme_texts:
        for i, line in enumerate(text.splitlines(), start=1):
            for m in PY_VERSION_RE.finditer(line):
                hints.append(
                    {"source": f"{path}:{i}", "spec": m.group(1), "text": line.strip()[:200]}
                )
    return hints


def _suggest_python(hints: list[dict]) -> dict:
    for h in hints:
        m = re.search(r"(\d)\.(\d{1,2})", h["spec"])
        if m and m.group(1) == "3":
            minor = int(m.group(2))
            version = f"3.{minor}"
            note = f"From {h['source']} ({h['spec']})."
            if minor < 9:
                note += (
                    " Interpreters this old may lack builds for this machine and modern wheels;"
                    " a newer Python is a deviation and should be recorded as one."
                )
            return {"version": version, "reason": note}
    return {"version": "3.11", "reason": "No Python version stated in the repo; 3.11 is a default."}


def _readme_commands(path: str, text: str) -> list[dict]:
    cmds = []
    in_code = False
    for i, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code and COMMAND_RE.match(line):
            cmds.append({"source": f"{path}:{i}", "command": line.strip().lstrip("$> ").strip()})
        elif not in_code:
            for m in INLINE_CMD_RE.finditer(line):
                cmds.append({"source": f"{path}:{i}", "command": m.group(1).strip()})
    return cmds


def inspect_repo(
    source: str,
    *,
    ref: str | None = None,
    name: str | None = None,
    workspace: str | None = None,
    study_dir: str | None = None,
) -> dict:
    ws = workspace_root(workspace)
    root = Path(study_dir).expanduser().resolve() if study_dir else ws / (name or slug_for(source))
    study = Study(root)
    if study.log_path.exists() and any(e["kind"] == "inspect" for e in study.entries()):
        prior = study.state()["inspect"]
        prior_source = prior.get("repo", {}).get("source") or ""
        if prior_source != source and slug_for(prior_source) != slug_for(source):
            raise StudyError(
                f"{root} already holds a study of {prior_source}. Pass --name (MCP: name) to "
                "start a separate study for this repo."
            )
    fresh = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    try:
        repo_info = acquire(source, study.repo, ref)
    except BaseException:
        if fresh:
            shutil.rmtree(root, ignore_errors=True)
        raise
    report = scan(study.repo)
    if not study_dir:
        set_current(ws, root)
    for i, c in enumerate(report["claims"], start=1):
        c["id"] = f"c{i}"
    entry = study.append("inspect", {"repo": repo_info, **report})
    (root / "inspect.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return {**entry, "study": str(root)}


def scan(repo: Path) -> dict:
    files = _walk(repo)
    rels = [f.relative_to(repo) for f in files]
    lang_bytes: dict[str, int] = {}
    total = 0
    for f, rel in zip(files, rels, strict=True):
        try:
            size = f.stat().st_size
        except OSError:
            continue
        total += size
        lang = LANG_BY_EXT.get(f.suffix.lower())
        if lang:
            lang_bytes[lang] = lang_bytes.get(lang, 0) + size
        if rel.name == "DESCRIPTION" and len(rel.parts) == 1:
            lang_bytes["R"] = lang_bytes.get("R", 0) + size
    languages = sorted(lang_bytes.items(), key=lambda kv: -kv[1])
    # Notebooks carry outputs and images, so their byte counts overstate them.
    code_langs = [k for k, _ in languages if k != "Jupyter Notebook"]
    primary = code_langs[0] if code_langs else (languages[0][0] if languages else None)

    deps = []
    for f, rel in zip(files, rels, strict=True):
        if len(rel.parts) > 3:
            continue
        for pat, kind in DEP_PATTERNS:
            if pat.match(rel.name):
                deps.append({"path": str(rel), "kind": kind, "parsed": _parse_dep_file(f, kind)})
                break

    readmes = [
        (str(rel), _read(f))
        for f, rel in zip(files, rels, strict=True)
        if (re.match(r"readme", rel.name, re.I) and len(rel.parts) <= 3)
        or (len(rel.parts) == 1 and rel.suffix.lower() == ".md")
    ]
    readmes.sort(key=lambda t: (t[0].count("/"), t[0].lower() != "readme.md", t[0]))

    commands = []
    for path, text in readmes:
        commands.extend(_readme_commands(path, text))
    install_hints = []
    for c in commands:
        m = re.match(r"^(?:pip3?|python3? -m pip|uv pip)\s+install\s+(.+)$", c["command"])
        if m:
            pkgs = [t for t in m.group(1).split() if not t.startswith("-") and t != "."]
            if pkgs and not any(t.endswith((".txt", ".yml", ".yaml")) for t in pkgs):
                install_hints.append({"source": c["source"], "packages": pkgs})

    claims = []
    for path, text in readmes:
        claims.extend(extract_claims(text, path))

    readme_text = "\n".join(t for _, t in readmes)
    entry_points = []
    notebooks = []
    for f, rel in zip(files, rels, strict=True):
        if f.suffix == ".ipynb":
            notebooks.append(str(rel))
            continue
        if f.suffix not in (".py", ".sh", ".R", ".jl") or len(rel.parts) > 3:
            continue
        text = _read(f) if f.suffix == ".py" else ""
        reasons = []
        if f.stem.lower() in ENTRY_NAMES or any(
            f.stem.lower().startswith(n + "_") for n in ENTRY_NAMES
        ):
            reasons.append("name")
        if "__main__" in text:
            reasons.append("__main__ guard")
        if str(rel) in readme_text or (f.name in readme_text and len(f.name) > 4):
            reasons.append("mentioned in README")
        if f.suffix == ".sh" and len(rel.parts) <= 2:
            reasons.append("shell script")
        if reasons:
            argparse_flags = re.findall(r"add_argument\(\s*['\"](--[\w-]+)", text)[:40]
            entry_points.append({"path": str(rel), "why": reasons, "flags": argparse_flags})
    entry_points.sort(key=lambda e: (-len(e["why"]), e["path"]))

    downloads = []
    gpu = {"code": [], "readme": [], "availability_checks": 0}
    seen_urls: set[str] = set()
    for f, rel in zip(files, rels, strict=True):
        if f.suffix.lower() not in (
            ".py",
            ".sh",
            ".md",
            ".txt",
            ".yml",
            ".yaml",
            ".cfg",
            ".r",
            ".jl",
            ".ipynb",
        ):
            continue
        text = _read(f)
        if not text:
            continue
        is_readme = any(rel_s == str(rel) for rel_s, _ in readmes)
        for i, line in enumerate(text.splitlines(), start=1):
            for u in URL_RE.findall(line):
                u = u.rstrip(".,;")
                if u in seen_urls:
                    continue
                if DATA_EXT_RE.search(u) or any(re.search(h, u) for h in DATA_HOSTS):
                    if re.search(r"(arxiv\.org|github\.com/[^/]+/[^/]+/?$|shields\.io|badge)", u):
                        continue
                    seen_urls.add(u)
                    downloads.append({"url": u, "source": f"{rel}:{i}"})
            if f.suffix in (".py", ".sh") and DOWNLOAD_CODE_RE.search(line):
                downloads.append({"code": line.strip()[:200], "source": f"{rel}:{i}"})
            if f.suffix in (".py", ".sh", ".ipynb"):
                if GPU_CODE_RE.search(line):
                    gpu["code"].append({"source": f"{rel}:{i}", "text": line.strip()[:200]})
                if GPU_CHECK_RE.search(line):
                    gpu["availability_checks"] += 1
            if is_readme and GPU_TEXT_RE.search(line):
                gpu["readme"].append({"source": f"{rel}:{i}", "text": line.strip()[:200]})
    for d in deps:
        for r in d["parsed"].get("requirements", []) + d["parsed"].get("pip", []):
            if isinstance(r, str) and re.search(
                r"(\+cu\d+|-gpu\b|cupy|nvidia-|flash.attn|bitsandbytes)", r, re.I
            ):
                gpu["code"].append({"source": d["path"], "text": r})
    gpu["summary"] = (
        f"{len(gpu['code'])} CUDA-specific code or dependency lines, "
        f"{gpu['availability_checks']} device-availability checks or device flags, "
        f"{len(gpu['readme'])} README lines mentioning GPUs."
    )
    gpu["code"] = gpu["code"][:40]
    gpu["readme"] = gpu["readme"][:20]

    hints = _python_hints(deps, readmes)
    from .paper import find_paper_links

    papers: list[dict[str, str]] = []
    for path, text in readmes:
        for link in find_paper_links(text, path):
            if all(p["arxiv"] != link["arxiv"] for p in papers):
                papers.append(link)
    return {
        "size": {"files": len(files), "bytes": total, "truncated": len(files) >= MAX_FILES},
        "languages": [{"language": k, "bytes": v} for k, v in languages],
        "primary_language": primary,
        "dependency_files": deps,
        "python_hints": hints[:20],
        "suggested_python": _suggest_python(hints),
        "readmes": [p for p, _ in readmes],
        "readme_commands": commands[:80],
        "readme_install_hints": install_hints[:10],
        "entry_points": entry_points[:40],
        "notebooks": notebooks[:40],
        "downloads": downloads[:60],
        "gpu": gpu,
        "claims": claims[:300],
        "papers": papers[:10],
    }
