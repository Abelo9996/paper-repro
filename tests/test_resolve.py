"""arXiv id to official repo, from saved arXiv pages, PDF links and a GitHub search reply."""

import json
from pathlib import Path

import pytest

from paper_repro.resolve import (
    arxiv_id,
    links_in_text,
    parse_abs_page,
    parse_github_search,
    rank_candidates,
)

DATA = Path(__file__).parent / "data" / "arxiv"


@pytest.mark.parametrize(
    "text,aid",
    [
        ("1609.02907", "1609.02907"),
        ("arXiv:2011.14439v5", "2011.14439"),
        ("https://arxiv.org/abs/1706.03762", "1706.03762"),
        ("https://arxiv.org/pdf/1706.03762v7.pdf", "1706.03762"),
        ("karpathy/nanoGPT", None),
        ("nanogpt-shakespeare-char", None),
    ],
)
def test_arxiv_id(text, aid):
    assert arxiv_id(text) == aid


def test_link_in_arxiv_comments_wins():
    meta = parse_abs_page((DATA / "2010.11929.abs.html").read_text())
    assert meta["title"].startswith("An Image is Worth 16x16 Words")
    assert meta["links"][0]["repo"] == "google-research/vision_transformer"
    assert meta["links"][0]["where"] == "arXiv comments"
    assert "https://github.com/google-research/vision_transformer" in meta["links"][0]["text"]
    ranked = rank_candidates(
        meta["links"] + [{"repo": "csrhddlam/axial-deeplab", "where": "paper page 3 (text)"}]
    )
    assert ranked[0]["repo"] == "google-research/vision_transformer"


def test_abs_page_without_links():
    meta = parse_abs_page((DATA / "2011.14439.abs.html").read_text())
    assert meta["title"] == "Scaling Down Deep Learning with MNIST-1D"
    assert meta["links"] == []


def test_pdf_link_annotations_name_the_repo():
    links = json.loads((DATA / "2011.14439.pdf-links.json").read_text())
    ranked = rank_candidates(links)
    assert ranked[0]["repo"] == "greydanus/mnist1d" and ranked[0]["mentions"] >= 10
    assert ranked[0]["where"] == "paper page 1 (link)"


def test_code_available_sentence_beats_a_cited_baseline():
    # GCN: "Code to reproduce our experiments is available at github.com/tkipf/gcn" on page 4,
    # and the Planetoid baseline's repository cited elsewhere.
    links = json.loads((DATA / "1609.02907.pdf-links.json").read_text())
    ranked = rank_candidates(links)
    assert ranked[0]["repo"] == "tkipf/gcn"
    assert "available" in ranked[0]["text"]
    assert {c["repo"] for c in ranked} >= {"tkipf/gcn", "kimiyoung/planetoid"}


def test_framework_repos_are_not_paper_code():
    links = [
        {"repo": "pytorch/pytorch", "where": "paper page 1 (text)", "text": "code available"},
        {"repo": "me/mine", "where": "paper page 9 (text)", "text": ""},
    ]
    assert [c["repo"] for c in rank_candidates(links)] == ["me/mine"]


def test_github_search_reply():
    hits = parse_github_search(json.loads((DATA / "1609.02907.github-search.json").read_text()))
    assert hits[0] == {
        "repo": "tkipf/pygcn",
        "stars": 5397,
        "description": "Graph Convolutional Networks in PyTorch",
    }


def test_links_in_text():
    text = "Code: https://github.com/greydanus/mnist1d/blob/master/x.ipynb and github.com/a/b.git."
    assert links_in_text(text) == ["greydanus/mnist1d", "a/b"]
