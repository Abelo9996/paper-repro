"""Score table claims against the hand-checked cells in tests/data/tables/expected.json.

A claim is correct when its table, page, row label, column label and value all match one
expected cell. Precision is correct claims over all claims the reader made from the expected
tables; recall is expected cells found over all expected cells.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

EXPECTED = Path(__file__).parent / "data" / "tables" / "expected.json"


def load_expected() -> list[dict]:
    return json.loads(EXPECTED.read_text(encoding="utf-8"))["papers"]


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"\[[\d,\s\-]+\]", "", s)
    return re.sub(r"[^a-z0-9+]", "", s)  # "+" matters: C10 vs C10+


def expected_cells(table: dict) -> dict[tuple[str, str], float]:
    cells = {}
    for row in table["rows"]:
        for col, v in zip(table["columns"], row[1:], strict=True):
            if v is not None:
                cells[(norm(row[0]), norm(col))] = v
    return cells


def score_paper(claims: list[dict], paper: dict) -> dict:
    out = {"tables": [], "claims": 0, "correct": 0, "cells": 0, "found": 0}
    for t in paper["tables"]:
        gt = expected_cells(t)
        emitted = [c for c in claims if c.get("table") == t["table"] and c.get("page") == t["page"]]
        used: set = set()
        correct = 0
        wrong = []
        for c in emitted:
            key = (norm(c.get("row")), norm(c.get("column")))
            v = gt.get(key)
            if v is not None and key not in used and abs(c["value"] - v) < 1e-9:
                used.add(key)
                correct += 1
            else:
                wrong.append((c.get("row"), c.get("column"), c["value"]))
        out["tables"].append(
            {
                "table": t["table"],
                "page": t["page"],
                "claims": len(emitted),
                "correct": correct,
                "cells": len(gt),
                "wrong": wrong,
            }
        )
        out["claims"] += len(emitted)
        out["correct"] += correct
        out["cells"] += len(gt)
        out["found"] += len(used)
    out["headline"] = [
        any(
            c.get("table") == h[0]
            and norm(c.get("row")) == norm(h[1])
            and norm(c.get("column")) == norm(h[2])
            and abs(c["value"] - h[3]) < 1e-9
            for c in claims
        )
        for h in paper["headline"]
    ]
    return out


def precision(s: dict) -> float:
    return s["correct"] / s["claims"] if s["claims"] else 0.0


def recall(s: dict) -> float:
    return s["found"] / s["cells"] if s["cells"] else 0.0
