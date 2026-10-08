# Reproduction report: karpathy/nanoGPT

**Reproduced: loss claimed 1.88, measured 1.8857 (mean of 2 runs).**

| | |
|---|---|
| Repository | https://github.com/karpathy/nanoGPT |
| Commit | `3adf61e154c3fe3fca428ad6bc3818b27a3b8291` (2025-11-12) |
| Machine | macOS 26.2 arm64, Apple M4, 16.0 GB RAM |
| Python | 3.12.13 |
| Commands | 4 run, 4 exited 0, 8m 38s total |
| Generated | 2026-10-08 10:58:49 UTC by paper-repro 0.1.0 |

## Reproduced: loss (k1)

The claim, from README.md, line 88:

> ...This still runs in about ~3 minutes, but gets us a loss of only 1.88 and therefore also worse samples, but it's still good fun:

| Value | On claim's scale | Run | Source |
|---|---|---|---|
| 1.8857 | 1.8857 | r3 | runs/r3/stdout.txt:2074 `step 2000: train loss 1.7648, val loss 1.8857` |
| 1.8857 | 1.8857 | r4 | runs/r4/stdout.txt:2074 `step 2000: train loss 1.7648, val loss 1.8857` |

How the verdict was reached:

- Claim: loss 1.88 (README.md line 88).
- Measured over 2 runs: mean 1.8857, std 0, min 1.8857, max 1.8857.
- Distance from the claim: 0.0057 (0.3% of the claim).
- The measured value is worse than claimed (higher, and lower is better for this metric).
- Tolerance: ±0.0188 (1% of the claimed value, default). Close band: ±0.0564.
- Why this tolerance: The README states 1.88 informally ("a loss of only 1.88") for this CPU configuration, and evaluation averages only 20 batches (--eval_iters=20), so a 1% relative band is used rather than the 2-decimal rounding.

## Commands

| # | Command | Scope | Seed | Exit | Wall time | Peak memory |
|---|---|---|---|---|---|---|
| r1 | `python data/shakespeare_char/prepare.py` | setup |  | 0 | 1.7s | 61 MB |
| r2 | `python train.py config/train_shakespeare_char.py --device=cpu --compile=False --eval_iters=2 --log_interval=1 --block_size=64 --batch_size=12 --n_layer=4 --n_head=4 --n_embd=128 --max_iters=10 --lr_decay_iters=10 --dropout=0.0` | smoke |  | 0 | 24.0s | 281 MB |
| r3 | `python train.py config/train_shakespeare_char.py --device=cpu --compile=False --eval_iters=20 --log_interval=1 --block_size=64 --batch_size=12 --n_layer=4 --n_head=4 --n_embd=128 --max_iters=2000 --lr_decay_iters=2000 --dropout=0.0` | full |  | 0 | 3m 56s | 195 MB |
| r4 | `python train.py config/train_shakespeare_char.py --device=cpu --compile=False --eval_iters=20 --log_interval=1 --block_size=64 --batch_size=12 --n_layer=4 --n_head=4 --n_embd=128 --max_iters=2000 --lr_decay_iters=2000 --dropout=0.0` | full |  | 0 | 4m 16s | 196 MB |

- r1: Download and encode tiny shakespeare, as in README.md:40
- r2: 10 iterations to check that training starts on CPU
- r3: README.md:85 CPU command, verbatim
- r4: Same command again. train.py fixes the seed at 1337, so this checks run-to-run determinism, not seed variance

Full stdout and stderr for each command are in `runs/<id>/`, with SHA-256 hashes recorded in `evidence.jsonl`. Commands ran inside the study's virtual environment, from the repo root.

## Environment

- Status: ok
- Python 3.12.13, built with uv 0.12.5 (210d1f678 2026-08-14 aarch64-apple-darwin)
- Resolved packages: 62 (`lock.txt`, sha256 `efb02c44428a5c70...`)
- Key packages: datasets 1.1.1, numpy 2.5.3, tiktoken 0.14.0, torch 2.14.1, tqdm 4.70.1, transformers 5.19.0, wandb 0.30.0

## Deviations from the authors' setup

- [e1] Installed packages named in README.md:22: torch numpy transformers datasets tiktoken wandb tqdm (7 without versions, so the latest compatible releases were used)

## Notes

- The README sentence does not say train or val loss. It follows the paragraph about the noisier evaluation estimate, and the val loss at step 2000 is the value that matches, so val loss was compared. The train loss at step 2000 was 1.7648 in both runs (runs/r3/stdout.txt).
- Both full runs printed identical train and val losses at every evaluation step, so on this CPU the run is deterministic for the seed fixed in train.py (1337). Seed-to-seed variance was not measured because the seed is hard-coded.
- Wall times are not a speed measurement: the full runs shared the CPU with other CPU-bound jobs. The README says this configuration takes about 3 minutes.

## What was not checked

- 11 other numbers found in the README were not compared: best validation loss 1.4697 (README.md:51), loss 2.85 (README.md:121), val loss 3.11 (README.md:121), train loss 3.11 (README.md:151), val loss 3.12 (README.md:151), train loss 2.85 (README.md:152) and 5 more.
- The repo mentions GPUs or CUDA (6 CUDA-specific code or dependency lines, 3 device-availability checks or device flags, 10 README lines mentioning GPUs); this run was on macOS arm64 (Apple M4). Numerical results can differ across hardware and kernels.
- 10 data or weight download references were found; their checksums against the authors' copies were not verified unless a note below says so.
- Whether the code matches the method described in the paper was not checked; this report only compares the code's output with the stated number.
- The GPU claim (best validation loss 1.4697 on one A100, README.md:51, claim c1) needs a CUDA GPU and was not attempted.
- The GPT-2 reproduction and finetuning numbers (c3 to c12) need OpenWebText and multi-GPU training and were not attempted.

## Evidence

`evidence.jsonl` holds 13 hash-chained entries; head `82eaef085dc6d5fa...`. Chain check: ok. Run `paper-repro verify --study <dir>` to recheck the chain and the output-file hashes.
