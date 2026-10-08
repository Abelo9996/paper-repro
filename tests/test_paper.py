"""Claims from the paper itself: arXiv links in the README, PDF-style text, results tables."""

from pathlib import Path

import pytest

from paper_repro.compare import compare_claim
from paper_repro.inspect_repo import inspect_repo
from paper_repro.paper import _normalize, _table_claims, find_paper_links, scan_paper
from paper_repro.study import Study

# Text as pypdf extracts it from arXiv:1609.02907 page 7 (decimals split, times in brackets).
GCN_PAGE = """\
Results are summarized in Table 2. For ICA, we report the mean accuracy of 100 runs with random
node orderings.
Table 2: Summary of results in terms of classification accuracy (in percent).
Method Citeseer Cora Pubmed NELL
ManiReg [3] 60.1 59 .5 70 .7 21 .8
Planetoid* [29] 64.7 (26s) 75.7 (13s) 77.2 (25s) 61.9 (185s)
GCN (this paper) 70.3 (7s) 81.5 (4s) 79.0 (38s) 66.0 (48s)
GCN (rand. splits) 67.9± 0.5 80 .1± 0.5 78 .9± 0.7 58 .4± 1.7
We further report wall-clock training time in seconds until convergence (in brackets) for our
method and report mean accuracy of 100 runs with random weight initializations.
"""


def test_find_paper_links():
    text = "See [the paper](https://arxiv.org/abs/1609.02907v4) and arXiv:2106.09685.\n"
    links = find_paper_links(text, "README.md")
    assert [x["arxiv"] for x in links] == ["1609.02907", "2106.09685"]
    assert links[0]["source"] == "README.md:1"


def test_table_rows_get_row_and_column():
    claims = _table_claims(_normalize(GCN_PAGE).splitlines(), "arXiv:1609.02907", 7)
    gcn_cora = [c for c in claims if c["row"] == "GCN (this paper)" and c["column"] == "Cora"]
    assert len(gcn_cora) == 1
    c = gcn_cora[0]
    assert c["value"] == 81.5 and c["percent"] and c["metric"] == "accuracy"
    assert c["confidence"] == "low" and c["page"] == 7
    rand = next(c for c in claims if c["row"] == "GCN (rand. splits)" and c["column"] == "Cora")
    assert rand["value"] == 80.1 and rand["plus_minus"] == 0.5
    assert all(c["value"] not in (26, 13, 100) for c in claims)  # times and run counts skipped
    assert {c["row"] for c in claims} == {
        "ManiReg",
        "Planetoid*",
        "GCN (this paper)",
        "GCN (rand. splits)",
    }


def test_scan_paper_from_a_text_file_and_compare(good_repo, tmp_path):
    entry = inspect_repo(str(good_repo))
    study = Study(Path(entry["study"]))
    paper = tmp_path / "paper.txt"
    paper.write_text(GCN_PAGE, encoding="utf-8")
    e = scan_paper(study, str(paper))
    assert e["paper"]["mode"] == "local-file"
    ids = [c["id"] for c in e["claims"]]
    assert ids[0] == "p1" and len(ids) == len(set(ids))
    again = scan_paper(study, str(paper))
    assert [c["id"] for c in again["claims"]] == ids  # re-scan keeps the ids
    target = next(
        c for c in e["claims"] if c.get("row") == "GCN (this paper)" and c["value"] == 81.5
    )
    assert target["id"] in study.state()["claims"]
    k = compare_claim(study, claim_id=target["id"], could_not_run=True)
    assert "page 1" in k["reasoning"][0]


def test_scan_paper_needs_a_source_when_the_readme_links_none(good_repo):
    entry = inspect_repo(str(good_repo))
    with pytest.raises(Exception, match="links no arXiv paper"):
        scan_paper(Study(Path(entry["study"])), None)


def test_inspect_reports_linked_papers(tmp_path):
    from fixtures import make_repo

    repo = make_repo(tmp_path / "src-paper", claimed="0.75", actual=0.75)
    readme = repo / "README.md"
    readme.write_text(readme.read_text() + "\nPaper: https://arxiv.org/abs/1609.02907\n")
    entry = inspect_repo(str(repo))
    assert entry["papers"][0]["arxiv"] == "1609.02907"
