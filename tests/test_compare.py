from pathlib import Path

import pytest

from paper_repro.compare import add_claim, compare_claim
from paper_repro.inspect_repo import inspect_repo
from paper_repro.metrics import extract_metrics
from paper_repro.runner import run_command
from paper_repro.study import Study, StudyError


@pytest.fixture
def study(good_repo):
    return Study(Path(inspect_repo(str(good_repo))["study"]))


def measure(study, text):
    run_command(study, f"printf '{text}'", use_env=False)
    return extract_metrics(study)["id"]


def test_rounding_widens_tolerance(study):
    add_claim(study, metric="accuracy", value=99.0, percent=True, source="paper", value_text="99")
    m = measure(study, "accuracy: 0.9862\\n")
    k = compare_claim(study, claim_id="u1", measured=[f"{m}:accuracy:last"], tol=0.1)
    # 98.62 rounds to 99, so it is consistent with a claim stated as "99"
    assert k["verdict"] == "reproduced"
    assert k["tolerance"]["abs"] == pytest.approx(0.5)
    assert any("rounds to it" in r for r in k["reasoning"])


def test_close_band_and_direction(study):
    add_claim(study, metric="val loss", value=1.88, source="README", value_text="1.88")
    m = measure(study, "val loss 1.92\\n")
    k = compare_claim(study, claim_id="u1", measured=[f"{m}:val_loss:last"], rel_tol=0.01)
    assert k["verdict"] == "close"
    assert any("worse than claimed (higher, and lower is better" in r for r in k["reasoning"])
    k2 = compare_claim(
        study, claim_id="u1", measured=[f"{m}:val_loss:last"], rel_tol=0.01, close_tol=0.02
    )
    assert k2["verdict"] == "not_reproduced"


def test_range_claim(study):
    add_claim(study, metric="accuracy", lo=84.2, hi=85.3, source="README")
    m = measure(study, "accuracy= 0.8460\\n")
    k = compare_claim(study, claim_id="u1", measured=[f"{m}:accuracy:last"])
    assert k["verdict"] == "reproduced" and k["distance"] == 0
    m2 = measure(study, "accuracy= 0.8000\\n")
    k = compare_claim(study, claim_id="u1", measured=[f"{m2}:accuracy:last"])
    assert k["verdict"] == "not_reproduced"
    assert k["distance"] == pytest.approx(4.2)


def test_unsourced_values_are_flagged(study):
    add_claim(study, metric="f1", value=81.2, source="paper Table 2")
    k = compare_claim(study, claim_id="u1", unsourced=[81.0])
    assert k["verdict"] == "reproduced"
    assert k["counts_as_reproduction"] is False
    assert any("entered by hand" in r for r in k["reasoning"])


def test_unknown_claim_and_missing_measurement(study):
    with pytest.raises(StudyError, match="Unknown claim"):
        compare_claim(study, claim_id="c999", unsourced=[1.0])
    with pytest.raises(StudyError, match="No measured values"):
        compare_claim(study, claim_id="c1")


def test_could_not_run_points_at_failing_run(study):
    run_command(
        study, "echo 'ModuleNotFoundError: No module named torch' >&2; exit 1", use_env=False
    )
    k = compare_claim(study, claim_id="c1", could_not_run=True)
    assert k["verdict"] == "could_not_run"
    assert k["blocking"]["id"] == "r1"
    assert "No module named torch" in k["blocking"]["error"]


def test_selectors(study):
    m = measure(study, "loss 3\\nloss 1\\nloss 2\\n")
    from paper_repro.metrics import resolve_selector

    assert resolve_selector(study, f"{m}:loss:min")["value"] == 1
    assert resolve_selector(study, f"{m}:loss:first")["value"] == 3
    assert resolve_selector(study, f"{m}:loss")["value"] == 2
    assert resolve_selector(study, f"{m}.2")["line"] == 2
    with pytest.raises(StudyError, match="Names found"):
        resolve_selector(study, f"{m}:accuracy")
