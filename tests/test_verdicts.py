"""Honest verdict labels: REIMPLEMENTED for agent-written commands, COULD NOT RUN with a reason."""

from pathlib import Path

import pytest

from paper_repro.compare import add_claim, classify_blocking, compare_claim, verdict_label
from paper_repro.inspect_repo import inspect_repo
from paper_repro.metrics import extract_metrics
from paper_repro.report import build_report, render_markdown
from paper_repro.runner import run_command
from paper_repro.study import Study


@pytest.fixture
def study(good_repo):
    s = Study(Path(inspect_repo(str(good_repo))["study"]))
    add_claim(s, metric="accuracy", value=75.0, percent=True, source="paper", value_text="75.0")
    return s


def test_repo_command_that_matches_is_reproduced(study):
    r = run_command(study, "python3 train.py", use_env=False)
    assert r["origin"] == "repo" and r["origin_reason"] is None
    m = extract_metrics(study)["id"]
    k = compare_claim(study, claim_id="u1", measured=[f"{m}:test_accuracy:last"])
    assert k["verdict"] == "reproduced" and verdict_label(k) == "REPRODUCED"
    assert k["counts_as_reproduction"] is True


def test_inline_code_is_reimplemented_never_reproduced(study):
    r = run_command(study, "python3 -c 'print(\"test accuracy: 0.75\")'", use_env=False)
    assert r["origin"] == "authored" and "inline code" in r["origin_reason"]
    m = extract_metrics(study)["id"]
    k = compare_claim(study, claim_id="u1", measured=[f"{m}:test_accuracy:last"])
    assert k["verdict"] == "reimplemented" and k["numbers_alone"] == "reproduced"
    assert verdict_label(k) == "REIMPLEMENTED (numbers match)"
    assert "REPRODUCED" not in verdict_label(k)
    assert k["counts_as_reproduction"] is False
    assert k["headline"].startswith("Reimplemented (numbers match)")


def test_untracked_script_is_detected_as_authored(study):
    (study.repo / "my_eval.py").write_text("print('test accuracy: 0.70')\n")
    r = run_command(study, "python3 my_eval.py", use_env=False)
    assert r["origin"] == "authored" and "not part of the repo" in r["origin_reason"]
    m = extract_metrics(study)["id"]
    k = compare_claim(study, claim_id="u1", measured=[f"{m}:test_accuracy:last"])
    assert verdict_label(k) == "REIMPLEMENTED (numbers differ)"


def test_modified_repo_script_is_authored(study):
    train = study.repo / "train.py"
    train.write_text(train.read_text() + "\nprint('patched')\n")
    r = run_command(study, "python3 train.py", use_env=False)
    assert r["origin"] == "authored" and "modified" in r["origin_reason"]


def test_authored_flag_and_report_rendering(study):
    run_command(study, "python3 train.py", use_env=False, authored=True)
    m = extract_metrics(study)["id"]
    compare_claim(study, claim_id="u1", measured=[f"{m}:test_accuracy:last"])
    rep = build_report(study)
    assert rep["comparisons"][0]["label"] == "REIMPLEMENTED (numbers match)"
    assert rep["commands"][0]["origin"] == "authored"
    md = render_markdown(rep)
    assert "## REIMPLEMENTED (numbers match)" in md
    assert "written by the agent, not the repo" in md


def test_close_is_shown_as_partial(study):
    m = run_command(study, "printf 'test accuracy: 0.76\\n'", use_env=False)
    mid = extract_metrics(study, run_ids=[m["id"]])["id"]
    k = compare_claim(study, claim_id="u1", measured=[f"{mid}:test_accuracy:last"], tol=0.5)
    assert k["verdict"] == "close" and verdict_label(k) == "PARTIAL"
    assert k["headline"].startswith("Partial (close)")


@pytest.mark.parametrize(
    "error,reason",
    [
        ("AssertionError: Torch not compiled with CUDA enabled", "gpu_required"),
        ("RuntimeError: No CUDA GPUs are available", "gpu_required"),
        ("urllib.error.HTTPError: HTTP Error 404: Not Found", "data_unavailable"),
        ("FileNotFoundError: [Errno 2] No such file or directory: 'data/cora'", "data_unavailable"),
        ("ValueError: shapes do not match", "run_failed"),
    ],
)
def test_could_not_run_reason_from_the_error(error, reason):
    block = {"kind": "run", "error": error, "timed_out": False}
    assert classify_blocking(block) == reason


def test_could_not_run_labels(study):
    run_command(study, "echo 'RuntimeError: No CUDA GPUs are available' >&2; exit 1", use_env=False)
    k = compare_claim(study, claim_id="u1", could_not_run=True)
    assert k["reason"] == "gpu_required"
    assert verdict_label(k) == "COULD NOT RUN (GPU required)"
    assert k["headline"].startswith("Could not run (GPU required)")
    k = compare_claim(study, claim_id="u1", could_not_run=True, reason="no_command")
    assert verdict_label(k) == "COULD NOT RUN (no command that produces the number)"
    assert classify_blocking({"kind": "env", "error": "No solution found"}) == "broken_deps"
    assert classify_blocking({"kind": "run", "error": "", "timed_out": True}) == "timeout"


def test_smoke_run_is_labeled_reduced_scale(study):
    run_command(study, "python3 train.py --epochs 1", use_env=False, scope="smoke")
    m = extract_metrics(study)["id"]
    k = compare_claim(study, claim_id="u1", measured=[f"{m}:test_accuracy:last"])
    assert verdict_label(k) == "INCONCLUSIVE (reduced-scale smoke check)"


def test_failed_download_early_in_stderr_is_data_unavailable():
    full = (
        "tar: Error opening archive: Unrecognized archive format\n"
        "cat: data/dbpedia_csv/train.csv: No such file or directory\n" + "warning: x\n" * 40
    )
    block = {"kind": "run", "error": "Abort trap: 6 ./fasttext test", "timed_out": False}
    assert classify_blocking(block) == "run_failed"
    assert classify_blocking(block, full) == "data_unavailable"
