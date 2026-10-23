"""Vet gallery recipes for real and record what happened in the recipe's `vetted` block.

    uv run python scripts/vet_gallery.py SLUG [SLUG ...] [--workspace DIR] [--dry-run]

Each slug is run with `paper-repro repro SLUG` in a fresh study. The measured values, verdict,
wall times, machine and package versions are read back from that study's report.json, never
typed in, and written to src/paper_repro/data/gallery.yaml (whatever the verdict).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GALLERY = ROOT / "src" / "paper_repro" / "data" / "gallery.yaml"
KEY_PACKAGES = (
    "torch",
    "torchvision",
    "tensorflow",
    "numpy",
    "scipy",
    "networkx",
    "gymnasium",
    "scikit-learn",
)
HEADER = """\
# Papers whose official code was run end to end by `paper-repro repro <slug>` on a CPU laptop.
# Every number under `vetted` was written by scripts/vet_gallery.py from a recorded run's
# report.json; none is typed in. A recipe pins what `repro` needs: commit, Python, environment,
# setup, the exact command with its seeds, the metric to read and the claim to compare with.
"""


def vetted_from_report(rep: dict) -> dict:
    k = [c for c in rep["comparisons"] if not c.get("superseded_by")][-1]
    host = rep["host"]
    os_name = {"Darwin": "macOS"}.get(host.get("os"), host.get("os"))
    env = rep.get("environment") or {}
    full = [c for c in rep["commands"] if c["scope"] == "full"]
    out = {
        "verdict": k["verdict"],
        "label": k["label"],
        "headline": k["headline"],
        "date": rep["generated_at"][:10],
        "paper_repro": rep["tool"]["version"],
        "host": f"{host.get('cpu') or host.get('machine')}, {os_name} {host.get('os_version') or host.get('os_release')}",
        "python": env.get("python"),
        "key_packages": env.get("key_packages") or {},
        "seeds": [c["seed"] for c in full],
        "run_wall_seconds": (rep.get("repro") or {}).get("run_wall_seconds"),
        "wall_seconds": (rep.get("repro") or {}).get("wall_seconds"),
    }
    if k.get("stats"):
        s = k["stats"]
        out["measured"] = round(s["mean"], 6)
        out["values"] = [round(v["value_on_claim_scale"], 6) for v in k["measured"]]
        if s.get("std") is not None:
            out["std"] = round(s["std"], 6)
    if k["verdict"] == "could_not_run":
        out["reason"] = k.get("reason")
        b = k.get("blocking") or {}
        err = (b.get("error") or "").strip().splitlines()
        out["blocked_at"] = f"{b.get('kind')} {b.get('id')}: {b.get('command')}" if b else None
        out["error"] = err[-1][:300] if err else None
        if b.get("kind") == "env":
            failure = env.get("failure") or {}
            out["error"] = (failure.get("error") or "").strip()[-600:] or out["error"]
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("slugs", nargs="+")
    p.add_argument("--workspace", default=str(Path.home() / "paper-repro-vet"))
    p.add_argument("--keep-env", action="store_true", help="keep each study's env/ afterwards")
    p.add_argument("--min-free-gb", type=float, default=3.0, help="stop when less disk is free")
    p.add_argument("--dry-run", action="store_true", help="print, do not write gallery.yaml")
    args = p.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    from paper_repro.repro import repro

    data = yaml.safe_load(GALLERY.read_text(encoding="utf-8"))
    for slug in args.slugs:
        free = shutil.disk_usage(
            args.workspace if Path(args.workspace).exists() else Path.home()
        ).free
        if free < args.min_free_gb * 2**30:
            print(
                f"stopping before {slug}: {free / 2**30:.1f} GB free, under {args.min_free_gb} GB"
            )
            return 1
        entry = next(e for e in data["papers"] if e["slug"] == slug)
        out = repro(slug, workspace=args.workspace, progress=print)
        rep = json.loads(Path(out["report_json"]).read_text(encoding="utf-8"))
        vetted = vetted_from_report(rep)
        vetted["study"] = Path(out["study"]).name
        lock = Path(out["study"]) / "lock.txt"
        if lock.exists():
            pins = dict(
                line.split("==", 1)
                for line in lock.read_text(encoding="utf-8").splitlines()
                if "==" in line
            )
            vetted["key_packages"] = {n: pins[n] for n in KEY_PACKAGES if n in pins}
        if not args.keep_env:
            # Envs are rebuilt from lock.txt when needed; the evidence, runs and card stay.
            shutil.rmtree(Path(out["study"]) / "env", ignore_errors=True)
            shutil.rmtree(Path(out["study"]) / "env.prev", ignore_errors=True)
        print(yaml.safe_dump({"vetted": vetted}, sort_keys=False, allow_unicode=True))
        entry["vetted"] = vetted
        if not args.dry_run:
            GALLERY.write_text(
                HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
                encoding="utf-8",
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
