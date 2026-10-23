"""The shipped gallery and the recipe schema."""

import re

import pytest

from paper_repro.gallery import GALLERY_FILE, find_recipe, load_gallery, validate_recipe

GOOD = {
    "slug": "tiny",
    "title": "Tiny",
    "area": "graph nets",
    "repo": "owner/name",
    "commit": "a" * 40,
    "python": "3.12",
    "command": "python train.py --seed {seed}",
    "seeds": [0, 1],
    "metric": {"name": "accuracy"},
    "claim": {"source": "readme", "value": 81.5},
}


def test_shipped_gallery_is_valid_and_pinned():
    entries = load_gallery(GALLERY_FILE)
    assert entries
    slugs = [e["slug"] for e in entries]
    assert len(slugs) == len(set(slugs))
    for e in entries:
        assert validate_recipe(e) == []
        assert re.fullmatch(r"[0-9a-f]{40}", e["commit"]), e["slug"]
        assert e.get("python"), e["slug"]
        v = e.get("vetted")
        if v:
            assert v["host"] and v["date"] and v["paper_repro"]
            if v["verdict"] != "could_not_run":
                assert isinstance(v["measured"], int | float), e["slug"]
                assert v["wall_seconds"] > 0
            else:
                assert v["reason"], e["slug"]


def test_no_dashes_in_gallery_text():
    assert not re.search("[–—]", GALLERY_FILE.read_text(encoding="utf-8"))


def test_valid_recipe():
    assert validate_recipe(GOOD) == []


@pytest.mark.parametrize(
    "change,problem",
    [
        ({"slug": "Bad Slug"}, "slug must be lowercase"),
        ({"commit": "abc123"}, "full 40-character SHA"),
        ({"python": "3"}, "python must be"),
        ({"command": "python train.py"}, "several seeds need {seed}"),
        ({"seeds": []}, "non-empty list"),
        ({"metric": {}}, "metric.name"),
        ({"claim": {"source": "blog", "value": 1}}, "claim.source"),
        ({"claim": {"source": "readme"}}, "needs a value"),
        ({"claim": {"source": "paper", "value": 1}}, "arxiv id"),
        ({"claim": {"source": "manual", "value": 1}}, "claim.where"),
        ({"tolerance": {"abs": 1}}, "tolerance.why"),
        ({"vetted": {"verdict": "great"}}, "vetted.verdict"),
        ({"env": {"unpin": "yes"}}, "env.unpin"),
    ],
)
def test_invalid_recipes(change, problem):
    r = dict(GOOD) | change
    assert any(problem in p for p in validate_recipe(r)), validate_recipe(r)


def test_find_recipe_by_slug_repo_or_paper():
    entries = [GOOD | {"arxiv": "1609.02907"}]
    assert find_recipe("tiny", entries) is entries[0]
    assert find_recipe("https://github.com/Owner/Name.git", entries) is entries[0]
    assert find_recipe("owner/name", entries) is entries[0]
    assert find_recipe("arXiv:1609.02907v4", entries) is entries[0]
    assert find_recipe("someone/else", entries) is None
