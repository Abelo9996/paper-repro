"""Small shared helpers: hashing, time, subprocess capture, metric vocabulary."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    ".ipynb_checkpoints",
    ".tox",
}


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, limit: int | None = None) -> str | None:
    """Hash a file. Returns None when the file is larger than ``limit`` bytes."""
    try:
        if limit is not None and path.stat().st_size > limit:
            return None
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def tail(text: str, lines: int = 20, max_chars: int = 4000) -> str:
    out = "\n".join(text.splitlines()[-lines:])
    return out[-max_chars:]


def run_capture(
    cmd: list[str], cwd: Path | None = None, timeout: float = 600, env: dict | None = None
) -> dict:
    """Run a command without a shell and capture everything about it."""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        rc = None
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        timed_out = True
    except FileNotFoundError as exc:
        rc, out, err, timed_out = 127, "", str(exc), False
    return {
        "argv": cmd,
        "cwd": str(cwd) if cwd else None,
        "exit_code": rc,
        "timed_out": timed_out,
        "wall_seconds": round(time.monotonic() - start, 3),
        "stdout": out,
        "stderr": err,
    }


def which(name: str) -> str | None:
    return shutil.which(name)


def host_info() -> dict:
    info = {
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python_of_tool": platform.python_version(),
    }
    if platform.system() == "Darwin":
        info["os_version"] = platform.mac_ver()[0]
        r = run_capture(["sysctl", "-n", "hw.memsize"], timeout=5)
        if r["exit_code"] == 0 and r["stdout"].strip().isdigit():
            info["memory_gb"] = round(int(r["stdout"].strip()) / 2**30, 1)
        r = run_capture(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=5)
        if r["exit_code"] == 0:
            info["cpu"] = r["stdout"].strip()
    elif platform.system() == "Linux":
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    info["memory_gb"] = round(int(line.split()[1]) / 2**20, 1)
        except OSError:
            pass
    return info


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Metric vocabulary shared by README claim extraction and log metric extraction.
# ---------------------------------------------------------------------------

METRIC_WORDS = [
    r"top[-_ ]?[15](?:[-_ ]?acc(?:uracy)?)?",
    r"accuracy",
    r"acc",
    r"balanced[-_ ]accuracy",
    r"f1(?:[-_ ]?score)?",
    r"macro[-_ ]f1",
    r"micro[-_ ]f1",
    r"precision",
    r"recall(?:@\d+)?",
    r"roc[-_ ]?auc",
    r"auroc",
    r"auc",
    r"map(?:@[\d.:]+)?",
    r"bleu",
    r"rouge(?:[-_ ]?(?:1|2|l|lsum))?",
    r"meteor",
    r"perplexity",
    r"ppl",
    r"loss",
    r"nll",
    r"error(?:[-_ ]rate)?",
    r"err",
    r"mse",
    r"rmse",
    r"mae",
    r"r2",
    r"r\^2",
    r"exact[-_ ]match",
    r"em",
    r"m?iou",
    r"dice",
    r"psnr",
    r"ssim",
    r"lpips",
    r"fid",
    r"inception[-_ ]score",
    r"wer",
    r"cer",
    r"bpc",
    r"bpd",
    r"spearman",
    r"pearson",
    r"ndcg(?:@\d+)?",
    r"mrr",
    r"hits@\d+",
    r"pass@\d+",
    r"reward",
]

METRIC_PREFIXES = [
    "train",
    "training",
    "val",
    "valid",
    "validation",
    "test",
    "eval",
    "evaluation",
    "dev",
    "best",
    "final",
    "mean",
    "average",
    "avg",
    "overall",
    "macro",
    "micro",
    "weighted",
    "top-1",
    "top1",
    "top-5",
    "top5",
]

METRIC_RE = "(?:" + "|".join(METRIC_WORDS) + ")"
PREFIX_RE = "(?:" + "|".join(re.escape(p) for p in METRIC_PREFIXES) + ")"
# A metric name: up to two qualifier words, then a metric word, then an optional dotted suffix
# like "acc.". Word boundaries keep "accurate" and "lossless" out.
SPLIT_RE = "(?:train|val|valid|test|dev|eval)"
NAME_RE = (
    r"(?<![\w.])(?P<name>(?:"
    + PREFIX_RE
    + r"[ _\-]){0,2}"
    + METRIC_RE
    + r"(?:[_\-]"
    + SPLIT_RE
    + r")?)(?![a-zA-Z0-9])\.?"
)
NUM_RE = r"[-+]?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][-+]?\d+)?"

LOWER_IS_BETTER = {
    "loss",
    "nll",
    "error",
    "error_rate",
    "err",
    "mse",
    "rmse",
    "mae",
    "perplexity",
    "ppl",
    "fid",
    "wer",
    "cer",
    "bpc",
    "bpd",
    "lpips",
}

ALIASES = {
    "acc": "accuracy",
    "ppl": "perplexity",
    "f1_score": "f1",
    "err": "error",
    "valid": "val",
    "validation": "val",
    "top1": "top1",
    "top_1": "top1",
    "top5": "top5",
    "top_5": "top5",
    "auroc": "roc_auc",
    "rocauc": "roc_auc",
    "evaluation": "eval",
    "training": "train",
    "average": "avg",
}


SPLITS = {"train", "val", "test", "dev", "eval"}


def normalize_metric(name: str) -> str:
    """Canonical metric key: lowercase, underscores, common aliases folded."""
    n = name.strip().lower().rstrip(".:")
    n = re.sub(r"[\s\-]+", "_", n)
    n = re.sub(r"_+", "_", n)
    parts = [ALIASES.get(p, p) for p in n.split("_") if p]
    if len(parts) > 1 and parts[-1] in SPLITS:
        parts = [parts[-1], *parts[:-1]]
    n = "_".join(parts)
    n = re.sub(r"^top_?1(_accuracy)?$", "top1_accuracy", n)
    n = re.sub(r"^top_?5(_accuracy)?$", "top5_accuracy", n)
    return n


def metric_base(name: str) -> str:
    """The metric word without qualifiers: 'best_val_loss' -> 'loss'."""
    norm = normalize_metric(name)
    parts = norm.split("_")
    while len(parts) > 1 and parts[0] in {ALIASES.get(p, p) for p in METRIC_PREFIXES}:
        parts = parts[1:]
    return "_".join(parts)


def lower_is_better(name: str) -> bool:
    base = metric_base(name)
    return base in LOWER_IS_BETTER or base.split("_")[-1] in LOWER_IS_BETTER


def decimals(text: str) -> int:
    """Number of digits after the decimal point in a number as written."""
    text = text.strip().lstrip("+-")
    if "e" in text.lower():
        return 0
    return len(text.split(".", 1)[1]) if "." in text else 0
