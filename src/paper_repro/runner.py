"""`run`: execute one command in the repo's environment and record everything about it."""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .study import Study, StudyError
from .util import SKIP_DIRS, now_iso, sha256_file, tail

MAX_SNAPSHOT_FILES = 200_000
HASH_LIMIT = 50 * 2**20
MAX_LISTED = 500
MAX_CAPTURED = 20
CAPTURE_LIMIT = 2 * 2**20  # json/csv results
TEXT_CAPTURE_LIMIT = 256 * 2**10  # .txt/.log; larger text files are usually data, not results


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snap: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = Path(dirpath) / f
            try:
                s = p.stat()
            except OSError:
                continue
            snap[str(p.relative_to(root))] = (s.st_size, s.st_mtime_ns)
            if len(snap) >= MAX_SNAPSHOT_FILES:
                return snap
    return snap


def _limits_preexec(cpu_seconds: int | None, memory_mb: int | None):
    def apply() -> None:
        import resource

        if cpu_seconds:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        if memory_mb:
            limit = memory_mb * 2**20
            try:
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            except (ValueError, OSError):
                pass

    return apply


def _group_members(pgid: int) -> list[int]:
    """PIDs in a process group, read from `ps` (works when killpg reports EPERM)."""
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=", "-o", "pgid="], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == str(pgid) and parts[0] != str(os.getpid()):
            pids.append(int(parts[0]))
    return pids


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
        return
    except ProcessLookupError:
        return
    except PermissionError:
        pass  # macOS returns EPERM for a group whose leader is a zombie; signal members directly
    for pid in _group_members(pgid):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _kill_tree(pgid: int, grace: float = 5.0) -> int:
    """Terminate every process in the group: SIGTERM, then SIGKILL after ``grace`` seconds.
    Returns how many processes were still alive when we started."""
    alive = _group_members(pgid)
    if not alive:
        return 0
    _signal_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _group_members(pgid):
            return len(alive)
        time.sleep(0.2)
    _signal_group(pgid, signal.SIGKILL)
    return len(alive)


def run_command(
    study: Study,
    command: str,
    *,
    timeout: float = 3600,
    cpu_seconds: int | None = None,
    memory_mb: int | None = None,
    env: dict[str, str] | None = None,
    seed: int | None = None,
    scope: str = "full",
    note: str | None = None,
    use_env: bool = True,
) -> dict:
    """Run ``command`` through the shell in the checkout, inside the study env."""
    study.require_repo()
    if scope not in ("full", "shortened", "smoke", "setup"):
        raise StudyError("scope must be one of: full, shortened, smoke, setup")
    if scope == "shortened" and not note:
        raise StudyError(
            "A shortened run needs --note saying what was shortened (epochs, data, steps)."
        )
    with study.lock():
        rid = study.next_id("r", "run")
        study.runs_dir.mkdir(parents=True, exist_ok=True)
        while True:
            # Skip directories left by interrupted runs and by runs still in progress.
            try:
                (study.runs_dir / rid).mkdir()
                break
            except FileExistsError:
                rid = f"r{int(rid[1:]) + 1}"
        overlapping = sorted(
            p.parent.name for p in study.runs_dir.glob("*/RUNNING") if p.parent.name != rid
        )
        (study.runs_dir / rid / "RUNNING").touch()
    run_dir = study.runs_dir / rid
    out_path, err_path = run_dir / "stdout.txt", run_dir / "stderr.txt"

    child_env = dict(os.environ)
    env_used = False
    if use_env and study.env_python().exists():
        child_env["VIRTUAL_ENV"] = str(study.env_dir)
        child_env["PATH"] = str(study.env_bin()) + os.pathsep + child_env.get("PATH", "")
        child_env.pop("PYTHONHOME", None)
        env_used = True
    child_env["PYTHONUNBUFFERED"] = "1"
    overrides = dict(env or {})
    if seed is not None:
        overrides.setdefault("PAPER_REPRO_SEED", str(seed))
    child_env.update(overrides)

    limits: dict[str, Any] = {"timeout_seconds": timeout}
    posix = os.name == "posix"
    if cpu_seconds:
        limits["cpu_seconds_per_process"] = cpu_seconds if posix else "not supported on this OS"
    if memory_mb:
        if platform.system() == "Linux":
            limits["address_space_mb"] = memory_mb
        else:
            limits["address_space_mb"] = (
                f"{memory_mb} requested, not enforced on {platform.system()} "
                "(peak memory is still recorded)"
            )

    before = snapshot(study.repo)
    started = now_iso()
    t0 = time.monotonic()
    with out_path.open("wb") as out_fh, err_path.open("wb") as err_fh:
        kwargs: dict[str, Any] = {}
        if posix:
            kwargs["start_new_session"] = True
            if cpu_seconds or memory_mb:
                kwargs["preexec_fn"] = _limits_preexec(cpu_seconds, memory_mb)
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(study.repo),
            stdout=out_fh,
            stderr=err_fh,
            stdin=subprocess.DEVNULL,
            env=child_env,
            **kwargs,
        )
        result: dict[str, Any] = {}

        def waiter() -> None:
            if posix:
                _, status, rusage = os.wait4(proc.pid, 0)
                result["status"] = status
                result["rusage"] = rusage
            else:
                result["code"] = proc.wait()

        th = threading.Thread(target=waiter, daemon=True)
        th.start()
        th.join(timeout)
        timed_out = th.is_alive()
        leftovers = 0
        if timed_out:
            if posix:
                _kill_tree(proc.pid)
            else:
                proc.kill()
            th.join(30)
        elif posix:
            # background processes the command left behind in its process group
            leftovers = _kill_tree(proc.pid, grace=2.0)
    wall = time.monotonic() - t0
    ended = now_iso()

    exit_code: int | None
    signal_name = None
    peak_rss_mb = None
    cpu_user = cpu_sys = None
    if posix and "status" in result:
        status = result["status"]
        if os.WIFEXITED(status):
            exit_code = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            sig = os.WTERMSIG(status)
            exit_code = -sig
            signal_name = signal.Signals(sig).name
        else:
            exit_code = None
        ru = result["rusage"]
        # ru_maxrss is bytes on macOS and kilobytes on Linux
        scale = 1 if platform.system() == "Darwin" else 1024
        peak_rss_mb = round(ru.ru_maxrss * scale / 2**20, 1)
        cpu_user, cpu_sys = round(ru.ru_utime, 2), round(ru.ru_stime, 2)
    else:
        exit_code = result.get("code")
    if exit_code is not None and proc.returncode is None:
        proc.returncode = exit_code  # already reaped by wait4; keep Popen from waiting again

    # Everything below must not lose the run: if bookkeeping fails, record that and carry on.
    recording_error = None
    written: list[dict] = []
    deleted: list[str] = []
    captured: list[dict] = []
    try:
        after = snapshot(study.repo)
        written, deleted = [], []
        for path, meta in after.items():
            old = before.get(path)
            if old != meta:
                p = study.repo / path
                written.append(
                    {
                        "path": path,
                        "bytes": meta[0],
                        "change": "modified" if old else "created",
                        "sha256": sha256_file(p, HASH_LIMIT) if len(written) < MAX_LISTED else None,
                    }
                )
        for path in before:
            if path not in after:
                deleted.append(path)

        # Keep a copy of small result-like files as they were when this run ended, so metrics
        # extracted later cannot pick up a file that a later run overwrote.
        from .metrics import CAPTURE_SUFFIXES, STRUCTURED_SUFFIXES

        STRUCTURED = STRUCTURED_SUFFIXES | {".jsonl"}

        captured = []
        for w in written:
            src = study.repo / w["path"]
            suffix = src.suffix.lower()
            limit = CAPTURE_LIMIT if suffix in STRUCTURED else TEXT_CAPTURE_LIMIT
            if len(captured) >= MAX_CAPTURED or w["bytes"] > limit:
                continue
            if suffix not in CAPTURE_SUFFIXES or not src.exists():
                continue
            dst = run_dir / "files" / w["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            captured.append(
                {
                    "path": w["path"],
                    "copy": str(dst.relative_to(study.root)),
                    "sha256": sha256_file(dst),
                }
            )
    except Exception as exc:  # noqa: BLE001
        recording_error = f"{type(exc).__name__}: {exc}"

    overlapping = sorted(
        set(overlapping)
        | {p.parent.name for p in study.runs_dir.glob("*/RUNNING") if p.parent.name != rid}
    )
    (run_dir / "RUNNING").unlink(missing_ok=True)
    stdout_text = out_path.read_text(encoding="utf-8", errors="replace")
    stderr_text = err_path.read_text(encoding="utf-8", errors="replace")
    rel_out = str(out_path.relative_to(study.root))
    rel_err = str(err_path.relative_to(study.root))
    return study.append(
        "run",
        {
            "id": rid,
            "command": command,
            "cwd": "repo",
            "overlapped_with": overlapping,
            "env_used": env_used,
            "env_overrides": overrides,
            "seed": seed,
            "scope": scope,
            "note": note,
            "started": started,
            "ended": ended,
            "wall_seconds": round(wall, 3),
            "cpu_user_seconds": cpu_user,
            "cpu_system_seconds": cpu_sys,
            "peak_rss_mb": peak_rss_mb,
            "exit_code": exit_code,
            "signal": signal_name,
            "timed_out": timed_out,
            "limits": limits,
            "leftover_processes_killed": leftovers,
            "recording_error": recording_error,
            "stdout": {
                "path": rel_out,
                "bytes": out_path.stat().st_size,
                "sha256": sha256_file(out_path),
                "tail": tail(stdout_text, 25),
            },
            "stderr": {
                "path": rel_err,
                "bytes": err_path.stat().st_size,
                "sha256": sha256_file(err_path),
                "tail": tail(stderr_text, 25),
            },
            "files": {
                "written": written[:MAX_LISTED],
                "written_count": len(written),
                "deleted": deleted[:MAX_LISTED],
                "deleted_count": len(deleted),
                "captured": captured,
            },
        },
    )
