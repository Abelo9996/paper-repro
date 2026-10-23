# paper-repro

Point your agent at a paper. It reruns the claim and gives you a verdict with receipts, or tells
you exactly why it couldn't.

```bash
uvx paper-repro repro 2011.14439        # an arXiv id, a gallery slug, or a GitHub repo
```

That one command finds the paper's official code, pins the commit, builds the environment, runs
the authors' own command, reads the number, compares it with the paper's table cell, writes a
hash-chained evidence log and a report, and renders a card. Real output on an Apple M4 laptop,
CPU only (paper-repro 0.2.0, trimmed):

```text
$ uvx paper-repro repro 2011.14439
resolve  arXiv:2011.14439: looking for the official code (arXiv page, then the PDF)
         Scaling Down Deep Learning with MNIST-1D
         -> greydanus/mnist1d (linked in the paper)
            paper page 1 (link): https://github.com/greydanus/mnist1d/blob/master/notebooks/building-mnist1d.ipynb
inspect  greydanus/mnist1d @ e2f536f (gallery recipe mnist1d-logistic)
paper    arXiv:2011.14439: 13 numbers read
claim    p7: accuracy = 32 ± 1% [MNIST-1D (shuffled) | Logistic regression] (arXiv:2011.14439, page 2, Table 1)
env      building with uv (python 3.12)
         e1 ok: python 3.12.13, 54 packages
setup    r1: mkdir -p ../nbrun/figures && ln -sfn ../repo ../nbrun/mnist1d -> exit 0 in 0.0s
run      r2: exit 0 in 2m 43s, peak memory 498.8 MB
metrics  m1: test_accuracy last 31.6 (48 values)
verdict  REPRODUCED
         Reproduced: accuracy claimed 32% ± 1 (treated as 31 to 33), measured 31.6%, inside the claimed range, within the tolerance of ±1.
verify   ok: 12 hash-chained entries, head ef88aa48176a5ab3
time: 163s in runs, 167s end to end
badge for a README: [![paper-repro: REPRODUCED](https://img.shields.io/badge/paper--repro-REPRODUCED%2031.6%25%20vs%2032%20%C2%B1%201%25-1f7a3a)](https://github.com/Abelo9996/paper-repro/blob/main/docs/gallery.md#mnist1d-logistic)
```

The run is the paper's own notebook, the one its Table 1 links to, executed unchanged. The card
it wrote (`card.png` and `card.svg`, 1200x630):

![paper-repro verdict card for MNIST-1D](https://raw.githubusercontent.com/Abelo9996/paper-repro/main/docs/card-mnist1d-logistic.png)

Anyone can check it with the command on the card. A repo owner can paste the badge line into
their README.

## Verdicts

| Verdict | Meaning |
|---|---|
| **REPRODUCED** | The repo's own command produced a number within tolerance of the claim. |
| **PARTIAL** | Outside the tolerance but inside the close band (3x the tolerance by default). |
| **NOT REPRODUCED** | Further off than that. |
| **REIMPLEMENTED** (numbers match, close or differ) | The number came from a command or script the agent wrote, not one the repo ships. Inline `python -c` and untracked or modified scripts are detected automatically. Never shown as REPRODUCED. |
| **INCONCLUSIVE** (reduced-scale smoke check, shortened run) | Only a cut-down run was made; it cannot confirm or refute the claim. |
| **COULD NOT RUN** (GPU required, data unavailable, dependencies do not install, ...) | Nothing was measured, and the reason is read from the step that failed. |

## Gallery

Papers with a pinned recipe (commit, Python, environment, command, seeds, metric, claim), so
`paper-repro repro <slug>` needs no authoring. Each was run here on an Apple M4 (macOS 26.2,
CPU only), and every number below comes from that recorded run. Failures stay in. Details,
versions and deviations for each: [docs/gallery.md](docs/gallery.md).

<!-- gallery:start -->
| Paper | Area | Claim | Measured | Verdict | Runs | Slug |
|---|---|---|---|---|---|---|
| nanoGPT | language modeling | 1.88 | 1.8857 | **REPRODUCED** | 34s | [`nanogpt-shakespeare-char`](docs/gallery.md#nanogpt-shakespeare-char) |
| Semi-Supervised Classification with Graph Convolutional Networks (PyTorch code) | graph nets | 81.5% | 82.7% (mean of 3, std 0.53) | **PARTIAL** | 11s | [`pygcn-cora`](docs/gallery.md#pygcn-cora) |
| Semi-Supervised Classification with Graph Convolutional Networks (official TensorFlow code) | graph nets | 81.5% | not measured | **COULD NOT RUN (dependencies do not install)** | none | [`gcn-tf-cora`](docs/gallery.md#gcn-tf-cora) |
| Simplifying Graph Convolutional Networks | graph nets | 81% | 81.033% (mean of 3, std 0.058) | **REPRODUCED** | 20s | [`sgc-cora`](docs/gallery.md#sgc-cora) |
| Deep Graph Infomax | graph nets | 82.3 ± 0.6% | not measured | **COULD NOT RUN (GPU required)** | 42s | [`dgi-cora`](docs/gallery.md#dgi-cora) |
| Simple and Deep Graph Convolutional Networks (GCNII) | graph nets | 85.5% | not measured | **COULD NOT RUN (GPU required)** | 2s | [`gcnii-cora`](docs/gallery.md#gcnii-cora) |
| Hamiltonian Neural Networks: ideal mass-spring task | physics-informed learning | 0.036 ± 0.002 | 0.037961 (mean of 3, std 0.0022) | **REPRODUCED** | 55s | [`hnn-mass-spring`](docs/gallery.md#hnn-mass-spring) |
| Hamiltonian Neural Networks: ideal pendulum task | physics-informed learning | 0.036 ± 0.002 | 0.036489 (mean of 3, std 0.00083) | **REPRODUCED** | 26s | [`hnn-pendulum`](docs/gallery.md#hnn-pendulum) |
| Scaling Down Deep Learning with MNIST-1D | classic vision | 32 ± 1% | 31.6% | **REPRODUCED** | 2m 46s | [`mnist1d-logistic`](docs/gallery.md#mnist1d-logistic) |
| Bag of Tricks for Efficient Text Classification (fastText) | NLP text classification | 98.6% | not measured | **COULD NOT RUN (data unavailable)** | 6s | [`fasttext-dbpedia`](docs/gallery.md#fasttext-dbpedia) |
| CleanRL: PPO on CartPole-v1 | reinforcement learning | 490.04 ± 6.12 | 500 (mean of 3) | **REPRODUCED** | 1m 45s | [`cleanrl-ppo-cartpole`](docs/gallery.md#cleanrl-ppo-cartpole) |
| NGBoost | tabular | 0.2 ± 0.26 | 2.1153 | **NOT REPRODUCED** | 3m 36s | [`ngboost-yacht`](docs/gallery.md#ngboost-yacht) |
<!-- gallery:end -->

Seeds, per-run values and the exact errors are in [docs/gallery.md](docs/gallery.md).
`paper-repro gallery` lists the same table in a terminal.

Three of these were also run with `uvx --from . paper-repro repro <slug>` from a fresh shell
for 0.2.0: `nanogpt-shakespeare-char` (REPRODUCED, 1.8857 vs 1.88, 35s), `sgc-cora`
(REPRODUCED, 81.03% vs 81.0%, 9s) and `pygcn-cora` (PARTIAL, 83.07% vs 81.5%, 14s). By arXiv id:
`1609.02907` resolves to tkipf/gcn, the code the GCN paper links ("Code to reproduce our
experiments is available at https://github.com/tkipf/gcn"), and ends in COULD NOT RUN because
`tensorflow==1.15.4` has no wheel for this machine; `2010.11929` (ViT) resolves to
google-research/vision_transformer from the arXiv comments and, with no recipe, ends in COULD NOT
RUN (no command that produces the number) after listing the README's commands. Times assume a
warm uv cache.

A paper not in the gallery still works step by step, by your agent or by hand (below). Without
a recipe, `repro` gets as far as it can on its own and stops with the reason, or runs a command
you give it: `paper-repro repro owner/repo --command "python train.py" --claim c3 --metric
accuracy` (add `--authored` if you wrote that command).

Papers with Code went offline on 24 July 2025, taking its 79,817 paper-to-code links with it
([shutdown record](https://www.codesota.com/papers-with-code/shutdown)). There's no common place
that tracks whether a paper's released code actually reproduces the numbers in the paper.
Research benchmarks for this exist (CORE-Bench, PaperBench), but they score agents, not papers.
paper-repro is the user-facing half: it gives a coding agent reliable operations to clone a
repo, build its environment, run it, pull numbers out of the logs and compare them with the
claim (from the README or from the paper itself), and it writes everything down so a person
can check the verdict without trusting the agent.

## Use it with your agent

After `setup`, you don't call paper-repro yourself. Ask your agent a question about a repo and a
number; the skill tells it the workflow and the MCP tools do the work. Two real headless Claude
Code sessions on this machine (Apple M4, CPU only), with nothing but the skill and the MCP server
loaded:

**"Can you check whether tkipf/pygcn reproduces the Cora accuracy reported in the GCN paper?
I'm on a laptop with no GPU."** (paper-repro 0.1.1, 22 turns, about 15 minutes, most of it five
200-epoch training runs)

The pygcn README states no numbers, so the agent read the paper:

```text
inspect_repo  {"source": "tkipf/pygcn"}
scan_paper    {}          -> arXiv:1609.02907 (linked at README.md:31), 32 claims from Table 2
create_env    {"python": "3.11"}
run_command   {"command": "cd pygcn && python train.py --no-cuda --epochs 2", "scope": "smoke"}
run_command   {"command": "cd pygcn && python train.py --no-cuda --seed 42", "scope": "full", ...}
              ... seeds 1, 2, 3, 4
extract_metrics {"run_ids": ["r2", "r3", "r4", "r5", "r6"], "names": ["accuracy"]}
compare_claim {"claim_id": "p26", "measured": ["m1:accuracy:last@each"], "tol": 1, "why": "..."}
  -> Close: accuracy claimed 81.5%, measured 83.34% (mean of 5 runs), 1.84 away: outside the
     tolerance of ±1 but inside the close band of ±3.
write_report  {}
```

From its answer to the user:

> pygcn's Cora accuracy is close to the paper's number, but **not a clean reproduction: it comes
> out about 1.8 points higher**. [...] **Why it doesn't match exactly:** the repo isn't trying to
> match the paper. Its README (line 12) says it "is not intended for reproduction of the results
> reported in [1]." [...] it trains on the first 140 nodes in file order, validates on nodes
> 200-499 and tests on 500-1499 (`pygcn/utils.py:41-43`). The paper uses the standard split with
> 20 labels per class.

**"Does karpathy/nanoGPT actually reproduce the loss of 1.88 its README claims for the small CPU
Shakespeare run?"** (paper-repro 0.1.0, 15 turns, 103 seconds): the agent picked claim `c2`,
built the environment from the README's `pip install` line, prepared the data, did a 5-step
smoke run, then the exact README command (47 seconds), and answered:

> Yes. I ran the README's CPU command exactly as written, and the final val loss was
> **1.8857**, against the README's claimed 1.88. [...] **Train or val loss:** the README says "a
> loss of only 1.88" without saying which. I compared against val loss, since train loss (1.76)
> is well below 1.88.

Both left a `report.md` with the commands, logs, hashes, environment and what was not checked.

## Example output

A real run on this machine (Apple M4, macOS, CPU only) driven from the CLI against
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
Reproduced: loss claimed 1.88, measured 1.8857 (mean of 2 runs), 0.0057 away, within the tolerance of ±0.0188.
  - Claim: loss 1.88 (README.md line 88).
  - Measured over 2 runs: mean 1.8857, std 0, min 1.8857, max 1.8857.
  - Distance from the claim: 0.0057 (0.3% of the claim).
  - The measured value is worse than claimed (higher, and lower is better for this metric).
  - Tolerance: ±0.0188 (1% of the claimed value, default). Close band: ±0.0564.
```

The runs were made with 0.1.0; the `compare` output above is 0.1.1 re-reading the same recorded
runs. The report also lists what was not checked: the A100 claim (1.4697), the GPT-2 numbers, the
checksums of downloaded data, and that the seed is hard-coded, so the two runs measure
determinism (identical losses at every eval step) rather than seed variance.

## How it works

paper-repro is a recorder, not a brain. It never calls a model. Your agent (Claude Code, Codex,
Cursor) decides what to run; paper-repro does it the same way every time and keeps the receipts.

| Step | What it does | Tools it drives |
|---|---|---|
| `inspect` | Shallow-clones the repo (or copies a local path), records the commit SHA, finds dependency files, Python version hints, README commands and `pip install` lines, entry points and their flags, data and weight downloads, GPU hints, and every number the README claims (table cells, sentences, ranges, `±` values), each with file and line. | `git` |
| `paper` | Downloads the paper from arXiv (the one the README links, or any id, URL or local PDF/text file), saves its text, and records the numbers it states as `p1`, `p2`, ... Results tables are rebuilt from word positions: each cell keeps its table, page, exact row and column labels (a two-level header becomes `BLEU EN-DE`) and a confidence with notes. The rebuilt tables are saved as Markdown next to the text. | `pypdf` (text), `pdfminer.six` (word positions) |
| `env` | Creates an isolated virtualenv per study and installs the repo's own dependency file with pins as written. Conda `environment.yml` files are translated to pip. `--unpin`, `--extra`, `--from-readme` and a different Python are allowed but recorded as deviations. Writes `lock.txt` from `uv pip freeze`. On failure, records the exact error. | `uv venv`, `uv pip` |
| `run` | Runs one shell command from the repo root inside that env. Captures stdout and stderr to files with SHA-256, exit code, wall time, CPU time, peak memory, every file created or modified, and a copy of small result files as they were when the run ended. Timeout kills the whole process tree. Each run is labeled `full`, `shortened` (needs a note saying what was cut), `smoke` or `setup`. | your shell, POSIX rlimits |
| `metrics` | Extracts values like `accuracy: 0.913`, `acc=91.3%`, `F1 81.2`, `val loss 1.8857`, `Accuracy: 9897/10000`, plus JSON, JSON lines and CSV results, each with its source file, line and text. Select one with `m1:val_loss:last`, or one per run with `m1:val_loss:last@each`. | |
| `compare` | Puts measured values next to the claim and gives a verdict: **reproduced**, **close** (shown as PARTIAL), **not reproduced**, **reimplemented** (a value came from an agent-written command), **inconclusive** (any value came from a smoke or shortened run), **could not run** (with a reason). Handles percent versus fraction, ranges, `±`, repeated runs (mean, std, min, max) and the rounding of the stated value. Default tolerance is 1% relative, close band 3x that; pass your own with a reason. A shortened run or a hand-typed value never counts as a reproduction. Comparing a claim again supersedes the earlier verdict, which stays in the report. | |
| `report` | Writes `report.md` (the shareable artifact) and `report.json` from the evidence log only: repo URL and commit, machine, Python and key package versions, every command with exit code and duration, the claim, measured values with source lines, the reasoning, deviations, and what was not checked. | |
| `repro` | All of the above in one go, ending in `verify` and a card. Takes a gallery slug (pinned recipe), an arXiv id (resolved to the official repo first) or a repo. Always starts a fresh study. | |
| `card` | Renders `card.png` and `card.svg` (1200x630) and `badge.md` (a shields.io badge) from `report.json`. | Pillow |

Every step prints a `next:` line (a `next` field in JSON and MCP results) with the usual next
step, and every step appends to `evidence.jsonl`, a hash-chained log. `paper-repro verify` rechecks the
chain and the hashes of captured outputs, so an edited log or a swapped stdout file shows up.

A study directory looks like this:

```
paper-repro-runs/karpathy-nanoGPT/
  repo/            the checkout
  env/             the virtualenv
  runs/r3/         stdout.txt, stderr.txt, files/ (results as the run left them)
  lock.txt         resolved packages
  evidence.jsonl   the log everything else is derived from
  paper/           the paper PDF and its extracted text, if you scanned it
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

When the number is only in the paper, `paper-repro paper` reads it. Real output (0.1.2, trimmed)
for the Transformer paper, whose Table 2 has a two-line header (`BLEU` over `EN-DE  EN-FR`):

```text
$ paper-repro paper 1706.03762
paper: arXiv:1706.03762 (15 pages, 39496 characters of text)
file: paper/arxiv-1706.03762.pdf sha256 bdfaa68d8984f0dc
text: paper/arxiv-1706.03762.txt
tables: paper/arxiv-1706.03762.tables.md (3 rebuilt)
claimed numbers (69):
  p1: BLEU = 23.75 [ByteNet | BLEU EN-DE]  (arXiv:1706.03762, page 8, Table 2, high)
  ...
  p16: BLEU = 28.4 [Transformer (big) | BLEU EN-DE]  (arXiv:1706.03762, page 8, Table 2, high)
  p17: BLEU = 41.8 [Transformer (big) | BLEU EN-FR]  (arXiv:1706.03762, page 8, Table 2, high)
  p18: PPL = 4.92 [base | PPL (dev)]  (arXiv:1706.03762, page 9, Table 3, high)
  ...
```

The training-cost columns of that table are not listed (they are not results), and in 0.1.1 the
same cells came out with no column name at all.

### Reading tables from PDFs

pypdf's plain text loses the layout, so `paper` rebuilds each results table from word boxes
(pdfminer.six): it finds the `Table N` caption, takes the tabular lines above or below it within
its page column, places columns by the x-position of the numbers, and names each column from
every header line above it. It handles captions below the table, stacked tables, two-level
headers, section rows ("Ours", "Published"), blank cells that repeat the label above,
`\multirow` labels, `±` spreads, `a/b` cells and drawn column rules. Columns that describe the
setup (depth, params, cost) are not claims; they name rows that would otherwise repeat, as in
`DenseNet (k = 12) (Depth 40)`.

Each claim gets a confidence score from 0 to 1 (high, medium or low) with notes saying what
lowered it, for example "metric named only in the caption" or "row label taken from a
neighbouring row".

Measured on a regression set of 13 tables from 8 arXiv papers, with every expected cell
transcribed by hand from the rendered pages (`tests/data/tables/expected.json`, scored with
`scripts/table_regression.py`). A claim is correct only when its table, row label, column label
and value all match.

| Reader | Tables | Precision | Recall |
|---|---|---|---|
| 0.1.1 (plain text) | 9 dev tables, 212 cells | 76/119 = 0.64 | 76/212 = 0.36 |
| 0.1.2 (word positions) | the same 9 dev tables | 212/212 = 1.00 | 212/212 = 1.00 |
| 0.1.1 (plain text) | 4 held-out tables, 151 cells | 0/2 | 0/151 |
| 0.1.2, first run on held-out | the same 4 tables | 47/141 = 0.33 | 47/151 = 0.31 |
| 0.1.2, after fixing what they showed | the same 4 tables | 150/152 = 0.99 | 150/151 = 0.99 |

The dev tables (Transformer, GCN, GAT, BERT, ResNet) were used while building the reader, so
1.00 there is not an estimate of accuracy on new papers. The held-out tables (ViT, DenseNet,
ELMo) were transcribed before the reader first saw them; the 0.33 is that first, honest number,
and the reader was then fixed against them, so they are no longer held out either. Expect
unseen papers to land somewhere in between, and check medium and low claims.

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
Start a new agent session afterwards so it picks up the server.
Manual registration is the same command everywhere: `uvx paper-repro mcp` over stdio.

The skill ([skills/paper-repro/SKILL.md](skills/paper-repro/SKILL.md)) is the workflow the agent
follows: inspect, pick one claim and say why, check feasibility, set up the env with the
least invasive fix, run the smallest faithful configuration first, extract, compare with a
tolerance it can defend, report. It also sets the rules: never fabricate or estimate a number,
never change the method to make a run succeed, and report "could not run" with the blocking
error instead of pushing through.

## What it can't do

- The gallery is 12 papers, vetted on one machine (an Apple M4, CPU only) in October 2026. A
  verdict there says what happened on that machine with those package versions, nothing more.
  Some code is not deterministic on CPU even with fixed seeds: three runs of pygcn's seeds 0, 1
  and 2 here gave means of 82.57, 82.7 and 83.07. Times assume packages are in the uv cache.
- `repro` without a recipe does not write a command for you. It stops with COULD NOT RUN and
  the README commands it found; an agent (or you, with `--command`) takes it from there.
- Finding the code for an arXiv id trusts links: the arXiv page first, then the PDF, ranked by
  page and by "code is available" wording. A paper that links a baseline's repo more
  prominently than its own can resolve to the wrong one; the output always shows the link it
  used. GitHub search is only a fallback and is labeled as not stated by the authors.
- REIMPLEMENTED is detected from the command line: inline `python -c` code and scripts named in
  the command that git does not track or that were modified. An unmodified repo script that
  imports a module the agent added is not caught; pass `--authored` (MCP `authored=true`).
- GPU-only detection without a recipe looks for `.cuda()` and `"cuda"` devices in Python files
  with no device check anywhere. It can miss GPU-only code and is not a promise that the rest
  runs on a CPU.
- It does not judge whether the code implements the method in the paper. It checks the code's
  output against a stated number, nothing more.
- No GPU orchestration. On a machine without the GPU the paper used, GPU-only claims end as
  "could not run" or as shortened CPU runs that never count as reproductions.
- No container builds yet. A Dockerfile is detected and reported but not built; environments
  are Python virtualenvs. R, Julia and other languages are detected but `env` only builds
  Python environments (you can still `run` commands that use a system R or Julia).
- Conda environments are translated to pip, which can resolve different builds than conda
  would. The translation is recorded as a deviation.
- Claim detection in the README is reliable for tables and plain sentences. Reading the paper
  (`paper-repro paper`) needs a text PDF: scanned pages and tables embedded as images yield
  nothing. Tables need a `Table N:` or `Table N.` caption; rotated tables, tables split over two
  pages and tables whose row labels wrap onto a second line are not handled, and when a cell
  holds two values (`88.4/88.5`) only a header like `MNLI-(m/mm)` or an `a / b` phrase in the
  caption names them. Sentences in the paper are only read for `metric: value` style claims, so
  "a BLEU score of 28.4" in prose is not picked up; the table is. When a claim is wrong or
  missing, add it with `paper-repro claim --source "paper Table 2"`. Only arXiv is fetched
  automatically; for other papers pass a local PDF.
- Metric extraction is pattern-based. Unusual log formats may need `--file` on a results file or
  a careful choice among the extracted values; the report always shows the exact source line.
- Memory limits are only enforced on Linux; on macOS peak memory is recorded but not capped.
- Runs share one checkout. Runs started at the same time get separate ids and records, but their
  timings and written-file lists can mix, and the report says so.
- The default tolerance (1% relative) is a convention, not a statistical test. Choose one per
  claim and say why.

## Privacy and safety

Everything runs on your machine. paper-repro sends nothing anywhere and has no telemetry. The
only network traffic is what you ask for: `git clone`, `uv` downloading packages, the paper PDF
from arxiv.org when you run `paper`, and whatever the repository's own scripts download.

That last part matters: running a paper's code means running a stranger's code with your
user's permissions. paper-repro isolates the Python environment and can cap time and CPU, but
it is not a sandbox. For code you do not trust, run it inside a VM or a disposable container.

## License

MIT, see [LICENSE](LICENSE).
