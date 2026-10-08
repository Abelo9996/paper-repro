import sys
from pathlib import Path

import pytest

from paper_repro.inspect_repo import inspect_repo
from paper_repro.runner import run_command
from paper_repro.study import Study, StudyError


@pytest.fixture
def study(good_repo):
    return Study(Path(inspect_repo(str(good_repo))["study"]))


def test_records_exit_code_streams_and_files(study):
    py = sys.executable
    e = run_command(
        study,
        f"{py} -c \"import sys; open('out.csv','w').write('accuracy\\n0.5\\n'); print('hi'); print('oops', file=sys.stderr); sys.exit(3)\"",
        use_env=False,
    )
    assert e["exit_code"] == 3 and not e["timed_out"]
    assert (study.root / e["stdout"]["path"]).read_text() == "hi\n"
    assert e["stderr"]["tail"] == "oops"
    assert [f["path"] for f in e["files"]["written"]] == ["out.csv"]
    assert e["files"]["written"][0]["change"] == "created"
    assert e["files"]["captured"][0]["copy"] == "runs/r1/files/out.csv"
    assert e["wall_seconds"] >= 0
    assert e["peak_rss_mb"] is None or e["peak_rss_mb"] > 0


def test_timeout_kills_the_process_tree(study):
    e = run_command(study, "sleep 30 & sleep 30; echo never", timeout=1, use_env=False)
    assert e["timed_out"] is True
    assert e["wall_seconds"] < 15
    assert "never" not in (study.root / e["stdout"]["path"]).read_text()


def test_env_overrides_and_seed(study):
    e = run_command(
        study, 'echo "$FOO $PAPER_REPRO_SEED"', env={"FOO": "bar"}, seed=7, use_env=False
    )
    assert (study.root / e["stdout"]["path"]).read_text().strip() == "bar 7"
    assert e["env_overrides"] == {"FOO": "bar", "PAPER_REPRO_SEED": "7"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX rlimits")
def test_cpu_limit_is_applied(study):
    e = run_command(
        study, f"{sys.executable} -c 'while True: pass'", cpu_seconds=1, timeout=30, use_env=False
    )
    assert not e["timed_out"]
    assert e["exit_code"] != 0  # killed by SIGXCPU or SIGKILL
    assert e["limits"]["cpu_seconds_per_process"] == 1


def test_scope_validation(study):
    with pytest.raises(StudyError):
        run_command(study, "true", scope="partial")
