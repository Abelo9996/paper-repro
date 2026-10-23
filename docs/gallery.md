# Gallery

Papers whose official code was run end to end with `paper-repro repro <slug>` on a CPU
laptop. Each entry pins the commit, Python, environment, command, seeds, metric and claim
(`src/paper_repro/data/gallery.yaml`), so a rerun needs no authoring. Every measured value
below was written by `scripts/vet_gallery.py` from a recorded run; failures and partial
results stay in, with the number or the blocking error.

| Paper | Area | Claim | Measured | Verdict | Runs | Slug |
|---|---|---|---|---|---|---|
| nanoGPT | language modeling | 1.88 | 1.8857 | **REPRODUCED** | 34s | [`nanogpt-shakespeare-char`](#nanogpt-shakespeare-char) |
| Semi-Supervised Classification with Graph Convolutional Networks (PyTorch code) | graph nets | 81.5% | 82.7% (mean of 3, std 0.53) | **PARTIAL** | 11s | [`pygcn-cora`](#pygcn-cora) |
| Semi-Supervised Classification with Graph Convolutional Networks (official TensorFlow code) | graph nets | 81.5% | not measured | **COULD NOT RUN (dependencies do not install)** | none | [`gcn-tf-cora`](#gcn-tf-cora) |
| Simplifying Graph Convolutional Networks | graph nets | 81% | 81.033% (mean of 3, std 0.058) | **REPRODUCED** | 20s | [`sgc-cora`](#sgc-cora) |
| Deep Graph Infomax | graph nets | 82.3 ± 0.6% | not measured | **COULD NOT RUN (GPU required)** | 42s | [`dgi-cora`](#dgi-cora) |
| Simple and Deep Graph Convolutional Networks (GCNII) | graph nets | 85.5% | not measured | **COULD NOT RUN (GPU required)** | 2s | [`gcnii-cora`](#gcnii-cora) |
| Hamiltonian Neural Networks: ideal mass-spring task | physics-informed learning | 0.036 ± 0.002 | 0.037961 (mean of 3, std 0.0022) | **REPRODUCED** | 55s | [`hnn-mass-spring`](#hnn-mass-spring) |
| Hamiltonian Neural Networks: ideal pendulum task | physics-informed learning | 0.036 ± 0.002 | 0.036489 (mean of 3, std 0.00083) | **REPRODUCED** | 26s | [`hnn-pendulum`](#hnn-pendulum) |
| Scaling Down Deep Learning with MNIST-1D | classic vision | 32 ± 1% | 31.6% | **REPRODUCED** | 2m 46s | [`mnist1d-logistic`](#mnist1d-logistic) |
| Bag of Tricks for Efficient Text Classification (fastText) | NLP text classification | 98.6% | not measured | **COULD NOT RUN (data unavailable)** | 6s | [`fasttext-dbpedia`](#fasttext-dbpedia) |
| CleanRL: PPO on CartPole-v1 | reinforcement learning | 490.04 ± 6.12 | 500 (mean of 3) | **REPRODUCED** | 1m 45s | [`cleanrl-ppo-cartpole`](#cleanrl-ppo-cartpole) |
| NGBoost | tabular | 0.2 ± 0.26 | 2.1153 | **NOT REPRODUCED** | 3m 36s | [`ngboost-yacht`](#ngboost-yacht) |

Runs is the wall time of the training runs; end to end adds cloning, the environment and
the paper download. Environments came from a warm uv cache; a cold cache adds the
download time of PyTorch and friends.

## nanogpt-shakespeare-char

**nanoGPT: character-level Shakespeare, the README's CPU configuration**

- Paper: no paper. Code: [karpathy/nanoGPT](https://github.com/karpathy/nanoGPT) at `3adf61e154c3`, Python 3.12.
- Claim: val_loss 1.88 (README:88).
- Command: `python train.py config/train_shakespeare_char.py --device=cpu --compile=False --eval_iters=20 --log_interval=1 --block_size=64 --batch_size=12 --n_layer=4 --n_head=4 --n_embd=128 --max_iters=2000 --lr_decay_iters=2000 --dropout=0.0`
- Setup: `python data/shakespeare_char/prepare.py`
- Verdict: **REPRODUCED**. Reproduced: loss claimed 1.88, measured 1.8857, 0.0057 away, within the tolerance of ±0.0188.
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.12.13, torch 2.14.1, numpy 2.5.4, networkx 3.7. Runs took 34s, 37s end to end (environment from the uv cache).
- Not checked: train.py seeds torch with a fixed 1337, so repeated runs measure determinism, not seed variance; one run is made.
- Rerun: `uvx paper-repro repro nanogpt-shakespeare-char`

## pygcn-cora

**Semi-Supervised Classification with Graph Convolutional Networks (PyTorch code)**

- Paper: [arXiv:1609.02907](https://arxiv.org/abs/1609.02907). Code: [tkipf/pygcn](https://github.com/tkipf/pygcn) at `1600b5b748b3`, Python 3.12.
- Claim: accuracy 81.5% (arXiv:1609.02907 Table 2, row GCN (this paper), column Cora).
- Command: `cd pygcn && python train.py --no-cuda --seed {seed}`, seeds [0, 1, 2]
- Tolerance: ±1. Cora's test set has 1000 nodes, so accuracy moves in steps of 0.1 points and seed noise is several of them.
- Verdict: **PARTIAL**. Partial (close): accuracy claimed 81.5%, measured 82.7% (mean of 3 runs), 1.2 away: outside the tolerance of ±1 but inside the close band of ±3.
- Per run: 82.1, 82.9, 83.1 (seeds [0, 1, 2]).
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.12.13, torch 2.14.1, numpy 2.5.4, scipy 1.18.1, networkx 3.7. Runs took 11s, 13s end to end (environment from the uv cache).
- Not checked: The pygcn README says it is not intended to reproduce the paper's results: it trains on the first 140 nodes in file order, not the paper's split of 20 labels per class. The paper's own code is tkipf/gcn (TensorFlow 1).
- Not checked: The runs are not deterministic on this CPU even with fixed seeds: three repro runs of seeds 0, 1, 2 on this machine gave means of 82.57, 82.7 (the vetted run) and 83.07; each was PARTIAL.
- Rerun: `uvx paper-repro repro pygcn-cora`

## gcn-tf-cora

**Semi-Supervised Classification with Graph Convolutional Networks (official TensorFlow code)**

- Paper: [arXiv:1609.02907](https://arxiv.org/abs/1609.02907). Code: [tkipf/gcn](https://github.com/tkipf/gcn) at `39a4089fe72a`, Python 3.8.
- Claim: test_accuracy 81.5% (arXiv:1609.02907 Table 2, row GCN (this paper), column Cora).
- Command: `cd gcn && python train.py --seed {seed}`, seeds [0]
- Verdict: **COULD NOT RUN (dependencies do not install)**. Could not run (dependencies do not install): accuracy 81.5% was not measured.
- Blocked at env e1: uv pip install --python <study>/env/bin/python -r <repo>/requirements.txt: `Using Python 3.8.20 environment at: /Users/abelyagubyan/paper-repro-vet/gcn-tf-cora/env
  × No solution found when resolving dependencies:
  ╰─▶ Because tensorflow==1.15.4 has no wheels with a matching Python ABI tag
      (e.g., `cp38`) and you require tensorflow==1.15.4, we can conclude that
     `
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.8.20. Runs took 0s, 2s end to end (environment from the uv cache).
- Rerun: `uvx paper-repro repro gcn-tf-cora`

## sgc-cora

**Simplifying Graph Convolutional Networks**

- Paper: [arXiv:1902.07153](https://arxiv.org/abs/1902.07153). Code: [Tiiiger/SGC](https://github.com/Tiiiger/SGC) at `2c7a2727e82e`, Python 3.8.
- Claim: accuracy 81% (README.md:31).
- Command: `python citation.py --dataset cora --tuned --no-cuda --seed {seed}`, seeds [42, 1, 2]
- Tolerance: ±1. Cora's test set has 1000 nodes, so accuracy moves in steps of 0.1 points; the README states one decimal.
- Verdict: **REPRODUCED**. Reproduced: accuracy claimed 81.0%, measured 81.0333% (mean of 3 runs), 0.0333333 away, within the tolerance of ±1.
- Per run: 81, 81.1, 81 (seeds [42, 1, 2]).
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.8.20, torch 2.4.1, numpy 1.24.4, scipy 1.10.1, networkx 1.11, scikit-learn 1.3.2. Runs took 20s, 23s end to end (environment from the uv cache).
- Deviation: requirements.txt does not list PyTorch (the README says PyTorch>=1.0.0), so the latest torch for Python 3.8 was added.
- Rerun: `uvx paper-repro repro sgc-cora`

## dgi-cora

**Deep Graph Infomax**

- Paper: [arXiv:1809.10341](https://arxiv.org/abs/1809.10341). Code: [PetarV-/DGI](https://github.com/PetarV-/DGI) at `61baf67d7052`, Python 3.10.
- Claim: accuracy 82.3 ± 0.6% (arXiv:1809.10341, Table 2 (transductive), row DGI (ours), column Cora: 82.3 ± 0.6).
- Command: `python execute.py`
- Verdict: **COULD NOT RUN (GPU required)**. Could not run (GPU required): accuracy 82.3% was not measured.
- Blocked at run r1: python execute.py: `AssertionError: Torch not compiled with CUDA enabled`
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.10.21, torch 2.14.1, numpy 1.22.4, scipy 1.7.3, networkx 2.6.3. Runs took 42s, 43s end to end (environment from the uv cache).
- Deviation: The repo has no dependency file. It imports scipy.sparse.linalg.eigen.arpack, which newer SciPy removed, so packages from before that change were chosen: Python 3.10, numpy<1.23, scipy<1.8, networkx<2.7 and the latest torch.
- Not checked: execute.py checks torch.cuda.is_available() for pretraining, which finished on the CPU, but then calls .cuda() unconditionally for the logistic-regression evaluation (execute.py:115), so no accuracy was printed.
- Rerun: `uvx paper-repro repro dgi-cora`

## gcnii-cora

**Simple and Deep Graph Convolutional Networks (GCNII)**

- Paper: [arXiv:2007.02133](https://arxiv.org/abs/2007.02133). Code: [chennnM/GCNII](https://github.com/chennnM/GCNII) at `ca91f5686c4c`, Python 3.12.
- Claim: accuracy 85.5% (README.md:24).
- Command: `python -u train.py --data cora --layer 64 --test --seed {seed}`, seeds [42]
- Verdict: **COULD NOT RUN (GPU required)**. Could not run (GPU required): Metric 85.5 was not measured.
- Blocked at run r1: python -u train.py --data cora --layer 64 --test --seed 42: `AssertionError: Torch not compiled with CUDA enabled`
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.12.13, torch 2.14.1, numpy 2.5.4, scipy 1.18.1, networkx 3.7, scikit-learn 1.9.1. Runs took 2s, 4s end to end (environment from the uv cache).
- Deviation: The README asks for CUDA 10.1, Python 3.6.9 and PyTorch 1.3.1 and ships no dependency file; current versions of the packages it imports were installed.
- Rerun: `uvx paper-repro repro gcnii-cora`

## hnn-mass-spring

**Hamiltonian Neural Networks: ideal mass-spring task**

- Paper: [arXiv:1906.01563](https://arxiv.org/abs/1906.01563). Code: [greydanus/hamiltonian-nn](https://github.com/greydanus/hamiltonian-nn) at `bcc362235dc6`, Python 3.12.
- Claim: test loss 0.036 ± 0.002 (arXiv:1906.01563, page 7, Table 1, row 1: Ideal mass-spring, column Test loss HNN (values multiplied by 10^3)).
- Command: `python experiment-spring/train.py --verbose --seed {seed}`, seeds [0, 1, 2]
- Verdict: **REPRODUCED**. Reproduced: test loss claimed the range 0.034 to 0.038, measured 0.037961 (mean of 3 runs), inside the claimed range, within the tolerance of ±0.0005.
- Per run: 0.035915, 0.03762, 0.040348 (seeds [0, 1, 2]).
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.12.13, torch 2.14.1, numpy 2.5.4, scipy 1.18.1, networkx 3.7. Runs took 55s, 1m 02s end to end (environment from the uv cache).
- Deviation: The repo has no dependency file; the packages it imports (torch, numpy, scipy, autograd, imageio) were installed at their latest versions.
- Not checked: The paper's energy metric (HNN .38 ± .1 x 10^-3) is computed in analyze-spring.ipynb and was not run.
- Rerun: `uvx paper-repro repro hnn-mass-spring`

## hnn-pendulum

**Hamiltonian Neural Networks: ideal pendulum task**

- Paper: [arXiv:1906.01563](https://arxiv.org/abs/1906.01563). Code: [greydanus/hamiltonian-nn](https://github.com/greydanus/hamiltonian-nn) at `bcc362235dc6`, Python 3.12.
- Claim: test loss 0.036 ± 0.002 (arXiv:1906.01563, page 7, Table 1, row 2: Ideal pendulum, column Test loss HNN (values multiplied by 10^3)).
- Command: `python experiment-pend/train.py --verbose --seed {seed}`, seeds [0, 1, 2]
- Verdict: **REPRODUCED**. Reproduced: test loss claimed the range 0.034 to 0.038, measured 0.0364887 (mean of 3 runs), inside the claimed range, within the tolerance of ±0.0005.
- Per run: 0.035587, 0.037232, 0.036647 (seeds [0, 1, 2]).
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.12.13, torch 2.14.1, numpy 2.5.4, scipy 1.18.1, networkx 3.7. Runs took 26s, 32s end to end (environment from the uv cache).
- Deviation: The repo has no dependency file; the packages it imports (torch, numpy, scipy, autograd, imageio) were installed at their latest versions.
- Not checked: The paper's energy metric (HNN 25 ± 5 x 10^-3) is computed in analyze-pend.ipynb and was not run.
- Rerun: `uvx paper-repro repro hnn-pendulum`

## mnist1d-logistic

**Scaling Down Deep Learning with MNIST-1D: Table 1, the paper's notebook**

- Paper: [arXiv:2011.14439](https://arxiv.org/abs/2011.14439). Code: [greydanus/mnist1d](https://github.com/greydanus/mnist1d) at `e2f536fa8644`, Python 3.12.
- Claim: test_accuracy 32 ± 1% (arXiv:2011.14439 Table 1, row MNIST-1D (shuffled), column Logistic regression).
- Command: `cd ../nbrun && ipython mnist1d/notebooks/mnist1d-classification.ipynb`
- Setup: `mkdir -p ../nbrun/figures && ln -sfn ../repo ../nbrun/mnist1d`
- Tolerance: ±1. The paper states 32 ± 1 (standard deviation over three runs).
- Verdict: **REPRODUCED**. Reproduced: accuracy claimed 32% ± 1 (treated as 31 to 33), measured 31.6%, inside the claimed range, within the tolerance of ±1.
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.12.13, torch 2.14.1, numpy 2.5.4, scipy 1.18.1, networkx 3.7. Runs took 2m 46s, 2m 50s end to end (environment from the uv cache).
- Deviation: The notebook adds ./mnist1d/notebooks to sys.path and saves figures/benchmark.png, as if run from a directory holding a checkout named mnist1d and a figures folder; it is run from such a directory beside the checkout (a symlink mnist1d -> the checkout, and an empty figures/). ipython, nbformat and torch (from the repo's [all] extra) were installed to run it.
- Deviation: MPLBACKEND=Agg is set so the plotting cells draw off screen instead of waiting on a window (without it the run hung in the first plotting cell after all 8 models had trained).
- Not checked: The notebook trains 8 models; the last value it prints is the logistic regression on shuffled MNIST-1D, the row compared here. The other cells of Table 1 are in the run's stdout but were not compared.
- Rerun: `uvx paper-repro repro mnist1d-logistic`

## fasttext-dbpedia

**Bag of Tricks for Efficient Text Classification (fastText): DBpedia**

- Paper: [arXiv:1607.01759](https://arxiv.org/abs/1607.01759). Code: [facebookresearch/fastText](https://github.com/facebookresearch/fastText) at `1142dc4c4ecb`, Python 3.12.
- Claim: accuracy 98.6% (arXiv:1607.01759, page 3, Table 1, row fastText, h = 10, bigram, column DBP).
- Command: `bash classification-example.sh`
- Verdict: **COULD NOT RUN (data unavailable)**. Could not run (data unavailable): accuracy 98.6% was not measured.
- Blocked at run r1: bash classification-example.sh: `classification-example.sh: line 41: 10556 Abort trap: 6           ./fasttext predict "${RESULTDIR}/dbpedia.bin" "${DATADIR}/dbpedia.test" > "${RESULTDIR}/dbpedia.test.predict"`
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.12.13. Runs took 6s, 7s end to end (environment from the uv cache).
- Not checked: classification-example.sh downloads DBpedia from a Google Drive link that now returns a 2.4 KB HTML page instead of the archive (tar: Unrecognized archive format), so fasttext was trained on an empty file and aborted. The script has no other source for the data.
- Rerun: `uvx paper-repro repro fasttext-dbpedia`

## cleanrl-ppo-cartpole

**CleanRL: PPO on CartPole-v1**

- Paper: [arXiv:2111.08819](https://arxiv.org/abs/2111.08819). Code: [vwxyzjn/cleanrl](https://github.com/vwxyzjn/cleanrl) at `fe8d8a03c41a`, Python 3.10.
- Claim: episodic return 490.04 ± 6.12 (docs/rl-algorithms/ppo.md:111, table of average episodic returns for ppo.py).
- Command: `python cleanrl/ppo.py --env-id CartPole-v1 --seed {seed} --no-cuda --no-track`, seeds [1, 2, 3]
- Tolerance: ±5% relative. CartPole returns are capped at 500 and a single episode is noisy; the docs' 490.04 ± 6.12 is an average over seeds and the last episodes.
- Verdict: **REPRODUCED**. Reproduced: episodic return claimed 490.04, measured 500 (mean of 3 runs), 9.96 away, within the tolerance of ±24.502.
- Per run: 500, 500, 500 (seeds [1, 2, 3]).
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.10.21, torch 2.4.1, numpy 2.2.6, networkx 3.4.2, gymnasium 0.29.1. Runs took 1m 45s, 1m 50s end to end (environment from the uv cache).
- Not checked: The docs report a smoothed average return over 3 seeds; this compares the return of the last finished training episode of each of 3 seeds, a noisier quantity.
- Rerun: `uvx paper-repro repro cleanrl-ppo-cartpole`

## ngboost-yacht

**NGBoost: Natural Gradient Boosting for Probabilistic Prediction, UCI Yacht**

- Paper: [arXiv:1910.03225](https://arxiv.org/abs/1910.03225). Code: [stanfordmlgroup/ngboost](https://github.com/stanfordmlgroup/ngboost) at `d03c7a126ff1`, Python 3.8.
- Claim: NLL 0.2 ± 0.26 (arXiv:1910.03225, page 7, Table 1, row Yacht, column NGBoost: 0.20 ± 0.26).
- Command: `python -m examples.experiments.regression_exp --dataset=yacht --score=MLE --natural`
- Verdict: **NOT REPRODUCED**. Not reproduced: NLL claimed 0.20 ± 0.26 (treated as -0.06 to 0.46), measured 2.1153, 1.6553 away, beyond the close band of ±0.015.
- Vetted 2026-10-23 with paper-repro 0.2.0 on Apple M4, macOS 26.2, Python 3.8.20, numpy 1.24.4, scipy 1.10.1, scikit-learn 1.3.2. Runs took 3m 36s, 3m 40s end to end (environment from the uv cache).
- Deviation: Pinned to d03c7a1 (2020-08-26), the last commit before 'clean up in examples folder' (f9fc18f) removed the script's imports of Normal and MLE; at HEAD (6aadc1f) the script stops with NameError: name 'Normal' is not defined (seen in a run on this machine).
- Deviation: requirements.txt pins numpy 1.17.2, scipy 1.3.1 and scikit-learn 0.21.3, which have no wheels for this machine; the ranges in setup.py (numpy>=1.17.2, scipy>=1.3.1, scikit-learn>=0.21.3, ...) were installed instead, on Python 3.8, plus pandas, which the script imports.
- Not checked: The script's last line is `== RMSE GBM=... NGB=..., NLL NGB=<mean> +/ <std>`; the value compared is the last `NGB=`, which is the mean test NLL over the 20 splits.
- Not checked: The 20 train/test splits are seeded (np.random.seed(1)) but the inner validation split is not, so reruns can differ slightly.
- Not checked: The NLL spread over the 20 splits is large (the script prints the std next to the mean); a few splits with a very poor NLL pull the mean up. Library versions are 2026 releases within setup.py's ranges, not the 2019 pins.
- Rerun: `uvx paper-repro repro ngboost-yacht`
