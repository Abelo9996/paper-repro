"""`paper`: find the numbers a paper claims, from its arXiv PDF or a local PDF or text file.

The README is often not where the headline number lives. This module fetches the paper (only
when asked), extracts its text with pypdf, and runs the same claim extractor used for READMEs
over its sentences. Results tables in a PDF are rebuilt from word positions (pdf_tables.py), so
every table cell keeps its exact row label, column label, page and a confidence score. For a
plain-text source there are no positions, and a simpler line-based table reader is used. The
extracted text and the rebuilt tables are saved next to the PDF so they can be read directly.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__
from .claims import METRIC_WORD_RE, _claim, extract_claims
from .pdf_tables import page_words, read_tables, table_claims, tables_markdown
from .study import Study, StudyError, locked
from .util import NUM_RE, sha256_file

ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:\s*)"
    r"(?P<id>\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7})(?:v\d+)?",
    re.IGNORECASE,
)
CAPTION_RE = re.compile(r"^\s*Table\s+(?P<n>[0-9IVX]+)\s*[:.]\s*(?P<text>.*)$", re.IGNORECASE)
# A number in a table row, optionally with a percent sign and a ± spread.
ROW_NUM_RE = re.compile(
    r"(?<![\w.\-])(?P<value>"
    + NUM_RE
    + r")\s*(?P<pct>%)?(?:\s*(?:±|\+/-|\\pm)\s*(?P<pm>"
    + NUM_RE
    + r")\s*%?)?(?![\w.])"
)
PAREN_RE = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")


def find_paper_links(text: str, source: str) -> list[dict[str, str]]:
    """arXiv ids mentioned in a Markdown file, with the line they appear on."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, line in enumerate(text.splitlines(), start=1):
        for m in ARXIV_ID_RE.finditer(line):
            aid = m.group("id")
            if aid not in seen:
                seen.add(aid)
                out.append({"arxiv": aid, "source": f"{source}:{i}"})
    return out


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # pypdf often splits a decimal as "59 .5"; put it back together.
    text = re.sub(r"(\d) \.(\d)", r"\1.\2", text)
    text = re.sub(r"(\d)\s*±\s*(\d)", r"\1 ± \2", text)
    return text.replace(" ", " ")


def _pdf_pages(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is a dependency
        raise StudyError("Reading PDFs needs pypdf: pip install pypdf") from exc
    try:
        reader = PdfReader(str(path))
        return [_normalize(p.extract_text() or "") for p in reader.pages]
    except Exception as exc:  # pypdf raises many types on damaged files
        raise StudyError(f"Could not read {path.name} as a PDF: {exc}") from exc


def _sentences(page: str) -> list[str]:
    """Reflow a PDF page into one sentence per line (PDF lines break mid-sentence)."""
    text = re.sub(r"-\n(?=[a-z])", "", page)  # de-hyphenate words split across lines
    text = re.sub(r"\s*\n\s*", " ", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", text)
    return [p.strip() for p in parts if p.strip()]


SCI_RE = re.compile(r"\d+(?:\.\d+)?\s*[·×x]\s*10\s*[-−]?\d+")  # "2.3 · 1019" from 2.3 x 10^19
DASH_CELL_RE = re.compile("(?<!\\S)[\u2014\u2013-](?!\\S)")  # em dash, en dash or hyphen


def _mask_brackets(line: str) -> str:
    """Blank out (...), [...] and powers of ten while keeping positions, so times, citations
    and costs are not read as results."""
    out = line
    for _ in range(3):
        out = PAREN_RE.sub(lambda m: " " * len(m.group(0)), out)
    return SCI_RE.sub(lambda m: " " * len(m.group(0)), out)


def _caption_metric(caption: str) -> re.Match | None:
    text = re.sub(r"accuracies", "accuracy", caption, flags=re.IGNORECASE)
    return METRIC_WORD_RE.search(text)


def _table_claims(lines: list[str], label: str, page: int) -> list[dict[str, Any]]:
    """Read results tables that follow a 'Table N:' caption, from plain text (no positions).

    Used for text-file sources, and for PDFs only when the layout reader fails.

    A row is a line with a text label followed only by numbers (times and citations in
    brackets are ignored). When a row has as many numbers as the header line has trailing
    column names, each number gets its column name. The table ends at the first line of prose.
    Everything here is marked low confidence.
    """
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        cap = CAPTION_RE.match(lines[i])
        if not cap:
            i += 1
            continue
        caption = cap.group("text").strip()
        caption_metric = _caption_metric(caption)
        caption_pct = bool(re.search(r"percent|%", caption, re.IGNORECASE))
        header: list[str] | None = None
        rows_started = False
        j = i + 1
        while j < min(len(lines), i + 40):
            line = lines[j].strip()
            if not line or CAPTION_RE.match(line):
                break
            masked = _mask_brackets(line)
            nums = list(ROW_NUM_RE.finditer(masked))
            rest = ROW_NUM_RE.sub(" ", masked[nums[0].start() :]) if nums else ""
            if not nums or re.search(r"[A-Za-z]", rest):
                if rows_started:
                    break  # prose after the table
                words = masked.split()
                if nums == [] and 2 <= len(words) <= 12:
                    header = words
                j += 1
                continue
            row_label = re.sub(r"\s*\[[^\]]*\]", "", line[: nums[0].start()]).strip(" :|")
            if not row_label or len(row_label) > 50 or not re.search(r"[A-Za-z]", row_label):
                j += 1
                continue
            rows_started = True
            # Cells in order: numbers and "-" placeholders, so columns line up past empty cells.
            cells = sorted(
                [(m.start(), m) for m in nums]
                + [(d.start(), None) for d in DASH_CELL_RE.finditer(masked, nums[0].start())],
                key=lambda t: t[0],
            )
            columns = (
                header[-len(cells) :]
                if header and len(cells) in (len(header), len(header) - 1)
                else None
            )
            for k, (_, m) in enumerate(cells):
                if m is None:
                    continue
                column = columns[k] if columns else None
                metric_src = (
                    METRIC_WORD_RE.search(column or "")
                    or caption_metric
                    or METRIC_WORD_RE.search(row_label)
                )
                if not metric_src:
                    continue
                out.append(
                    _claim(
                        metric=metric_src.group(0),
                        value=m.group("value"),
                        pct="%" in m.group(0) or caption_pct,
                        pm=m.group("pm"),
                        source=f"{label}, page {page}",
                        line=None,
                        text=f"Table {cap.group('n')}: {caption[:120]} | {line}",
                        kind="paper-table",
                        extra={
                            "row": row_label,
                            "column": column,
                            "table": f"Table {cap.group('n')}",
                            "page": page,
                            "confidence": "low",
                            "confidence_score": 0.3,
                            "confidence_notes": [
                                "read from plain text without positions: columns matched by order"
                            ],
                            "reader": "text",
                        },
                    )
                )
            j += 1
        i = j
    return out


COUNT_AFTER_RE = r"\s*(?:runs?|times|epochs?|seeds?|iterations?|steps?|samples?|examples?|layers?|nodes?|splits?|trials?|repeated|random)\b"


def _prose_claims(page_text: str, label: str, page: int) -> list[dict[str, Any]]:
    sents = _sentences(page_text)
    found = extract_claims("\n".join(sents), f"{label}, page {page}")
    out = []
    for c in found:
        if c["kind"] == "table":
            continue
        vt = c.get("value_text") or ""
        if vt and re.search(re.escape(vt) + COUNT_AFTER_RE, c["text"], re.IGNORECASE):
            continue  # "accuracy of 100 runs" counts runs, it is not a result
        c["line"] = None
        c["page"] = page
        c["kind"] = "paper-prose"
        out.append(c)
    return out


def _download(url: str, dest: Path, timeout: float) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": f"paper-repro/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise StudyError(
            f"Could not download {url}: {exc}. If you have the PDF, pass its local path instead."
        ) from exc
    if dest.read_bytes()[:5] != b"%PDF-":
        dest.unlink(missing_ok=True)
        raise StudyError(f"{url} did not return a PDF. Pass a local PDF path instead.")


TABLE_CAPTION_RE = re.compile(r"\bTable\s+(?:[0-9]+|[IVX]+)\s*[:.]", re.IGNORECASE)


def _pdf_table_claims(
    pdf: Path, pages: list[str], label: str, info: dict[str, Any]
) -> dict[int, list[dict[str, Any]]]:
    """Table claims per page from word positions; the text reader if that fails."""
    wanted = {n for n, text in enumerate(pages, start=1) if TABLE_CAPTION_RE.search(text)}
    by_page: dict[int, list[dict[str, Any]]] = {}
    try:
        tables = read_tables(page_words(pdf, wanted)) if wanted else []
    except Exception as exc:  # pdfminer raises many types on unusual files
        info["table_reader"] = f"text (the layout reader failed: {type(exc).__name__}: {exc})"
        for n, text in enumerate(pages, start=1):
            by_page[n] = _table_claims(text.splitlines(), label, n)
        return by_page
    info["table_reader"] = "layout"
    info["tables"] = [
        {
            "table": f"Table {t.number}",
            "page": t.page,
            "rows": len(t.rows),
            "columns": len(t.columns),
        }
        for t in tables
    ]
    tables_path = pdf.with_suffix(".tables.md")
    tables_path.write_text(tables_markdown(tables, label), encoding="utf-8")
    info["tables_path"] = tables_path
    for c in table_claims(tables, label):
        by_page.setdefault(c["page"], []).append(c)
    return by_page


@locked
def scan_paper(study: Study, source: str | None = None, timeout: float = 60) -> dict:
    """Fetch or copy the paper, extract its text, and record the claimed numbers it states."""
    study.require_repo()
    st = study.state()
    insp = st["inspect"] or {}
    if not source:
        links = insp.get("papers") or []
        if not links:
            raise StudyError(
                "No paper given and the README links no arXiv paper. Pass an arXiv id or URL "
                "(for example 1609.02907) or the path to a PDF or text file."
            )
        source = links[0]["arxiv"]
        picked = f"the arXiv link at {links[0]['source']}"
    else:
        picked = "given"

    out_dir = study.root / "paper"
    out_dir.mkdir(exist_ok=True)
    local = Path(source).expanduser()
    m = ARXIV_ID_RE.search(source) or re.fullmatch(
        r"(?P<id>\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7})(?:v\d+)?", source.strip()
    )
    info: dict[str, Any] = {"source": source, "picked": picked}
    if local.exists():
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", local.stem)
        dest = out_dir / f"{stem}{local.suffix.lower()}"
        if local.resolve() != dest.resolve():
            shutil.copy2(local, dest)
        label = local.name
        info["mode"] = "local-file"
    elif m:
        aid = m.group("id")
        url = f"https://arxiv.org/pdf/{aid}"
        dest = out_dir / f"arxiv-{aid.replace('/', '_')}.pdf"
        if not dest.exists():
            _download(url, dest, timeout)
        label = f"arXiv:{aid}"
        info.update({"mode": "arxiv", "arxiv": aid, "url": url})
    else:
        raise StudyError(
            f"{source!r} is neither an existing file nor an arXiv id or URL. Pass an arXiv id "
            "(1609.02907), an arxiv.org link, or a local PDF or text path."
        )

    if dest.suffix.lower() == ".pdf":
        pages = _pdf_pages(dest)
    else:
        pages = [_normalize(dest.read_text(encoding="utf-8", errors="replace"))]
    text_path = dest.with_suffix(".txt") if dest.suffix.lower() == ".pdf" else dest
    if dest.suffix.lower() == ".pdf":
        text_path.write_text(
            "".join(f"=== page {i} ===\n{p}\n" for i, p in enumerate(pages, start=1)),
            encoding="utf-8",
        )

    if dest.suffix.lower() == ".pdf":
        tables_by_page = _pdf_table_claims(dest, pages, label, info)
    else:
        info["table_reader"] = "text"
        tables_by_page = {
            n: _table_claims(p.splitlines(), label, n) for n, p in enumerate(pages, start=1)
        }

    claims: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for page_no, page in enumerate(pages, start=1):
        found = tables_by_page.get(page_no, []) + _prose_claims(page, label, page_no)
        for c in found:
            key = (
                c["metric"],
                c["value"],
                c["lo"],
                c["hi"],
                page_no,
                c.get("table"),
                c.get("row"),
                c.get("column"),
            )
            if key in seen:
                continue
            seen.add(key)
            claims.append(c)
    # Re-scanning the same paper keeps its ids; another paper continues the numbering.
    same = [e for e in st["papers"] if e["paper"].get("label") == label]
    if same:
        prior = same[0]["paper"].get("id_offset", 0)
    else:
        prior = max(
            (int(c["id"][1:]) for e in st["papers"] for c in e.get("claims", [])), default=0
        )
    info["id_offset"] = prior
    for n, c in enumerate(claims, start=prior + 1):
        c["id"] = f"p{n}"

    rel = lambda p: str(p.relative_to(study.root))  # noqa: E731
    info.update(
        {
            "label": label,
            "file": {"path": rel(dest), "sha256": sha256_file(dest), "bytes": dest.stat().st_size},
            "text_path": rel(text_path),
            **({"tables_path": rel(info.pop("tables_path"))} if "tables_path" in info else {}),
            "pages": len(pages),
            "characters": sum(len(p) for p in pages),
        }
    )
    if info["characters"] < 200:
        info["warning"] = (
            "Almost no text could be extracted (a scanned PDF?). Read the paper yourself and "
            "record the claim with add_claim, giving the page and table as the source."
        )
    return study.append("paper", {"paper": info, "claims": claims})
