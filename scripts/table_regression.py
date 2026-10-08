"""Measure table reading on real papers, and refresh the offline fixtures.

    uv run python scripts/table_regression.py score --pdf-dir /tmp/pdfs [--reader text|layout]
    uv run python scripts/table_regression.py fixtures --pdf-dir /tmp/pdfs

`score` downloads any missing PDF from arXiv into --pdf-dir, reads its tables and compares the
claims with tests/data/tables/expected.json. `--reader text` is the plain-text reader used for
PDFs up to 0.1.1; `--reader layout` is the word-position reader. `fixtures` writes the word
boxes of each expected table (caption and table only) to tests/data/tables/<id>-p<page>.json,
so the tests run without the PDFs.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from table_eval import load_expected, precision, recall, score_paper  # noqa: E402

from paper_repro.paper import _pdf_pages, _table_claims  # noqa: E402
from paper_repro.pdf_tables import Page, page_words, read_tables, table_claims  # noqa: E402


def fetch(aid: str, pdf_dir: Path) -> Path:
    dest = pdf_dir / f"{aid}.pdf"
    if not dest.exists():
        req = urllib.request.Request(
            f"https://arxiv.org/pdf/{aid}", headers={"User-Agent": "paper-repro-tests"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
    return dest


def text_claims(pdf: Path) -> list[dict]:
    out = []
    for n, page in enumerate(_pdf_pages(pdf), start=1):
        out += _table_claims(page.splitlines(), pdf.name, n)
    return out


def layout_claims(pdf: Path) -> list[dict]:
    return table_claims(read_tables(page_words(pdf)), pdf.name)


def cmd_score(args) -> int:
    totals: dict[str, dict] = {}
    for paper in load_expected():
        if args.split and paper["split"] != args.split:
            continue
        total = totals.setdefault(
            paper["split"], {"claims": 0, "correct": 0, "cells": 0, "found": 0, "heads": []}
        )
        pdf = fetch(paper["arxiv"], args.pdf_dir)
        claims = text_claims(pdf) if args.reader == "text" else layout_claims(pdf)
        s = score_paper(claims, paper)
        for t in s["tables"]:
            print(
                f"{paper['arxiv']} {t['table']} p{t['page']}: {t['correct']}/{t['claims']} claims "
                f"correct, {t['correct']}/{t['cells']} cells found"
            )
            if args.verbose:
                for w in t["wrong"][:8]:
                    print("    wrong or unmatched:", w)
        total["heads"] += s["headline"]
        for k in ("claims", "correct", "cells", "found"):
            total[k] += s[k]
    for split, total in totals.items():
        heads = total["heads"]
        print(
            f"reader={args.reader} split={split}: precision {total['correct']}/{total['claims']} = "
            f"{precision(total):.3f}, recall {total['found']}/{total['cells']} = "
            f"{recall(total):.3f}, headline cells {sum(heads)}/{len(heads)}"
        )
    return 0


def cmd_fixtures(args) -> int:
    out_dir = ROOT / "tests" / "data" / "tables"
    for paper in load_expected():
        pdf = fetch(paper["arxiv"], args.pdf_dir)
        want = {(t["table"], t["page"]) for t in paper["tables"]}
        pages = {p for _, p in want}
        words = {p.number: p for p in page_words(pdf, pages)}
        tables = [
            t for t in read_tables(list(words.values())) if (f"Table {t.number}", t.page) in want
        ]
        for pno in sorted(pages):
            boxes = [
                (t.top - 2, t.bottom + 2, t.left - 2, t.right + 2) for t in tables if t.page == pno
            ]
            page = words[pno]

            def inside(y, x0, x1, boxes=boxes):
                return any(a <= y <= b and x0 >= c and x1 <= d for a, b, c, d in boxes)

            kept = [w for w in page.words if inside(w.mid, w.x0, w.x1)]
            rules = [r for r in page.rules if inside((r[1] + r[2]) / 2, r[0], r[0])]
            hrules = [r for r in page.hrules if any(a <= r[0] <= b for a, b, _, _ in boxes)]
            fixture = Page(pno, page.width, page.height, kept, rules, hrules).to_json()
            fixture["source"] = f"arXiv:{paper['arxiv']}"
            path = out_dir / f"{paper['arxiv']}-p{pno}.json"
            path.write_text(
                json.dumps(fixture, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            print(
                f"wrote {path.relative_to(ROOT)} ({len(kept)} words, {path.stat().st_size} bytes)"
            )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("score", cmd_score), ("fixtures", cmd_fixtures)):
        s = sub.add_parser(name)
        s.add_argument("--pdf-dir", type=Path, required=True)
        s.set_defaults(func=fn)
        if name == "score":
            s.add_argument("--reader", choices=["text", "layout"], default="layout")
            s.add_argument("-v", "--verbose", action="store_true")
            s.add_argument("--split", choices=["dev", "held-out"], help="score one split only")
    args = p.parse_args()
    args.pdf_dir.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
