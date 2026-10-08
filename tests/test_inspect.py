import textwrap

from paper_repro.envs import conda_to_requirements, unpin
from paper_repro.inspect_repo import inspect_repo, scan


def test_git_clone_of_file_url(good_repo):
    e = inspect_repo(good_repo.as_uri())
    assert e["repo"]["mode"] == "git-clone"
    assert len(e["repo"]["commit"]) == 40
    assert e["repo"]["dirty"] is False
    assert e["study"].endswith("src-good")


def test_scan_detects_everything(tmp_path):
    r = tmp_path / "r"
    (r / "configs").mkdir(parents=True)
    (r / "README.md").write_text(
        textwrap.dedent(
            """\
            # X
            Requires Python 3.8. Trained on 8 V100 GPUs.
            ```
            pip install torch numpy
            python main.py --config configs/a.yaml
            ```
            Weights: https://drive.google.com/file/d/abc/view and https://example.org/w.pth
            Paper: https://arxiv.org/abs/1234.5678
            """
        )
    )
    (r / "main.py").write_text(
        "import argparse\nimport torch\np = argparse.ArgumentParser()\np.add_argument('--config')\n"
        "model = model.cuda()\nif __name__ == '__main__':\n    pass\n"
    )
    (r / "environment.yml").write_text(
        "name: x\ndependencies:\n  - python=3.8\n  - pytorch=1.10\n  - cudatoolkit=11.3\n  - pip:\n    - einops==0.4.1\n"
    )
    (r / "setup.py").write_text(
        "setup(name='x', python_requires='>=3.7', install_requires=['numpy>=1.20'])"
    )
    s = scan(r)
    kinds = {d["kind"] for d in s["dependency_files"]}
    assert {"conda-environment", "setup.py"} <= kinds
    assert s["suggested_python"]["version"] == "3.8"
    assert any(
        ep["path"] == "main.py" and "__main__ guard" in ep["why"] for ep in s["entry_points"]
    )
    assert s["entry_points"][0]["flags"] == ["--config"]
    urls = [d.get("url") for d in s["downloads"]]
    assert "https://example.org/w.pth" in urls
    assert any("drive.google.com" in (u or "") for u in urls)
    assert not any("arxiv" in (u or "") for u in urls)
    assert s["gpu"]["code"] and s["gpu"]["readme"]
    assert s["readme_install_hints"][0]["packages"] == ["torch", "numpy"]
    assert any(c["command"].startswith("python main.py") for c in s["readme_commands"])


def test_conda_translation(tmp_path):
    f = tmp_path / "environment.yml"
    f.write_text(
        "dependencies:\n  - python=3.8\n  - pytorch::pytorch=1.10\n  - numpy==1.21.2\n  - cudatoolkit=11.3\n"
        "  - libpng\n  - scipy\n  - pip:\n    - einops==0.4.1\n"
    )
    reqs, skipped, py = conda_to_requirements(f)
    assert py == "3.8"
    assert reqs == ["torch==1.10.*", "numpy==1.21.2", "scipy", "einops==0.4.1"]
    assert "cudatoolkit=11.3" in skipped and "libpng" in skipped


def test_unpin():
    assert unpin(["numpy==1.15.1", "torch>=0.4", "# c", "-e .", "scipy[all]==1"]) == [
        "numpy",
        "torch",
        "# c",
        "-e .",
        "scipy",
    ]
