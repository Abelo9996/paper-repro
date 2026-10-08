# Reproduction report: Diego999/pyGAT

**Reproduced: final accuracy claimed the range 84.2 to 85.3, measured 84.3667% (mean of 3 runs).**

| | |
|---|---|
| Repository | https://github.com/Diego999/pyGAT |
| Commit | `3664f2dc90cbf971564c0bf186dc794f12446d0c` (2021-08-14) |
| Machine | macOS 26.2 arm64, Apple M4, 16.0 GB RAM |
| Python | 3.12.13 |
| Commands | 4 run, 4 exited 0, 49m 23s total |
| Generated | 2026-10-08 12:01:26 UTC by paper-repro 0.1.0 |

## Reproduced: final accuracy (k1)

The claim, from README.md, line 24:

> ...The final accuracy is between 84.2 and 85.3 (obtained on 5 different runs).

| Value | On claim's scale | Run | Source |
|---|---|---|---|
| 0.842 | 84.2 | r2 | runs/r2/stdout.txt:840 `Test set results: loss= 0.6498 accuracy= 0.8420` |
| 0.847 | 84.7 | r3 | runs/r3/stdout.txt:816 `Test set results: loss= 0.6599 accuracy= 0.8470` |
| 0.842 | 84.2 | r4 | runs/r4/stdout.txt:834 `Test set results: loss= 0.6671 accuracy= 0.8420` |

How the verdict was reached:

- Claim: final accuracy the range 84.2 to 85.3 (README.md line 24).
- Measured values are fractions and the claim is in percent (or the reverse); values were rescaled by 100 before comparing.
- Measured over 3 runs: mean 84.3667, std 0.288675, min 84.2, max 84.7.
- The measured mean lies inside the claimed range.
- Tolerance: ±0.1 absolute. Close band: ±1.
- Why this tolerance: Cora's test split has 1000 nodes, so accuracy moves in steps of 0.1 points; the claim is already a range over 5 runs, so the band around it is one test node.
- The spread across runs (std 0.288675) is larger than the tolerance, so this verdict depends on which seeds were run.

## Commands

| # | Command | Scope | Seed | Exit | Wall time | Peak memory |
|---|---|---|---|---|---|---|
| r1 | `python train.py --epochs 2` | smoke |  | 0 | 9.6s | 1380 MB |
| r2 | `rm -f *.pkl && python train.py --seed 72` | full | 72 | 0 | 15m 45s | 1786 MB |
| r3 | `rm -f *.pkl && python train.py --seed 1` | full | 1 | 0 | 13m 58s | 1302 MB |
| r4 | `rm -f *.pkl && python train.py --seed 2` | full | 2 | 0 | 19m 30s | 1312 MB |

- r1: 2 epochs to check that the code runs on current numpy, scipy and torch
- r2: README master-branch configuration (train.py defaults), seed 72; checkpoints left by the previous run removed first
- r3: README master-branch configuration (train.py defaults), seed 1; checkpoints left by the previous run removed first
- r4: README master-branch configuration (train.py defaults), seed 2; checkpoints left by the previous run removed first

Full stdout and stderr for each command are in `runs/<id>/`, with SHA-256 hashes recorded in `evidence.jsonl`. Commands ran inside the study's virtual environment, from the repo root.

## Environment

- Status: ok
- Python 3.12.13, built with uv 0.12.5 (210d1f678 2026-08-14 aarch64-apple-darwin)
- Installed from: requirements.txt
- Resolved packages: 12 (`lock.txt`, sha256 `4de0890b852e18b6...`)
- Key packages: numpy 2.5.3, scipy 1.18.1, torch 2.14.1

Earlier attempts (2), kept in the log:

- e1: failed at create venv: `uv venv --quiet --python 3.5 <study>/env`
  `error: Invalid version request: Python <3.6 is not supported but 3.5 was requested.`
- e2: failed at install requirements.txt: `uv pip install --python <study>/env/bin/python -r <repo>/requirements.txt`
  `Because there is no version of torch==0.4.1.post2 and you require torch==0.4.1.post2, we can conclude that your requirements are unsatisfiable.`

## Deviations from the authors' setup

- [e3] Python 3.12 used; the repo asks for 3.5 (README.md:34).
- [e3] Removed version pins from requirements.txt (e3-unpinned-requirements.txt); resolved versions are in lock.txt and may not match what the authors used.

## Notes

- The run used the authors' training loop unchanged: early stopping on validation loss with patience 100, then test accuracy of the best checkpoint. Each command first deletes *.pkl checkpoints left by the previous run, because train.py globs for them in the working directory.

## What was not checked

- The repo mentions GPUs or CUDA (10 CUDA-specific code or dependency lines, 2 device-availability checks or device flags, 3 README lines mentioning GPUs); this run was on macOS arm64 (Apple M4). Numerical results can differ across hardware and kernels.
- Whether the code matches the method described in the paper was not checked; this report only compares the code's output with the stated number.
- The README's range comes from 5 runs; 3 seeds were run here (72, the default, plus 1 and 2) because each run took 14 to 20 minutes on this CPU.
- The sparse variant (--sparse) and the similar_impl_tensorflow branch (README: about 83.0 in under a minute) were not run.
- The authors used PyTorch 0.4.1 on a GPU; this run used PyTorch 2.14.1 on CPU with unpinned numpy and scipy (see lock.txt). The README's timing claims (0.9 s per epoch on a Titan Xp) were not compared.

## Evidence

`evidence.jsonl` holds 14 hash-chained entries; head `0de1918251b58d68...`. Chain check: ok. Run `paper-repro verify --study <dir>` to recheck the chain and the output-file hashes.
