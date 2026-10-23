"""`repro` end to end on fixture repos with a fixture gallery: no network, no authoring."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import env_python, needs_uv
from fixtures import make_repo

from paper_repro.cli import main
from paper_repro.repro import repro
from paper_repro.study import Study


def write_gallery(tmp_path, monkeypatch, recipes):
    path = tmp_path / "gallery.yaml"
    path.write_text(yaml.safe_dump({"papers": recipes}), encoding="utf-8")
    monkeypatch.setenv("PAPER_REPRO_GALLERY", str(path))
    return path


def recipe(repo, slug="tiny-classifier", **over):
    r = {
        "slug": slug,
        "title": "Tiny classifier on the toy set",
        "area": "classic vision",
        "repo": str(repo),
        "device": "cpu",
        "command": "python train.py --seed {seed}",
        "seeds": [0, 1, 2],
        "timeout": 120,
        "metric": {"name": "test_accuracy"},
        "claim": {"source": "readme", "value": 0.75},
    }
    r.update(over)
    return r


@needs_uv
def test_gallery_recipe_reaches_a_verdict_and_a_card(tmp_path, monkeypatch, good_repo, capsys):
    write_gallery(tmp_path, monkeypatch, [recipe(good_repo)])
    rc = main(["repro", "tiny-classifier", "--python", env_python()])
    out = capsys.readouterr().out
    assert rc == 0
    assert "REPRODUCED" in out and "card:" in out and "badge for a README" in out
    study = Study(Path(next(line.split()[-1] for line in out.splitlines() if "study " in line)))
    rep = json.loads((study.root / "report.json").read_text())
    k = rep["comparisons"][-1]
    assert k["label"] == "REPRODUCED" and k["stats"]["n"] == 3
    assert rep["repro"]["recipe"] == "tiny-classifier"
    assert rep["repro"]["verify_with"] == "uvx paper-repro repro tiny-classifier"
    assert [c["seed"] for c in rep["commands"] if c["scope"] == "full"] == [0, 1, 2]
    assert rep["evidence"]["chain_ok"]
    assert (study.root / "card.png").stat().st_size > 10_000
    svg = (study.root / "card.svg").read_text()
    assert "REPRODUCED" in svg and "uvx paper-repro repro tiny-classifier" in svg
    md = (study.root / "report.md").read_text()
    assert "gallery recipe `tiny-classifier`" in md
    # A second repro starts a fresh study instead of appending to the first one.
    second = repro("tiny-classifier", python=env_python(), seeds=1, make_card=False)
    assert second["study"].endswith("tiny-classifier-2") and second["label"] == "REPRODUCED"


@needs_uv
def test_authored_recipe_is_reimplemented(tmp_path, monkeypatch, good_repo):
    write_gallery(
        tmp_path,
        monkeypatch,
        [recipe(good_repo, authored=True, seeds=[0], command="python train.py --seed {seed}")],
    )
    out = repro("tiny-classifier", python=env_python())
    assert out["verdict"] == "reimplemented"
    assert out["label"] == "REIMPLEMENTED (numbers match)"
    assert out["card"]["badge"].startswith("[![paper-repro: REIMPLEMENTED (numbers match)]")


@needs_uv
def test_broken_dependencies_could_not_run(tmp_path, monkeypatch, broken_repo):
    write_gallery(tmp_path, monkeypatch, [recipe(broken_repo, seeds=[0])])
    out = repro("tiny-classifier", python=env_python())
    assert out["verdict"] == "could_not_run"
    assert out["label"] == "COULD NOT RUN (dependencies do not install)"
    assert Path(out["card"]["png"]).exists()


def test_repo_without_recipe_or_command_says_why(tmp_path, monkeypatch, good_repo):
    write_gallery(tmp_path, monkeypatch, [])
    out = repro(str(good_repo), make_card=False)
    assert out["verdict"] == "could_not_run"
    assert out["label"] == "COULD NOT RUN (no command that produces the number)"
    rep = json.loads(Path(out["report_json"]).read_text())
    assert any("python train.py --seed 0" in o for o in rep["observations"])
    assert not rep["commands"]  # nothing was run or installed


def test_cuda_only_code_is_gpu_required(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "gpu", claimed="0.9", actual=0.9, git=False)
    (repo / "model.py").write_text("import torch\nx = torch.zeros(3).cuda()\nmodel.cuda()\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    write_gallery(tmp_path, monkeypatch, [])
    out = repro(str(repo), make_card=False)
    assert out["label"] == "COULD NOT RUN (GPU required)"
    assert "model.py:2" in Path(out["report_md"]).read_text()


@needs_uv
def test_repo_without_recipe_runs_a_given_command(tmp_path, monkeypatch, off_repo):
    write_gallery(tmp_path, monkeypatch, [])
    out = repro(
        str(off_repo),
        command="python train.py",
        claim="c1",
        metric="test_accuracy",
        python=env_python(),
        make_card=False,
    )
    assert out["verdict"] == "not_reproduced" and out["label"] == "NOT REPRODUCED"


def test_recipe_rejects_ad_hoc_overrides(tmp_path, monkeypatch, good_repo):
    write_gallery(tmp_path, monkeypatch, [recipe(good_repo)])
    with pytest.raises(Exception, match="has a gallery recipe"):
        repro("tiny-classifier", command="python other.py")
