"""End-to-end flows over three fixture repos: one reproduces, one is off, one cannot install."""

import json
from pathlib import Path

import pytest
from conftest import env_python, needs_uv

from paper_repro.cli import main
from paper_repro.compare import compare_claim
from paper_repro.envs import create_env
from paper_repro.inspect_repo import inspect_repo
from paper_repro.metrics import extract_metrics
from paper_repro.report import write_report
from paper_repro.runner import run_command
from paper_repro.study import Study, resolve_study


def cli_json(capsys, *argv):
    rc = main([argv[0], "--json", *argv[1:]])
    out = capsys.readouterr().out
    return rc, json.loads(out)


@needs_uv
def test_reproducing_repo_via_cli(good_repo, capsys):
    rc, insp = cli_json(capsys, "inspect", str(good_repo))
    assert rc == 0
    assert insp["repo"]["commit"] and len(insp["repo"]["commit"]) == 40
    claim = next(c for c in insp["claims"] if c["metric"] == "test_accuracy")

    rc, env = cli_json(capsys, "env", "--python", env_python())
    assert rc == 0 and env["status"] == "ok"
    assert env["lock"]["path"] == "lock.txt"

    for seed in (0, 1, 2):
        rc, run = cli_json(
            capsys, "run", "--seed", str(seed), "--", "python", "train.py", "--seed", str(seed)
        )
        assert rc == 0
        assert run["exit_code"] == 0 and run["env_used"]
        assert any(f["path"] == "results.json" for f in run["files"]["written"])

    rc, m = cli_json(capsys, "metrics", "--run", "r1", "--run", "r2", "--run", "r3")
    assert {s["name"] for s in m["summary"]} >= {"test_accuracy", "loss", "train_accuracy"}

    rc, k = cli_json(
        capsys,
        "compare",
        "--claim",
        claim["id"],
        "--measured",
        f"{m['id']}:test_accuracy:last@each",
    )
    assert k["verdict"] == "reproduced"
    assert k["stats"]["n"] == 3
    assert k["counts_as_reproduction"] is True
    assert [v["run"] for v in k["measured"]] == ["r1", "r2", "r3"]

    rc, rep = cli_json(capsys, "report")
    md = Path(rep["report_md"]).read_text()
    assert "Reproduced" in md and "python train.py --seed 2" in md
    data = json.loads(Path(rep["report_json"]).read_text())
    assert data["comparisons"][0]["verdict"] == "reproduced"
    assert data["environment"]["python"]
    assert data["evidence"]["chain_ok"] is True
    assert data["repo"]["commit"] == insp["repo"]["commit"]

    rc, v = cli_json(capsys, "verify")
    assert rc == 0 and v["ok"]


@needs_uv
def test_number_is_off(off_repo):
    entry = inspect_repo(str(off_repo))
    study = Study(Path(entry["study"]))
    claim = next(c for c in entry["claims"] if c["kind"] == "table" and c["row"] == "ours")
    assert claim["value"] == 92.0 and claim["percent"]
    assert create_env(study, python=env_python())["status"] == "ok"
    run_command(study, "python train.py")
    m = extract_metrics(study, run_ids=["r1"], names=["test_accuracy"])
    k = compare_claim(study, claim_id=claim["id"], measured=[f"{m['id']}:test_accuracy:last"])
    assert k["verdict"] == "not_reproduced"
    assert k["measured"][0]["value_on_claim_scale"] == pytest.approx(80.8)
    assert any("worse than claimed" in r for r in k["reasoning"])
    assert any("rescaled by 100" in r for r in k["reasoning"])
    assert any("Only one run" in r for r in k["reasoning"])
    out = write_report(study)
    assert "Not reproduced" in Path(out["report_md"]).read_text()


@needs_uv
def test_broken_dependency_could_not_run(broken_repo):
    entry = inspect_repo(str(broken_repo))
    study = resolve_study()
    assert str(study.root) == entry["study"]
    env = create_env(study, python=env_python())
    assert env["status"] == "failed"
    assert env["failure"]["step"] == "install requirements.txt"
    assert "this-package-does-not-exist-paper-repro" in env["failure"]["error"]
    k = compare_claim(study, claim_id="c1", could_not_run=True)
    assert k["verdict"] == "could_not_run"
    assert k["blocking"]["id"] == env["id"] and k["blocking"]["kind"] == "env"
    md = Path(write_report(study)["report_md"]).read_text()
    assert "Could not run" in md
    assert "this-package-does-not-exist-paper-repro" in md


@needs_uv
def test_shortened_run_never_counts(good_repo):
    entry = inspect_repo(str(good_repo))
    study = Study(Path(entry["study"]))
    create_env(study, python=env_python())
    with pytest.raises(Exception, match="needs --note"):
        run_command(study, "python train.py --epochs 1", scope="shortened")
    run_command(study, "python train.py --epochs 1", scope="shortened", note="1 epoch instead of 3")
    m = extract_metrics(study)
    k = compare_claim(study, claim_id="c1", measured=[f"{m['id']}:test_accuracy:last"])
    assert k["numbers_alone"] == "reproduced"  # the number matches...
    assert k["verdict"] == "inconclusive"  # ...but a shortened run cannot settle the claim
    assert k["scope"] == "shortened"
    assert k["counts_as_reproduction"] is False
    assert k["headline"].startswith("Inconclusive (shortened run)")
    rep = json.loads(Path(write_report(study)["report_json"]).read_text())
    assert any("shortened" in d for d in rep["deviations"])
    assert any("shortened run only" in n for n in rep["not_checked"])


@needs_uv
def test_metrics_read_the_file_as_the_run_left_it(good_repo):
    """A later run overwriting results.json must not change what an earlier run measured."""
    entry = inspect_repo(str(good_repo))
    study = Study(Path(entry["study"]))
    create_env(study, python=env_python())
    run_command(study, "python train.py --seed 0")
    run_command(study, "python train.py --seed 2")
    m = extract_metrics(study, run_ids=["r1"], names=["test.accuracy"])
    assert [v["value"] for v in m["values"]] == [pytest.approx(0.748)]
    assert m["values"][0]["source"].startswith("runs/r1/files/")


def test_tampering_is_detected(good_repo):
    entry = inspect_repo(str(good_repo))
    study = Study(Path(entry["study"]))
    run_command(study, "echo accuracy: 0.75", use_env=False)
    assert study.verify()["ok"]
    (study.root / "runs" / "r1" / "stdout.txt").write_text("accuracy: 0.99\n")
    v = study.verify()
    assert not v["ok"] and any("changed" in p for p in v["problems"])
    lines = study.log_path.read_text().splitlines()
    lines[0] = lines[0].replace('"Python"', '"Rust"')
    study.log_path.write_text("\n".join(lines) + "\n")
    assert any("content hash mismatch" in p for p in study.verify()["problems"])


@needs_uv
def test_python_override_is_a_deviation(good_repo):
    (good_repo / ".python-version").write_text("3.10\n")
    entry = inspect_repo(str(good_repo))
    study = Study(Path(entry["study"]))
    assert entry["suggested_python"]["version"] == "3.10"
    env = create_env(study, python=env_python())
    assert env["status"] == "ok"
    assert any("the repo asks for 3.10" in d for d in env["deviations"])


@needs_uv
def test_failed_env_attempt_keeps_the_working_env(good_repo):
    entry = inspect_repo(str(good_repo))
    study = Study(Path(entry["study"]))
    e1 = create_env(study, python=env_python())
    assert e1["status"] == "ok"
    lock_before = (study.root / "lock.txt").read_text()
    e2 = create_env(study, python="3.4")  # uv refuses this Python
    assert e2["status"] == "failed"
    assert e2["restored_env"] == "e1"
    assert any("newer Python" in h for h in e2["hints"])
    assert study.env_python().exists()
    assert (study.root / "lock.txt").read_text() == lock_before
    assert not (study.root / "env.prev").exists()
    r = run_command(study, "python train.py")
    assert r["exit_code"] == 0 and r["env_used"]
    rep = json.loads(Path(write_report(study)["report_json"]).read_text())
    assert rep["environment"]["id"] == "e1"
    assert [a["id"] for a in rep["earlier_environment_attempts"]] == ["e2"]


@needs_uv
def test_recomparing_a_claim_supersedes_the_earlier_verdict(good_repo):
    entry = inspect_repo(str(good_repo))
    study = Study(Path(entry["study"]))
    create_env(study, python=env_python())
    run_command(study, "python train.py --epochs 1", scope="smoke")
    run_command(study, "python train.py")
    m = extract_metrics(study, run_ids=["r1"])
    k1 = compare_claim(study, claim_id="c1", measured=[f"{m['id']}:test_accuracy:last"])
    assert k1["verdict"] == "inconclusive"
    m2 = extract_metrics(study, run_ids=["r2"])
    k2 = compare_claim(study, claim_id="c1", measured=[f"{m2['id']}:test_accuracy:last"])
    assert k2["verdict"] == "reproduced"
    out = write_report(study)
    assert [v["id"] for v in out["verdicts"]] == [k2["id"]]
    assert out["overall"].startswith("Reproduced")
    md = Path(out["report_md"]).read_text()
    assert f"Superseded by {k2['id']}" in md


def test_reinspecting_the_same_repo_spelled_differently(good_repo):
    inspect_repo(str(good_repo))
    again = inspect_repo(str(good_repo) + "/")
    assert again["claims"]


def test_failed_clone_leaves_no_empty_study(tmp_path):
    with pytest.raises(Exception, match="Check the URL"):
        inspect_repo(str(tmp_path / "missing-but-looks-like-url.git"))
    assert not (tmp_path / "ws" / "missing-but-looks-like-url").exists()
