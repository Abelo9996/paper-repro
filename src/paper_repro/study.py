"""A study is one reproduction attempt: a checkout, an env, and an append-only evidence log.

Layout of a study directory::

    <study>/
      repo/            the checkout (a shallow clone or a copy of a local path)
      env/             the virtual environment created by `env`
      runs/r1/         stdout.txt and stderr.txt for each `run`
      lock.txt         `uv pip freeze` of the env after setup
      evidence.jsonl   append-only, hash-chained log; the single source of truth
      report.md/.json  written by `report`

Everything the tool knows about a study is derived by replaying evidence.jsonl, so the
report can never say something the log does not.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import now_iso, sha256_bytes

GENESIS = "0" * 64
CURRENT_FILE = "CURRENT"


class StudyError(Exception):
    """A user-facing error (bad id, missing study, and so on)."""


def workspace_root(explicit: str | os.PathLike | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("PAPER_REPRO_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / "paper-repro-runs").resolve()


def _entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return sha256_bytes(json.dumps(body, sort_keys=True, ensure_ascii=False).encode())


@dataclass
class Study:
    root: Path

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def env_dir(self) -> Path:
        return self.root / "env"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def log_path(self) -> Path:
        return self.root / "evidence.jsonl"

    def env_python(self) -> Path:
        if os.name == "nt":
            return self.env_dir / "Scripts" / "python.exe"
        return self.env_dir / "bin" / "python"

    def env_bin(self) -> Path:
        return self.env_dir / ("Scripts" if os.name == "nt" else "bin")

    # ------------------------------------------------------------------ log

    def entries(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        out = []
        with self.log_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def append(self, kind: str, payload: dict[str, Any]) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        prior = self.entries()
        entry = {
            "seq": len(prior) + 1,
            "ts": now_iso(),
            "kind": kind,
            "prev": prior[-1]["hash"] if prior else GENESIS,
            **payload,
        }
        entry["hash"] = _entry_hash(entry)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        return entry

    def next_id(self, prefix: str, kind: str) -> str:
        n = sum(1 for e in self.entries() if e["kind"] == kind)
        return f"{prefix}{n + 1}"

    # ---------------------------------------------------------------- state

    def state(self) -> dict:
        """Replay the log into a convenient view."""
        st: dict[str, Any] = {
            "study": str(self.root),
            "inspect": None,
            "envs": [],
            "runs": {},
            "metrics": {},
            "claims": {},
            "comparisons": [],
            "notes": [],
        }
        for e in self.entries():
            k = e["kind"]
            if k == "inspect":
                st["inspect"] = e
                for c in e.get("claims", []):
                    st["claims"][c["id"]] = c
            elif k == "env":
                st["envs"].append(e)
            elif k == "run":
                st["runs"][e["id"]] = e
            elif k == "metrics":
                st["metrics"][e["id"]] = e
            elif k == "claim":
                st["claims"][e["claim"]["id"]] = e["claim"]
            elif k == "compare":
                st["comparisons"].append(e)
            elif k == "note":
                st["notes"].append(e)
        return st

    def require_repo(self) -> None:
        if not self.repo.exists():
            raise StudyError(f"No checkout in {self.root}. Run `paper-repro inspect <repo>` first.")

    def verify(self) -> dict:
        """Check the hash chain and the hashes of every captured output file."""
        problems: list[str] = []
        prev = GENESIS
        entries = self.entries()
        for e in entries:
            if e.get("prev") != prev:
                problems.append(f"entry {e.get('seq')}: prev hash does not match entry before it")
            if _entry_hash(e) != e.get("hash"):
                problems.append(
                    f"entry {e.get('seq')}: content hash mismatch (edited after writing)"
                )
            prev = e.get("hash", "")
            if e["kind"] == "run":
                for stream in ("stdout", "stderr"):
                    info = e.get(stream) or {}
                    p = self.root / info.get("path", "")
                    if info.get("path") and p.exists():
                        from .util import sha256_file

                        if sha256_file(p) != info.get("sha256"):
                            problems.append(
                                f"{e['id']} {stream}: file changed since it was recorded"
                            )
                    elif info.get("path"):
                        problems.append(f"{e['id']} {stream}: file missing ({info.get('path')})")
        return {
            "ok": not problems,
            "entries": len(entries),
            "head": prev if entries else None,
            "problems": problems,
        }


def slug_for(source: str) -> str:
    s = source.rstrip("/")
    s = re.sub(r"\.git$", "", s)
    m = re.search(r"(?:github\.com|gitlab\.com|bitbucket\.org)[/:]([^/]+)/([^/]+)", s)
    if m:
        s = f"{m.group(1)}-{m.group(2)}"
    elif re.fullmatch(r"[\w.-]+/[\w.-]+", s) and not Path(s).exists():
        s = s.replace("/", "-")
    else:
        s = Path(s).name or "repo"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-") or "repo"


def set_current(ws: Path, study_root: Path) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / CURRENT_FILE).write_text(str(study_root) + "\n", encoding="utf-8")


def resolve_study(study: str | os.PathLike | None = None, workspace: str | None = None) -> Study:
    """Find the study to act on: explicit path, $PAPER_REPRO_STUDY, or the workspace CURRENT."""
    if study:
        p = Path(study).expanduser().resolve()
        if not (p / "evidence.jsonl").exists():
            raise StudyError(f"{p} is not a study directory (no evidence.jsonl).")
        return Study(p)
    env = os.environ.get("PAPER_REPRO_STUDY")
    if env:
        return resolve_study(env)
    cur = workspace_root(workspace) / CURRENT_FILE
    if cur.exists():
        return resolve_study(cur.read_text(encoding="utf-8").strip())
    raise StudyError("No study selected. Run `paper-repro inspect <repo>` or pass --study DIR.")
