# paper-repro

Point your agent at a paper's code; it gets it running and tells you whether the headline number reproduces, with the evidence.

```bash
uvx paper-repro setup --yes        # register the MCP server and skill with Claude Code, Codex, Cursor
# then ask your agent: "Does github.com/karpathy/nanoGPT reproduce its CPU val loss of 1.88?"
uvx paper-repro inspect https://github.com/karpathy/nanoGPT   # or drive it yourself from the CLI
```

> Not on PyPI yet. Until the first release, run it straight from GitHub by replacing `uvx paper-repro` with
> `uvx --from git+https://github.com/Abelo9996/paper-repro paper-repro`. `setup` registers `uvx paper-repro mcp`, so it works once the
> package is on PyPI.

Papers with Code went offline on 24 July 2025, taking its 79,817 paper-to-code links with it
([shutdown record](https://www.codesota.com/papers-with-code/shutdown)). There's no common place
that tracks whether a paper's released code actually reproduces the numbers in the paper. Research benchmarks for this exist (CORE-Bench, PaperBench), but they score agents,
not papers. paper-repro is the user-facing half: it gives a coding agent reliable operations to
clone a repo, build its environment, run it, pull numbers out of the logs and compare them with
the claim, and it writes everything down so a person can check the verdict without trusting
the agent.

## Example output

A real run on this machine (Apple M4, macOS, CPU only) against
[karpathy/nanoGPT](https://github.com/karpathy/nanoGPT) at commit `3adf61e`. Its README says the
small CPU configuration of the Shakespeare character model "gets us a loss of only 1.88". The full
evidence bundle is in [examples/nanogpt-shakespeare-char-cpu](examples/nanogpt-shakespeare-char-cpu/report.md).

```text
$ paper-repro inspect https://github.com/karpathy/nanoGPT
claimed numbers (12):
  c1: best validation loss = 1.4697  (README.md:51)
  c2: loss = 1.88  (README.md:88)
  c3: loss = 2.85  (README.md:121)
  ...
$ paper-repro env --python 3.12 --from-readme
$ paper-repro run --scope setup -- python data/shakespeare_char/prepare.py
$ paper-repro run -- "python train.py config/train_shakespeare_char.py --device=cpu --compile=False --eval_iters=20 ..."
r3: exit 0 in 236.5s, peak memory 194.6 MB, 1 files written
$ paper-repro metrics --run r3 --run r4 --name val_loss
$ paper-repro compare --claim c2 --measured 'm1:val_loss:last@each' --why '...'
k1: REPRODUCED
Reproduced: loss claimed 1.88, measured 1.8857 (mean of 2 runs).
  - Claim: loss 1.88 (README.md line 88).
  - Measured over 2 runs: mean 1.8857, std 0, min 1.8857, max 1.8857.
  - Distance from the claim: 0.0057 (0.3% of the claim).
  - The measured value is worse than claimed (higher, and lower is better for this metric).
  - Tolerance: ±0.0188 (1% of the claimed value, default). Close band: ±0.0564.
```

The report also lists what was not checked: the A100 claim (1.4697), the GPT-2 numbers, the
checksums of downloaded data, and that the seed is hard-coded, so the two runs measure
determinism (identical losses at every eval step) rather than seed variance.

## How it works

paper-repro is a recorder, not a brain. It never calls a model. Your agent (Claude Code, Codex,
Cursor) decides what to run; paper-repro does it the same way every time and keeps the receipts.

| Step | What it does | Tools it drives |
|---|---|---|
| `inspect` | Shallow-clones the repo (or copies a local path), records the commit SHA, finds dependency files, Python version hints, README commands and `pip install` lines, entry points and their flags, data and weight downloads, GPU hints, and every number the README claims (table cells, sentences, ranges, `±` values), each with file and line. | `git` |
| `env` | Creates an isolated virtualenv per study and installs the repo's own dependency file with pins as written. Conda `environment.yml` files are translated to pip. `--unpin`, `--extra`, `--from-readme` and a different Python are allowed but recorded as deviations. Writes `lock.txt` from `uv pip freeze`. On failure, records the exact error. | `uv venv`, `uv pip` |
| `run` | Runs one shell command from the repo root inside that env. Captures stdout and stderr to files with SHA-256, exit code, wall time, CPU time, peak memory, every file created or modified, and a copy of small result files as they were when the run ended. Timeout kills the whole process tree. Each run is labeled `full`, `shortened` (needs a note saying what was cut), `smoke` or `setup`. | your shell, POSIX rlimits |
| `metrics` | Extracts values like `accuracy: 0.913`, `acc=91.3%`, `F1 81.2`, `val loss 1.8857`, `Accuracy: 9897/10000`, plus JSON, JSON lines and CSV results, each with its source file, line and text. Select one with `m1:val_loss:last`, or one per run with `m1:val_loss:last@each`. | |
| `compare` | Puts measured values next to the claim and gives one of four verdicts: **reproduced**, **close**, **not reproduced**, **could not run**. Handles percent versus fraction, ranges, `±`, repeated runs (mean, std, min, max) and the rounding of the stated value. Default tolerance is 1% relative, close band 3x that; pass your own with a reason. A shortened run or a hand-typed value never counts as a reproduction. | |
| `report` | Writes `report.md` (the shareable artifact) and `report.json` from the evidence log only: repo URL and commit, machine, Python and key package versions, every command with exit code and duration, the claim, measured values with source lines, the reasoning, deviations, and what was not checked. | |

Every step appends to `evidence.jsonl`, a hash-chained log. `paper-repro verify` rechecks the
chain and the hashes of captured outputs, so an edited log or a swapped stdout file shows up.

A study directory looks like this:

```
paper-repro-runs/karpathy-nanoGPT/
  repo/            the checkout
  env/             the virtualenv
  runs/r3/         stdout.txt, stderr.txt, files/ (results as the run left them)
  lock.txt         resolved packages
  evidence.jsonl   the log everything else is derived from
  report.md        the verdict and evidence, for people
  report.json      the same, for programs
```

`paper-repro report --bundle DIR` copies the shareable parts (no checkout, no env) to `DIR`.

### CLI

The second example, [examples/pygat-cora](examples/pygat-cora/report.md), was produced with
these commands against [Diego999/pyGAT](https://github.com/Diego999/pyGAT), whose README says
"The final accuracy is between 84.2 and 85.3 (obtained on 5 different runs)":

```bash
paper-repro inspect Diego999/pyGAT
paper-repro env                      # fails: README asks for Python 3.5, which uv does not support
paper-repro env --python 3.12        # fails: torch==0.4.1.post2 has no wheel for this machine
paper-repro env --python 3.12 --unpin
paper-repro run --scope smoke --note "2 epochs ..." -- python train.py --epochs 2
paper-repro run --seed 72 --timeout 10800 --note "..." -- "rm -f *.pkl && python train.py --seed 72"
paper-repro run --seed 1 ...  &&  paper-repro run --seed 2 ...
paper-repro metrics --run r2 --run r3 --run r4 --name accuracy
paper-repro compare --claim c1 --measured 'm1:accuracy:last@each' --tol 0.1 --close-tol 1.0 \
  --why "Cora's test split has 1000 nodes, so accuracy moves in steps of 0.1 points; ..."
paper-repro note --kind not_checked "The README's range comes from 5 runs; 3 seeds were run here ..."
paper-repro report --bundle examples/pygat-cora
```

Result: test accuracy 84.2, 84.7 and 84.2 over three seeds, mean 84.37, inside the claimed range,
verdict reproduced. Both failed environment attempts, the Python and unpinning deviations, and
the fact that only 3 of the authors' 5 runs were repeated are all in the report.

Every subcommand takes `--json`. `paper-repro status` shows what a study has recorded so far.

## Setup for agents

```bash
uvx paper-repro setup          # shows what it would change, asks before applying
uvx paper-repro setup --yes    # apply without asking
```

It detects each agent and, for the ones present:

- Claude Code: `claude mcp add --scope user paper-repro -- uvx paper-repro mcp`, and copies the
  skill to `~/.claude/skills/paper-repro/SKILL.md`. Use `--project DIR` to write a project
  `.mcp.json` instead.
- Codex: adds `[mcp_servers.paper-repro]` to `~/.codex/config.toml` and copies the skill to
  `~/.codex/skills/paper-repro/`.
- Cursor: adds `paper-repro` to `mcpServers` in `~/.cursor/mcp.json`.

It backs up any file it edits (`*.bak-paper-repro-<time>`) and does nothing on a second run.
Manual registration is the same command everywhere: `uvx paper-repro mcp` over stdio.

The skill ([skills/paper-repro/SKILL.md](skills/paper-repro/SKILL.md)) is the workflow the agent
follows: inspect, pick one claim and say why, check feasibility, set up the env with the
least invasive fix, run the smallest faithful configuration first, extract, compare with a
tolerance it can defend, report. It also sets the rules: never fabricate or estimate a number,
never change the method to make a run succeed, and report "could not run" with the blocking
error instead of pushing through.

## What it can't do

- It does not judge whether the code implements the method in the paper. It checks the code's
  output against a stated number, nothing more.
- No GPU orchestration. On a machine without the GPU the paper used, GPU-only claims end as
  "could not run" or as shortened CPU runs that never count as reproductions.
- No container builds yet. A Dockerfile is detected and reported but not built; environments
  are Python virtualenvs. R, Julia and other languages are detected but `env` only builds
  Python environments (you can still `run` commands that use a system R or Julia).
- Conda environments are translated to pip, which can resolve different builds than conda
  would. The translation is recorded as a deviation.
- Claim detection reads the README (and other Markdown in the repo), not the paper PDF. Numbers
  that only appear in the paper must be added with `paper-repro claim --source "paper Table 2"`.
- Metric extraction is pattern-based. Unusual log formats may need `--file` on a results file or
  a careful choice among the extracted values; the report always shows the exact source line.
- Memory limits are only enforced on Linux; on macOS peak memory is recorded but not capped.
- The default tolerance (1% relative) is a convention, not a statistical test. Choose one per
  claim and say why.

## Privacy and safety

Everything runs on your machine. paper-repro sends nothing anywhere and has no telemetry. The
only network traffic is what you ask for: `git clone`, `uv` downloading packages, and whatever
the repository's own scripts download.

That last part matters: running a paper's code means running a stranger's code with your
user's permissions. paper-repro isolates the Python environment and can cap time and CPU, but
it is not a sandbox. For code you do not trust, run it inside a VM or a disposable container.

## License

MIT, see [LICENSE](LICENSE).
