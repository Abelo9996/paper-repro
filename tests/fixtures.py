"""Build tiny fixture repos on disk. Everything is stdlib-only so tests stay offline."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

TRAIN = """\
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--epochs", type=int, default=3)
args = parser.parse_args()

for epoch in range(1, args.epochs + 1):
    print(f"epoch {epoch} loss {1.0 / epoch:.4f} train_acc={0.5 + 0.05 * epoch:.3f}")

acc = ACTUAL + (args.seed % 3 - 1) * 0.002
print(f"test accuracy: {acc:.4f}")
with open("results.json", "w") as fh:
    json.dump({"test": {"accuracy": acc, "n": 400}}, fh)
"""


def make_repo(
    root: Path, *, claimed: str, actual: float, requirements: str = "", git: bool = True
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        textwrap.dedent(
            f"""\
            # Tiny classifier

            Runs on a CPU in a second. Our model reaches a test accuracy of {claimed} on the toy set.

            | Model | Accuracy |
            |-------|----------|
            | ours  | {float(claimed) * 100:.1f}% |
            | baseline | 61.0% |

            ## Usage

            ```bash
            pip install -r requirements.txt
            python train.py --seed 0
            ```

            Data comes from https://example.org/data/toy.zip (not needed for this demo).
            """
        ),
        encoding="utf-8",
    )
    (root / "train.py").write_text(TRAIN.replace("ACTUAL", repr(actual)), encoding="utf-8")
    (root / "requirements.txt").write_text(requirements or "# stdlib only\n", encoding="utf-8")
    if git:
        for cmd in (
            ["git", "init", "--quiet"],
            ["git", "add", "-A"],
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.org",
                "commit",
                "--quiet",
                "-m",
                "fixture",
            ],
        ):
            subprocess.run(cmd, cwd=root, check=True, capture_output=True)
    return root
