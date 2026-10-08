"""Tables read from word positions, checked against hand-transcribed cells of real papers.

The fixtures in tests/data/tables are the word boxes (text with positions) of the captions and
tables only, extracted from the arXiv PDFs with scripts/table_regression.py. The expected values
were transcribed by hand from the rendered pages.
"""

import json
from pathlib import Path

import pytest
from table_eval import load_expected, precision, recall, score_paper

from paper_repro.pdf_tables import Page, parse_cell, read_tables, table_claims
from paper_repro.util import lower_is_better

DATA = Path(__file__).parent / "data" / "tables"


def _claims(paper: dict) -> list[dict]:
    pages = sorted({t["page"] for t in paper["tables"]})
    loaded = [
        Page.from_json(json.loads((DATA / f"{paper['arxiv']}-p{n}.json").read_text("utf-8")))
        for n in pages
    ]
    return table_claims(read_tables(loaded), f"arXiv:{paper['arxiv']}")


def _total(split: str) -> dict:
    total = {"claims": 0, "correct": 0, "cells": 0, "found": 0, "headline": []}
    for paper in load_expected():
        if paper["split"] != split:
            continue
        s = score_paper(_claims(paper), paper)
        for k in ("claims", "correct", "cells", "found"):
            total[k] += s[k]
        total["headline"] += s["headline"]
    return total


def test_dev_tables_read_exactly():
    t = _total("dev")
    assert t["cells"] == 212
    assert precision(t) == 1.0 and recall(t) == 1.0
    assert all(t["headline"])


def test_held_out_tables_stay_above_the_measured_floor():
    # Measured on 2026-10-08 after the fixes: 150 of 152 claims correct, 150 of 151 cells.
    # The two wrong claims are the ViT "88.4/88.5*" cell, whose second value only a footnote
    # explains. A drop below this floor is a regression.
    t = _total("held-out")
    assert t["cells"] == 151
    assert t["correct"] >= 150 and precision(t) >= 0.98 and recall(t) >= 0.99
    assert all(t["headline"])


def _find(claims, row, column):
    return [c for c in claims if c["row"] == row and c["column"] == column]


def test_transformer_two_level_header_and_confidence():
    paper = next(p for p in load_expected() if p["arxiv"] == "1706.03762")
    claims = _claims(paper)
    (c,) = _find(claims, "Transformer (big)", "BLEU EN-DE")
    assert c["value"] == 28.4 and c["metric"] == "bleu" and c["page"] == 8
    assert c["table"] == "Table 2" and c["confidence"] == "high"
    assert c["confidence_score"] == 1.0 and c["reader"] == "layout"
    # Training cost columns are not results, and 10^19 exponents never become numbers.
    assert not [x for x in claims if "Cost" in (x["column"] or "")]


def test_caption_below_and_stacked_tables_keep_their_numbers():
    paper = next(p for p in load_expected() if p["arxiv"] == "1512.03385")
    claims = _claims(paper)
    t3 = _find(claims, "ResNet-152", "top-1 err.")
    assert [(c["table"], c["value"]) for c in t3] == [("Table 3", 21.43), ("Table 4", 19.38)]
    # "top-1 err." is an error, so lower is better when comparing.
    assert t3[0]["metric"] == "top_1_error" and lower_is_better(t3[0]["metric"])


def test_section_rows_and_two_level_header_in_bert_squad():
    paper = next(p for p in load_expected() if p["arxiv"] == "1810.04805")
    claims = _claims(paper)
    (c,) = _find(claims, "BERTLARGE (Ens.+TriviaQA)", "Test F1")
    assert c["value"] == 93.2 and c["row_group"] == "Ours"
    (m,) = _find(claims, "BERTLARGE", "MNLI-m")
    assert m["value"] == 86.7
    assert "several metrics" in " ".join(m["confidence_notes"])  # F1, Spearman, accuracy


def test_blank_and_repeated_row_labels_are_named_from_the_setup_columns():
    paper = next(p for p in load_expected() if p["arxiv"] == "1608.06993")
    claims = _claims(paper)
    (c,) = _find(claims, "ResNet with Stochastic Depth (Depth 1202)", "C10+")
    assert c["value"] == 4.91 and c["confidence"] == "medium"  # inherited label, caption metric
    assert "neighbouring row" in " ".join(c["confidence_notes"])
    assert not [x for x in claims if x["column"] in ("Depth", "Params")]
    (d,) = _find(claims, "DenseNet-264", "top-1 single-crop")
    assert d["value"] == 22.15


def test_citation_column_is_not_part_of_the_row_label():
    paper = next(p for p in load_expected() if p["arxiv"] == "1802.05365")
    claims = _claims(paper)
    (c,) = _find(claims, "SQuAD", "PREVIOUS SOTA")
    assert c["value"] == 84.4


@pytest.mark.parametrize(
    "text,expected",
    [
        ("81.5", [("81.5", False, None)]),
        ("70.3 (7s)", [("70.3", False, None)]),
        ("83.0 ± 0.7%", [("83.0", True, "0.7")]),
        ("8.43^†", [("8.43", False, None)]),
        ("86.7/85.9", [("86.7", False, None), ("85.9", False, None)]),
    ],
)
def test_parse_cell_values(text, expected):
    assert parse_cell(text)["values"] == expected


@pytest.mark.parametrize("text", ["-", "\u2014", "2.3 · 10^19", "392k", "3,327"])
def test_parse_cell_non_results(text):
    assert "values" not in parse_cell(text)


def test_page_json_round_trip():
    raw = json.loads((DATA / "1706.03762-p8.json").read_text("utf-8"))
    page = Page.from_json(raw)
    again = page.to_json()
    assert again["words"] == raw["words"] and again["rules"] == raw["rules"]
