"""Read results tables from a PDF by where the words sit on the page.

pypdf's plain text loses the layout: a two-line header comes out as one run of words, empty
cells disappear, and a caption printed below its table reads as if it belonged to the next one.
This module works from word boxes instead (from pdfminer.six) and rebuilds each table:

1. Words are grouped into lines by vertical position (superscripts join their line) and lines
   into segments wherever the horizontal gap is wider than a space or a drawn vertical rule
   separates two words.
2. A `Table N:` or `Table N.` line is a caption. The table is the block of tabular lines right
   above or right below it, within the caption's page column (or the narrower box a
   multi-line caption spans). Which side is decided per paper, from the captions where only
   one side has a table.
3. Rows holding only numbers, `-` placeholders and the row label are body rows. Their number
   cells define the columns by x-position. Lines above the first body row are the header: each
   header segment names the columns it sits over, so a two-level header like `BLEU` over
   `EN-DE  EN-FR` gives `BLEU EN-DE` and `BLEU EN-FR`. Text-only rows inside the body are
   section labels, sub-headers, or labels centered on several rows (LaTeX multirow); a blank
   first cell takes the nearest label between the same horizontal rules.
4. Each number becomes a claim with its table, page, exact row and column labels and a
   confidence score saying how cleanly it lined up. Columns that describe the setup (depth,
   params, N, d_model) are not claims; they name rows that would otherwise repeat.

The word extraction (`page_words`) is separate from the table logic (`find_tables`), so tests
can run the table logic on saved word boxes without the PDF.
"""

from __future__ import annotations

import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import NUM_RE, normalize_metric


@dataclass
class Word:
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    text: str

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class Page:
    number: int
    width: float
    height: float
    words: list[Word]
    rules: list[tuple[float, float, float]] = field(
        default_factory=list
    )  # vertical (x, top, bottom)
    hrules: list[tuple[float, float, float]] = field(default_factory=list)  # horizontal (y, x0, x1)

    def to_json(self) -> dict[str, Any]:
        r = lambda v: round(v, 2)  # noqa: E731
        return {
            "page": self.number,
            "width": r(self.width),
            "height": r(self.height),
            "words": [
                [r(w.x0), r(w.x1), r(w.top), r(w.bottom), r(w.size), w.text] for w in self.words
            ],
            "rules": [[r(x), r(t), r(b)] for x, t, b in self.rules],
            "hrules": [[r(y), r(a), r(b)] for y, a, b in self.hrules],
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Page:
        return cls(
            d["page"],
            d["width"],
            d["height"],
            [Word(*w) for w in d["words"]],
            [tuple(x) for x in d.get("rules", [])],
            [tuple(x) for x in d.get("hrules", [])],
        )


@dataclass
class Segment:
    """Words on one line with no gap wider than a space between them."""

    x0: float
    x1: float
    text: str
    size: float
    words: int

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Line:
    top: float
    bottom: float
    size: float
    words: list[Word]
    segments: list[Segment] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "  ".join(s.text for s in self.segments)


# ---------------------------------------------------------------------------------------------
# Word extraction


def _norm_text(s: str) -> str:
    s = re.sub(r"\(cid:\d+\)", "", s)  # glyphs with no Unicode mapping
    s = unicodedata.normalize("NFKC", s)
    return s.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")


def page_words(path: Path, pages: set[int] | None = None) -> list[Page]:
    """Word boxes for each page (1-based numbers), in top-down page coordinates."""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LTChar, LTContainer, LTCurve
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage

    logging.getLogger("pdfminer").setLevel(logging.ERROR)

    def chars(obj):
        for o in obj:
            if isinstance(o, LTChar):
                yield o
            elif isinstance(o, LTContainer):
                yield from chars(o)

    def rules(obj, h, vertical):
        for o in obj:
            if isinstance(o, LTCurve):
                w, ht = o.x1 - o.x0, o.y1 - o.y0
                if vertical and w <= 1.5 and ht >= 4:
                    yield ((o.x0 + o.x1) / 2, h - o.y1, h - o.y0)
                elif not vertical and ht <= 1.5 and w >= 10:
                    yield (h - (o.y0 + o.y1) / 2, o.x0, o.x1)
            elif isinstance(o, LTContainer):
                yield from rules(o, h, vertical)

    out: list[Page] = []
    rm = PDFResourceManager(caching=True)
    dev = PDFPageAggregator(rm, laparams=None)
    interp = PDFPageInterpreter(rm, dev)
    with path.open("rb") as fh:
        for n, page in enumerate(PDFPage.get_pages(fh), start=1):
            if pages is not None and n not in pages:
                continue
            interp.process_page(page)
            layout = dev.get_result()
            h = layout.height
            cs = []
            for c in chars(layout):
                if not c.upright or c.size <= 0:
                    continue
                cs.append((c.x0, c.x1, h - c.y1, h - c.y0, c.size, c.get_text()))
            words = [w for w in _chars_to_words(cs) if w.text.strip()]
            out.append(
                Page(
                    n,
                    layout.width,
                    h,
                    words,
                    list(rules(layout, h, True)),
                    list(rules(layout, h, False)),
                )
            )
    return out


def _chars_to_words(chars: list[tuple]) -> list[Word]:
    """Group characters into words: same line, same size class, no gap wider than ~0.17 em."""
    words: list[Word] = []
    for line in _cluster_lines(chars, key=lambda c: ((c[2] + c[3]) / 2, c[4])):
        line.sort(key=lambda c: c[0])
        cur: list[tuple] = []
        for c in line:
            if not c[5].strip():
                if cur:
                    words.append(_word(cur))
                cur = []
                continue
            if cur:
                prev = cur[-1]
                size = max(prev[4], c[4])
                gap = c[0] - prev[1]
                size_change = abs(prev[4] - c[4]) > 0.2 * size
                if gap > 0.17 * size or gap < -0.5 * size or size_change:
                    words.append(_word(cur))
                    cur = []
            cur.append(c)
        if cur:
            words.append(_word(cur))
    return words


def _word(cs: list[tuple]) -> Word:
    return Word(
        min(c[0] for c in cs),
        max(c[1] for c in cs),
        min(c[2] for c in cs),
        max(c[3] for c in cs),
        max(c[4] for c in cs),
        _norm_text("".join(c[5] for c in cs)),
    )


def _cluster_lines(items: list, key) -> list[list]:
    """Group items into lines by vertical middle. `key(item)` gives (mid, size). An item joins
    the current line when its middle is within half the larger font size of the line's first
    item, so superscripts and subscripts stay with their line."""
    ordered = sorted(items, key=lambda it: key(it)[0])
    lines: list[list] = []
    anchor = None
    for it in ordered:
        mid, size = key(it)
        if anchor is not None and mid - anchor[0] <= 0.5 * max(size, anchor[1]):
            lines[-1].append(it)
            if size > anchor[1] + 0.5:
                anchor = (mid, size)  # follow the main text, not a raised small glyph
        else:
            lines.append([it])
            anchor = (mid, size)
    return lines


# ---------------------------------------------------------------------------------------------
# Lines and segments


def _lines(words: list[Word]) -> list[Line]:
    out = []
    for group in _cluster_lines(words, key=lambda w: (w.mid, w.size)):
        size = statistics.median(w.size for w in group)
        main = [w for w in group if w.size >= 0.8 * size] or group
        out.append(
            Line(
                top=min(w.top for w in main),
                bottom=max(w.bottom for w in main),
                size=max(w.size for w in main),
                words=sorted(group, key=lambda w: w.x0),
            )
        )
    out.sort(key=lambda ln: ln.top)
    return out


NUM_TOKEN_RE = re.compile(r"^[(\[]?[-+]?(?:\d+\.\d+|\.\d+|\d+)[%)\]]?[*†‡§¶∗]*$")


def _is_num(text: str) -> bool:
    return bool(NUM_TOKEN_RE.match(text))


def _segments(
    words: list[Word], size: float, rules: list[tuple] | tuple = (), gap_em: float = 0.6
) -> list[Segment]:
    """Join words separated by about a space; a wider gap or a drawn vertical rule starts a new
    cell. Two plain numbers side by side are always separate cells."""
    segs: list[Segment] = []
    cur: list[Word] = []

    def flush():
        if cur:
            segs.append(
                Segment(
                    cur[0].x0,
                    max(w.x1 for w in cur),
                    _join(cur, size),
                    max(w.size for w in cur),
                    len(cur),
                )
            )

    for w in words:
        if cur:
            prev = cur[-1]
            gap = w.x0 - prev.x1
            small = w.size < 0.8 * size or prev.size < 0.8 * size
            both_num = _is_num(prev.text) and _is_num(w.text) and not small
            ruled = any(
                prev.x1 - 0.5 <= x <= w.x0 + 0.5 and t < w.bottom and b > w.top for x, t, b in rules
            )
            # In a header, measure the gap against the smaller of the two fonts: small caps
            # set two names closer than a space of the line's main font.
            ref = min(size, prev.size, w.size) if gap_em < 0.6 else size
            if gap > gap_em * ref or (both_num and gap > 0.1 * size) or ruled:
                flush()
                cur = []
        cur.append(w)
    flush()
    # A small-font segment on its own (an exponent or footnote mark pulled onto a neighbouring
    # line) is not a cell.
    big = [sg for sg in segs if sg.size >= 0.8 * size]
    return big if big else segs


def _join(words: list[Word], size: float) -> str:
    """Text of a run of words. A small raised word is written ^x (exponents, footnote marks)."""
    out = ""
    for i, w in enumerate(words):
        t = w.text
        raised = w.size < 0.8 * size and w.bottom < max(x.bottom for x in words) - 0.15 * size
        if raised:
            out += "^" + t
            continue
        if i and not (w.size < 0.8 * size and w.x0 - words[i - 1].x1 < 0.1 * size):
            out += " "
        out += t
    return out.strip()


# ---------------------------------------------------------------------------------------------
# Cells

CELL_RE = re.compile(
    r"^(?P<value>" + NUM_RE + r")\s*(?P<pct>%)?"
    r"(?:\s*(?:±|\+/-|\+-)\s*(?P<pm>" + NUM_RE + r")\s*%?)?$"
)
PAIR_RE = re.compile(
    r"^(?P<a>" + NUM_RE + r")\s*(?P<pa>%)?\s*/\s*(?P<b>" + NUM_RE + r")\s*(?P<pb>%)?$"
)
COUNT_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d+(?:\.\d+)?[KMBkmb]$")
DASH_RE = re.compile(r"^[-\u2010-\u2015\u2212]+$|^n/?a$|^N/?A$")
SCI_CELL_RE = re.compile(r"\d\s*[·×x\*]\s*10\s*\^")
TRAIL_RE = re.compile(r"\s*(?:\([^()]*\)|\[[^\[\]]*\])\s*$")
MARK_RE = re.compile(r"(?:\^\S+|[*†‡§¶∗])+$")


def parse_cell(text: str) -> dict[str, Any] | None:
    """A cell's value(s), or {'empty': True} for a placeholder, or None when it is not numeric."""
    t = text.strip()
    if DASH_RE.match(t):
        return {"empty": True}
    if SCI_CELL_RE.search(t):
        return {"sci": True}
    if COUNT_RE.match(t):
        return {"count": True}  # sizes such as 3,327 or 100K: part of the grid, not results
    t = TRAIL_RE.sub("", t)  # "70.3 (7s)": the time in brackets is not part of the result
    t = MARK_RE.sub("", t).strip()  # footnote marks, bold/underline stars
    t = t.replace("^", "")
    m = CELL_RE.match(t)
    if m:
        # "83.0 ± 0.7%": the percent sign after the spread applies to the value too.
        return {"values": [(m.group("value"), "%" in t, m.group("pm"))]}
    m = PAIR_RE.match(t)
    if m:
        return {
            "values": [
                (m.group("a"), bool(m.group("pa")), None),
                (m.group("b"), bool(m.group("pb")), None),
            ],
            "pair": True,
        }
    return None


# ---------------------------------------------------------------------------------------------
# Tables

CAPTION_START_RE = re.compile(r"^Table\s+(?P<n>[0-9]+|[IVX]+)\s*[:.]", re.IGNORECASE)


@dataclass
class Column:
    x0: float
    x1: float
    labels: list[str] = field(default_factory=list)
    nearest: bool = False  # label placed by nearest position, not by overlap

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Table:
    number: str
    caption: str
    page: int
    caption_side: str  # the caption is "above" or "below" the table
    label_header: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    title: str | None = None
    top: float = 0.0  # extent of table and caption on the page, in points
    bottom: float = 0.0
    left: float = 0.0
    right: float = 0.0


def _span(x0: float, x1: float, width: float) -> tuple[str, float, float]:
    """The page column the table lives in, from the caption's extent on its first line (the
    other column's text can sit on the same line)."""
    mid = width / 2
    if x0 >= mid - 0.05 * width:
        return ("right", mid - 0.01 * width, width)
    if x1 <= mid + 0.05 * width:
        return ("left", 0.0, mid + 0.01 * width)
    return ("full", 0.0, width)


def _in_span(w: Word, span) -> bool:
    kind, lo, hi = span
    if kind == "left":
        return w.x1 <= hi
    if kind == "right":
        return w.x0 >= lo
    if kind == "box":
        return w.x0 >= lo and w.x1 <= hi
    return True


def _span_lines(page: Page, span) -> list[Line]:
    lines = _lines([w for w in page.words if _in_span(w, span)])
    for ln in lines:
        ln.segments = _segments(ln.words, ln.size, page.rules)
    return lines


def _chains(segs: list[Segment], size: float) -> list[tuple[float, float]]:
    """Runs of segments closer than a column gutter (justified prose has wide spaces)."""
    out: list[list[float]] = []
    for sg in segs:
        if out and sg.x0 - out[-1][1] < 1.4 * size:
            out[-1][1] = sg.x1
        else:
            out.append([sg.x0, sg.x1])
    return [(a, b) for a, b in out]


def _is_prose(ln: Line, span) -> bool:
    width = span[2] - span[1]
    for s in ln.segments:
        if s.words >= 7 and (s.x1 - s.x0) >= 0.45 * width:
            return True
        if s.words >= 4 and s.text.endswith(".") and parse_cell(s.text) is None:
            return True  # the end of a sentence, e.g. the last line of another caption
    return False


def _cell_kinds(ln: Line) -> list[dict | None]:
    return [parse_cell(s.text) for s in ln.segments]


def _is_body(ln: Line) -> bool:
    """A row with a label (optional) followed only by numbers, placeholders or exponents, with at
    least one number."""
    kinds = _cell_kinds(ln)
    first = next((i for i, k in enumerate(kinds) if k is not None), None)
    if first is None:
        return False
    if any(k is None for k in kinds[first:]):
        return False
    return any("values" in k for k in kinds[first:])


def _is_caption(ln: Line) -> bool:
    first = ln.segments[0].text if ln.segments else ""
    return bool(CAPTION_START_RE.match(first) or re.match(r"^(Figure|Fig\.)\s*\d+\s*[:.]", first))


def _block(lines: list[Line], start: int, step: int, span, cap: Line) -> list[Line]:
    """Tabular lines walking away from the caption, until prose, another caption or a big gap."""
    out: list[Line] = []
    prev = cap
    i = start
    while 0 <= i < len(lines):
        ln = lines[i]
        i += step
        gap = (ln.top - prev.bottom) if step > 0 else (prev.top - ln.bottom)
        limit = (4.0 if not out else 2.4) * max(ln.size, prev.size)
        if gap > limit or _is_caption(ln) or _is_prose(ln, span):
            break
        out.append(ln)
        prev = ln
    if step < 0:
        out.reverse()
    return out


def _caption_end(lines: list[Line], i: int) -> tuple[str, int, float, float]:
    """Caption text, the index of its last line and its horizontal extent. Captions run over
    several lines; only the run of text starting where the caption starts counts (a figure
    caption can share the line)."""
    first = lines[i]
    x0, x1 = _chains(first.segments, first.size)[0]
    text = " ".join(s.text for s in first.segments if s.x1 <= x1)
    j = i
    while j + 1 < len(lines):
        prev, nxt = lines[j], lines[j + 1]
        if nxt.top - prev.bottom > 0.6 * prev.size or abs(nxt.size - prev.size) > 0.5:
            break
        if _is_body(nxt):
            break
        chains = _chains(nxt.segments, nxt.size)
        own = [c for c in chains if abs(c[0] - x0) <= 1.5 * nxt.size]
        if not own or (len(chains) > 1 and chains[0] != own[0]):
            break
        a, b = own[0]
        more = " ".join(s.text for s in nxt.segments if a <= s.x0 and s.x1 <= b)
        if re.search(r"\d-$", text):
            text += more  # "10-" + "crop": a real hyphen at the line end
        elif re.search(r"[a-z]-$", text) and more[:1].islower():
            text = text[:-1] + more  # "meth-" + "ods": hyphenation
        else:
            text += " " + more
        x1 = max(x1, b)
        j += 1
    return re.sub(r"\s+", " ", text).strip(), j, x0, x1


def _caption_at(lines: list[Line], top: float, size: float) -> int | None:
    return next(
        (
            k
            for k, ln in enumerate(lines)
            if ln.segments
            and abs(ln.top - top) < 0.5 * size
            and CAPTION_START_RE.match(ln.segments[0].text)
        ),
        None,
    )


def _has_table(block: list[Line]) -> bool:
    """A labelled row of numbers; axis ticks of a figure next to the caption do not count."""
    return any(_is_body(x) and parse_cell(x.segments[0].text) is None for x in block)


def find_tables(page: Page, prefer: str | None = None) -> list[tuple[Table | None, dict]]:
    """Tables on one page, one entry per caption. `prefer` is the side the table sits on
    relative to its caption ("above" or "below") when both sides hold one. The info dict says
    which sides held a table, so the caller can learn the paper's habit."""
    page_lines = _lines(page.words)
    results = []
    for pl in page_lines:
        segs = _segments(pl.words, pl.size)
        for k_seg, seg in enumerate(segs):
            m = CAPTION_START_RE.match(seg.text)
            if not m:
                continue
            x0, x1 = _chains(segs[k_seg:], pl.size)[0]
            span = _span(x0, x1, page.width)
            lines = _span_lines(page, span)
            idx = _caption_at(lines, pl.top, pl.size)
            if idx is None:
                continue
            caption, last, cx0, cx1 = _caption_end(lines, idx)
            if last > idx:
                # A caption of several lines is as wide as the box the table sits in, which can
                # be narrower than the page column (a figure may share the column).
                pad = 0.03 * page.width
                box = ("box", max(cx0 - pad, span[1] if span[0] != "full" else 0.0), cx1 + pad)
                lines = _span_lines(page, box)
                idx = _caption_at(lines, pl.top, pl.size)
                if idx is None:
                    continue
                span = box
                caption, last, cx0, cx1 = _caption_end(lines, idx)
            below = _block(lines, last + 1, 1, span, lines[last])
            above = _block(lines, idx - 1, -1, span, lines[idx])
            has_below = _has_table(below)
            has_above = _has_table(above)
            info = {"n": m.group("n"), "above": has_above, "below": has_below}
            if has_above and has_below:
                if prefer:
                    side = prefer
                else:
                    side = (
                        "below"
                        if _gap(below[0].top - lines[last].bottom)
                        <= _gap(lines[idx].top - above[-1].bottom)
                        else "above"
                    )
            elif has_below or has_above:
                side = "below" if has_below else "above"
            else:
                results.append((None, info))
                continue
            block = below if side == "below" else above
            caption_text = CAPTION_START_RE.sub("", caption).strip()
            table = _build(
                block, m.group("n"), caption_text, page.number, span, page.rules, page.hrules
            )
            if table is not None:
                table.caption_side = "above" if side == "below" else "below"
                edges = [*block, lines[idx], lines[last]]
                table.top = min(x.top for x in edges)
                table.bottom = max(x.bottom for x in edges)
                table.left = min(w.x0 for x in edges for w in x.words)
                table.right = max(w.x1 for x in edges for w in x.words)
            results.append((table, info))
    return results


def _gap(x: float) -> float:
    return max(0.0, x)


def _build(
    block: list[Line],
    number: str,
    caption: str,
    page: int,
    span,
    rules: list[tuple],
    hrules: list[tuple] = (),
) -> Table | None:
    body_idx = [k for k, ln in enumerate(block) if _is_body(ln)]
    if not body_idx:
        return None
    first_body = body_idx[0]
    # Trim trailing non-body lines (a footnote under the table) but keep section rows between
    # body rows.
    block = block[: body_idx[-1] + 1]
    header = block[:first_body]
    body = block[first_body:]
    for ln in header:
        # Header words are short; a gap wider than ~0.4 em already separates two names.
        ln.segments = _segments(ln.words, ln.size, rules, gap_em=0.4)

    # Columns from number cells of body rows.
    cells_per_row = []
    for ln in body:
        kinds = _cell_kinds(ln)
        first = next((i for i, k in enumerate(kinds) if k is not None), None)
        if first is None or not _is_body(ln):
            cells_per_row.append(None)
            continue
        cells_per_row.append([(ln.segments[i], kinds[i]) for i in range(first, len(kinds))])
    widest = max(len(c) for c in cells_per_row if c)
    anchors: list[list[float]] = []
    for cells in cells_per_row:
        if cells and len(cells) == widest:
            if not anchors:
                anchors = [[s.x0, s.x1] for s, _ in cells]
            else:
                for a, (s, _) in zip(anchors, cells, strict=True):
                    a[0] = min(a[0], s.x0)
                    a[1] = max(a[1], s.x1)
    columns = [Column(a[0], a[1]) for a in anchors]
    # Cells in rows with fewer cells may open new columns (a column that is empty in the widest
    # rows); add them where they overlap nothing.
    for cells in cells_per_row:
        for s, _ in cells or []:
            if not any(_overlap(s.x0, s.x1, c.x0, c.x1) > 0 for c in columns):
                columns.append(Column(s.x0, s.x1))
    columns.sort(key=lambda c: c.x0)
    if not columns:
        return None
    left_edge = columns[0].x0
    t_top = min(ln.top for ln in block) - 2
    t_bottom = max(ln.bottom for ln in block) + 2
    rules_h = sorted(
        y for y, a, b in hrules if t_top <= y <= t_bottom and a <= columns[-1].x1 and b >= left_edge
    )

    # Text before the first number column. Its first column is the row label; a second text
    # column present in most rows (a citation printed next to its number, "Liu et al. (2017)
    # 84.4") is context for the row, not part of its label.
    size0 = statistics.median(ln.size for ln in body)
    pre = [
        ln.segments[: ln.segments.index(cells[0][0])]
        for ln, cells in zip(body, cells_per_row, strict=True)
        if cells
    ]
    two = [t for t in pre if len(t) >= 2]
    ctx_x = None
    if pre and len(two) >= 0.5 * len(pre):
        ctx_x = min(t[1].x0 for t in two) - 0.5 * size0
    ctx_header = None

    # Header: every header line names the columns under it. On the lowest header line a label
    # names the columns it sits over (or the nearest one). A label on a higher line is a group
    # label ("BLEU" over "EN-DE  EN-FR") and names every column it is the nearest label to.
    label_header_parts: list[str] = []
    title = None
    group = None
    table_x0 = min(min(w.x0 for w in ln.words) for ln in block)
    table_center = (table_x0 + columns[-1].x1) / 2
    # A line of sizes under the column names ("392k  363k ...") is not part of a name.
    header = [
        ln
        for ln in header
        if not all(
            (k := parse_cell(s.text)) is not None and ("count" in k or "empty" in k)
            for s in ln.segments
            if s.x1 > left_edge - 0.2 * ln.size
        )
        or all(s.x1 <= left_edge - 0.2 * ln.size for s in ln.segments)
    ]
    # Single-segment lines below the last multi-segment header line are section labels
    # ("Top Leaderboard Systems") for the rows that follow, not column names.
    multi = [h for h, ln in enumerate(header) if len(ln.segments) > 1]
    if multi:
        for ln in header[multi[-1] + 1 :]:
            group = ln.text
        header = header[: multi[-1] + 1]
    for h, ln in enumerate(header):
        size = ln.size
        segs = []
        for s in ln.segments:
            if s.x1 <= left_edge - 0.2 * size:
                if ctx_x is not None and s.x0 >= ctx_x:
                    ctx_header = f"{ctx_header} {s.text}" if ctx_header else s.text
                else:
                    label_header_parts.append(s.text)
            else:
                segs.append(s)
        if not segs:
            continue
        if (
            h == 0
            and len(header) > 1
            and len(ln.segments) == 1
            and abs(segs[0].center - table_center) < 0.12 * (span[2] - span[1])
            and _covers(segs[0], columns) <= 1
        ):
            title = segs[0].text  # "Transductive" centered over the whole table
            continue
        leaf = h == len(header) - 1
        direct: dict[int, Segment] = {}
        for k, c in enumerate(columns):
            for s in segs:
                if s.x0 - 0.3 * size <= c.center <= s.x1 + 0.3 * size:
                    direct[k] = s
                    break
        for k, c in enumerate(columns):
            if k in direct:
                c.labels.append(direct[k].text)
                continue
            s = min(segs, key=lambda s: _dist(s, c.center))
            d = _dist(s, c.center)
            if leaf:
                # Only the single nearest column, and only if the label covers no column itself.
                if any(v is s for v in direct.values()):
                    continue
                nearest_k = min(range(len(columns)), key=lambda j: _dist(s, columns[j].center))
                if nearest_k == k and d <= max(c.x1 - c.x0, s.x1 - s.x0):
                    c.labels.append(s.text)
                    c.nearest = True
            elif d <= 2.0 * size:
                c.labels.append(s.text)  # a group label: nearest is the expected placement

    if ctx_header and not columns[0].labels:
        columns[0].labels.append(ctx_header)  # "Previous SOTA" names the number beside it
        columns[0].nearest = True

    # Body rows. A text-only row inside the body is a section label ("Ours", "Published"), or,
    # when it has cells over several columns, a sub-header renaming those columns for the rows
    # below it.
    rows: list[dict[str, Any]] = []
    override: dict[int, str] = {}
    spanning: list[tuple[float, str]] = []  # labels centered on several rows (\multirow)
    body_lines = [ln for ln, c in zip(body, cells_per_row, strict=True) if c]
    for ln, cells in zip(body, cells_per_row, strict=True):
        if cells is None:
            covered = {
                k: s.text
                for s in ln.segments
                for k, c in enumerate(columns)
                if s.x0 - 0.3 * ln.size <= c.center <= s.x1 + 0.3 * ln.size
            }
            overlaps = any(
                min(ln.bottom, b.bottom) - max(ln.top, b.top) > 0.2 * ln.size for b in body_lines
            )
            if len(ln.segments) > 1 and covered:
                override.update(covered)
            elif overlaps and ln.segments[0].x1 <= left_edge:
                spanning.append(((ln.top + ln.bottom) / 2, ln.text))
            else:
                group = ln.text
                rows.append({"section": True})
            continue
        first_num = ln.segments.index(cells[0][0])
        texts = ln.segments[:first_num]
        label = " ".join(s.text for s in texts if ctx_x is None or s.x0 < ctx_x)
        context = " ".join(s.text for s in texts if ctx_x is not None and s.x0 >= ctx_x)
        out_cells = []
        for s, kind in cells:
            hits = [k for k, c in enumerate(columns) if _overlap(s.x0, s.x1, c.x0, c.x1) > 0]
            names = [override.get(k) or self_label(columns[k]) for k in hits]
            out_cells.append({"text": s.text, "kind": kind, "columns": hits, "names": names})
        rows.append(
            {
                "label": label,
                "inherited": False,
                "context": context or None,
                "context_header": ctx_header,
                "group": group,
                "cells": out_cells,
                "text": ln.text,
                "mid": (ln.top + ln.bottom) / 2,
            }
        )
    _fill_labels(rows, spanning, rules_h)
    rows = [r for r in rows if not r.get("section")]
    return Table(
        number=number,
        caption=caption,
        page=page,
        caption_side="",
        label_header=" ".join(label_header_parts),
        columns=columns,
        rows=rows,
        title=title,
    )


def _fill_labels(rows: list[dict], spanning: list[tuple[float, str]], hrules: list[float]) -> None:
    """Give rows with an empty first cell a label: the nearest label between the same
    horizontal rules and in the same section, either one centered on several rows (\\multirow)
    or another row's label, preferring the row above on a tie (LaTeX tables leave a repeated
    label blank)."""

    def band(y: float) -> int:
        return sum(1 for r in hrules if r < y)

    section = 0
    for r in rows:
        if r.get("section"):
            section += 1
        else:
            r["_section"] = section
    labelled = [r for r in rows if not r.get("section") and r["label"]]
    for r in rows:
        if r.get("section") or r["label"]:
            continue
        y, b = r["mid"], band(r["mid"])
        # Distances within ~2 pt count as a tie, which the row above wins.
        options = [(round(abs(sy - y) / 2), 0, t) for sy, t in spanning if band(sy) == b]
        options += [
            (round(abs(o["mid"] - y) / 2), 0 if o["mid"] < y else 1, o["label"])
            for o in labelled
            if band(o["mid"]) == b and o["_section"] == r["_section"]
        ]
        if options:
            r["label"] = min(options)[2]
            r["inherited"] = True


def self_label(c: Column) -> str | None:
    return " ".join(c.labels) if c.labels else None


def _dist(s: Segment, x: float) -> float:
    return max(0.0, s.x0 - x, x - s.x1)


def _covers(s: Segment, columns: list[Column]) -> int:
    return sum(1 for c in columns if s.x0 <= c.center <= s.x1)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


# ---------------------------------------------------------------------------------------------
# Whole document


def read_tables(pages: list[Page]) -> list[Table]:
    """Tables on all pages, using the paper's caption side to settle captions that have a
    table on both sides (a caption between two stacked tables)."""
    votes = {"above": 0, "below": 0}
    for p in pages:
        for _t, info in find_tables(p):
            if info["above"] != info["below"]:
                votes["below" if info["below"] else "above"] += 1
    prefer = None
    if votes["above"] != votes["below"]:
        prefer = "below" if votes["below"] > votes["above"] else "above"
    out: list[Table] = []
    for p in pages:
        for t, _info in find_tables(p, prefer=prefer):
            if t is not None:
                out.append(t)
    return out


# ---------------------------------------------------------------------------------------------
# Claims

# Column names that describe the setup or the cost, not a result.
NOT_RESULT_RE = re.compile(
    r"#|\b(?:cost|flops?|params?|parameters|time|speed|throughput|memory|size|layers?|depth|width|epochs?"
    r"|steps?|batch|lr|learning rate|year|hours?|days?|gpus?|nodes|edges|classes|features)\b",
    re.IGNORECASE,
)
PAIR_LABEL_RE = re.compile(r"^(?P<base>.*?)[-\s]*\((?P<a>[^()/]+)/(?P<b>[^()/]+)\)\s*$")
# "single-crop / 10-crop" in a caption names the two values of an "a / b" cell.
CAPTION_PAIR_RE = re.compile(
    r"(?<![\w/.])([A-Za-z0-9][\w-]*[A-Za-z][\w-]*)\s*/\s*([A-Za-z0-9][\w-]*[A-Za-z][\w-]*)(?![\w/])"
)
CITE_RE = re.compile(r"\s*\[[\d,\s\u2013-]+\]")


def _metric_for(column: str | None, caption: str, row: str, title: str | None):
    from .claims import METRIC_WORD_RE

    if column:
        found = list(METRIC_WORD_RE.finditer(column))
        if found:
            # "top-1 err." is a top-1 error, not a top-1 accuracy: keep every metric word.
            text = column[found[0].start() : found[-1].end()]
            if len(text) > 40:
                text = found[-1].group(0)
            topk_only = all(re.match(r"top-?\d", m.group(0), re.IGNORECASE) for m in found)
            if topk_only and re.search(r"\berr", caption, re.IGNORECASE):
                text += " error"
            return text, "column"
    cap = re.sub(r"accuracies", "accuracy", caption, flags=re.IGNORECASE)
    # Metric words next to each other are one name: "Top-1 error", not "Top-1" and "error".
    phrases: list[list[int]] = []
    for m in METRIC_WORD_RE.finditer(cap):
        if phrases and m.start() - phrases[-1][1] <= 2:
            phrases[-1][1] = m.end()
        else:
            phrases.append([m.start(), m.end()])
    if phrases:
        names = [cap[a:b] for a, b in phrases]
        kinds = {normalize_metric(n) for n in names}
        return names[0], "caption" if len(kinds) == 1 else "caption-several"
    for text, where in ((row, "row"), (title or "", "title")):
        m = METRIC_WORD_RE.search(text)
        if m:
            return m.group(0), where
    return None, None


def _level(score: float) -> str:
    return "high" if score >= 0.8 else "medium" if score >= 0.55 else "low"


def _metric_columns(t: Table) -> bool:
    from .claims import METRIC_WORD_RE

    return any(METRIC_WORD_RE.search(self_label(c) or "") for c in t.columns)


def _is_setup(name: str | None, metric_cols: bool) -> bool:
    """A column describing the setup (depth, params, N, d_model), not a result. When some
    columns name a metric, the columns that name none are setup too."""
    from .claims import METRIC_WORD_RE

    if not name:
        return False
    if METRIC_WORD_RE.search(name):
        return False
    return bool(NOT_RESULT_RE.search(name)) or metric_cols


def _setup_cells(r: dict, metric_cols: bool) -> list[tuple[str, str]]:
    """(column name, text) of a row's cells that describe the setup (depth, params, ...)."""
    out = []
    if r.get("context"):
        out.append((r.get("context_header") or "", r["context"]))
    for c in r["cells"]:
        name = c["names"][0] if len(c["columns"]) == 1 else None
        if _is_setup(name, metric_cols):
            out.append((name, c["text"]))
    return out


def _row_names(t: Table) -> list[str]:
    """Row labels, made unique where the table repeats one ("DenseNet (k = 12)" at depth 40 and
    100) by adding the first setup cell that tells the rows apart: "DenseNet (k = 12) (Depth 40)"."""
    base = [CITE_RE.sub("", r["label"]).strip() for r in t.rows]
    out = list(base)
    metric_cols = _metric_columns(t)
    for name in set(base):
        idx = [i for i, b in enumerate(base) if b == name]
        if len(idx) < 2:
            continue
        setups = [dict(_setup_cells(t.rows[i], metric_cols)) for i in idx]
        keys = [k for k in setups[0] if all(k in s for s in setups)]
        # First the setup cells only some of these rows have (the thing that was varied).
        own = [{k: v for k, v in st.items() if k not in keys} for st in setups]
        tags = [", ".join(f"{k} {v}".strip() for k, v in o.items()) for o in own]
        if all(tags) and len(set(tags)) == len(tags):
            for i, tag in zip(idx, tags, strict=True):
                out[i] = f"{name} ({tag})"
            continue
        for k in keys:
            vals = [s[k] for s in setups]
            if len(set(vals)) == len(vals):
                for i, v in zip(idx, vals, strict=True):
                    out[i] = f"{name} ({k} {v})" if k else f"{name} ({v})"
                break
        else:
            # No single column tells them apart: list every setup cell of each row.
            for i, st in zip(idx, setups, strict=True):
                if st:
                    out[i] = f"{name} ({', '.join(f'{k} {v}'.strip() for k, v in st.items())})"
    return out


def table_claims(tables: list[Table], label: str) -> list[dict[str, Any]]:
    """One claim per numeric result cell, with its table, page, exact row and column labels and
    a confidence score (0 to 1) saying how cleanly the cell lined up with its header."""
    from .claims import _claim

    out: list[dict[str, Any]] = []
    for t in tables:
        caption_pct = bool(re.search(r"\bpercent|%", t.caption, re.IGNORECASE))
        names = _row_names(t)
        metric_cols = _metric_columns(t)
        for r, row in zip(t.rows, names, strict=True):
            for c in r["cells"]:
                kind = c["kind"]
                if "values" not in kind or len(c["columns"]) != 1:
                    continue
                col_label = c["names"][0]
                col = t.columns[c["columns"][0]]
                if _is_setup(col_label, metric_cols):
                    continue
                metric, metric_from = _metric_for(col_label, t.caption, row, t.title)
                if not metric:
                    continue
                score = 1.0
                reasons = []
                if not col_label:
                    score -= 0.35
                    reasons.append("no column header found")
                elif col.nearest:
                    score -= 0.15
                    reasons.append("column header matched by nearest position")
                if not row:
                    score -= 0.3
                    reasons.append("no row label")
                elif r.get("inherited"):
                    score -= 0.15
                    reasons.append(
                        "row label taken from a neighbouring row (its own cell is blank)"
                    )
                if metric_from == "caption":
                    score -= 0.1
                    reasons.append("metric named only in the caption")
                elif metric_from == "caption-several":
                    score -= 0.25
                    reasons.append(
                        "the caption names several metrics; check which one this column reports"
                    )
                elif metric_from in ("row", "title"):
                    score -= 0.15
                    reasons.append(f"metric named only in the {metric_from}")
                values = kind["values"]
                for n, (value, pct, pm) in enumerate(values):
                    column = col_label
                    s = score
                    why = list(reasons)
                    if len(values) > 1:
                        pm_label = PAIR_LABEL_RE.match(col_label or "")
                        cap_pair = CAPTION_PAIR_RE.search(t.caption)
                        if pm_label:
                            part = pm_label.group("a" if n == 0 else "b").strip()
                            column = f"{pm_label.group('base')}-{part}"
                        elif cap_pair and len(values) == 2:
                            column = f"{col_label or 'value'} {cap_pair.group(n + 1)}"
                            s -= 0.1
                            why.append("the two values in the cell are named from the caption")
                        else:
                            column = f"{col_label or 'column'} (value {n + 1} of {len(values)})"
                            s -= 0.1
                            why.append("cell holds two values")
                    s = round(max(0.0, min(1.0, s)), 2)
                    out.append(
                        _claim(
                            metric=metric,
                            value=value,
                            pct=pct or caption_pct or "%" in (col_label or ""),
                            pm=pm,
                            source=f"{label}, page {t.page}",
                            line=None,
                            text=f"Table {t.number}: {t.caption[:120]} | {r['text']}",
                            kind="paper-table",
                            extra={
                                "row": row,
                                "column": column,
                                "row_group": r["group"],
                                "table": f"Table {t.number}",
                                "page": t.page,
                                "confidence": _level(s),
                                "confidence_score": s,
                                "confidence_notes": why,
                                "reader": "layout",
                            },
                        )
                    )
    return out


def tables_markdown(tables: list[Table], label: str) -> str:
    """The rebuilt tables as Markdown, so an agent or a person can check a claim against the
    whole table it came from."""
    out = [f"# Tables read from {label}", ""]
    out.append(
        "Rebuilt from word positions in the PDF. Check against the PDF before relying on a value."
    )
    for t in tables:
        out += ["", f"## Table {t.number} (page {t.page})", "", t.caption, ""]
        heads = [t.label_header or ""] + [self_label(c) or "" for c in t.columns]
        out.append("| " + " | ".join(h.replace("|", "/") for h in heads) + " |")
        out.append("|" + "---|" * len(heads))
        for r in t.rows:
            cells = [""] * len(t.columns)
            for c in r["cells"]:
                for k in c["columns"]:
                    cells[k] = c["text"]
            label_cell = r["label"] + (f" ({r['group']})" if r["group"] else "")
            out.append("| " + " | ".join(x.replace("|", "/") for x in [label_cell, *cells]) + " |")
    return "\n".join(out) + "\n"
