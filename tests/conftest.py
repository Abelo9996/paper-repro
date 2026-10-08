from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures import make_repo  # noqa: E402

HAS_UV = shutil.which("uv") is not None
needs_uv = pytest.mark.skipif(not HAS_UV, reason="uv not installed")
PYTHON = sys.executable


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own workspace and HOME, and uv is kept offline."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PAPER_REPRO_HOME", str(tmp_path / "ws"))
    monkeypatch.delenv("PAPER_REPRO_STUDY", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")
    monkeypatch.setenv("UV_NO_CONFIG", "1")
    # keep uv's cache inside the test dir so nothing touches the real one
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def good_repo(tmp_path):
    return make_repo(tmp_path / "src-good", claimed="0.75", actual=0.75)


@pytest.fixture
def off_repo(tmp_path):
    return make_repo(tmp_path / "src-off", claimed="0.92", actual=0.81)


@pytest.fixture
def broken_repo(tmp_path):
    return make_repo(
        tmp_path / "src-broken",
        claimed="0.75",
        actual=0.75,
        requirements="this-package-does-not-exist-paper-repro==1.0.0\n",
    )


def env_python() -> str:
    return os.path.realpath(PYTHON)
