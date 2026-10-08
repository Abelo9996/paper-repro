"""Find numbers a README claims: table cells under metric headers and metric sentences."""

from __future__ import annotations

import re
from typing import Any

from .metrics import METRIC_VALUE_RE, _value_ok
from .util import METRIC_RE, NAME_RE, NUM_RE, normalize_metric

TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
METRIC_WORD_RE = re.compile(r"(?<![a-zA-Z])" + METRIC_RE + r"(?![a-zA-Z])", re.IGNORECASE)
CELL_NUM_RE = re.compile(
    r"^\s*[*_~`]*\s*(?P<value>" + NUM_RE + r")\s*(?P<pct>%)?\s*"
    r"(?:(?:±|\+/-|\+-|\\pm)\s*(?P<pm>" + NUM_RE + r")\s*%?)?\s*[*_~`]*\s*$"
)
RANGE_RE = re.compile(
    NAME_RE
    + r"[^0-9\n]{0,40}?\bbetween\s+(?P<lo>"
    + NUM_RE
    + r")\s*%?\s*(?:and|to)\s+(?P<hi>"
    + NUM_RE
    + r")\s*(?P<pct>%)?",
    re.IGNORECASE,
)
PM_RE = re.compile(
    NAME_RE
    + r"[^0-9\n]{0,30}?(?P<value>"
    + NUM_RE
    + r")\s*(?P<pct>%)?\s*(?:±|\+/-|\+-|\\pm)\s*(?P<pm>"
    + NUM_RE
    + r")",
    re.IGNORECASE,
)


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _clean(text: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [label](url) -> label
    return re.sub(r"[*`]", "", text).strip().strip("_").strip()


def extract_claims(text: str, source: str) -> list[dict[str, Any]]:
    """Return claim candidates found in a Markdown document, in document order."""
    lines = text.splitlines()
    claims: list[dict[str, Any]] = []
    in_code = False
    i = 0
    table_lines: set[int] = set()
    # Pass 1: pipe tables
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if (
            not in_code
            and "|" in line
            and i + 1 < len(lines)
            and TABLE_SEP_RE.match(lines[i + 1])
            and "|" in lines[i + 1]
        ):
            header = [_clean(c) for c in _split_row(line)]
            context = " ".join(lines[max(0, i - 3) : i])
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                cells = _split_row(lines[j])
                label = _clean(cells[0]) if cells else ""
                for col, cell in enumerate(cells):
                    m = CELL_NUM_RE.match(_clean_keep_pm(cell))
                    if not m or col >= len(header):
                        continue
                    col_name = header[col]
                    metric_in_header = bool(METRIC_WORD_RE.search(col_name))
                    metric_in_row = bool(METRIC_WORD_RE.search(label))
                    metric_in_context = bool(METRIC_WORD_RE.search(context)) or bool(
                        METRIC_WORD_RE.search(" ".join(header))
                    )
                    if not (metric_in_header or metric_in_row or metric_in_context):
                        continue
                    if metric_in_header:
                        metric = col_name
                    elif metric_in_row:
                        metric = label
                    else:
                        metric = col_name
                    claims.append(
                        _claim(
                            metric=metric,
                            value=m.group("value"),
                            pct=bool(m.group("pct")),
                            pm=m.group("pm"),
                            source=source,
                            line=j + 1,
                            text=lines[j],
                            kind="table",
                            extra={
                                "table_header": " | ".join(header),
                                "row": label,
                                "column": col_name,
                                "confidence": "high"
                                if metric_in_header or metric_in_row
                                else "low",
                            },
                        )
                    )
                table_lines.add(j)
                j += 1
            i = j
            continue
        i += 1

    # Pass 2: sentences and code-block output lines
    in_code = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if idx in table_lines:
            continue
        taken: list[tuple[int, int]] = []
        for m in RANGE_RE.finditer(line):
            claims.append(
                _claim(
                    metric=m.group("name"),
                    value=None,
                    pct=bool(m.group("pct")),
                    pm=None,
                    source=source,
                    line=idx + 1,
                    text=_snippet(line, m.start(), m.end()),
                    kind="code" if in_code else "prose",
                    lo=m.group("lo"),
                    hi=m.group("hi"),
                )
            )
            taken.append(m.span())
        for m in PM_RE.finditer(line):
            if any(a <= m.start() < b for a, b in taken):
                continue
            claims.append(
                _claim(
                    metric=m.group("name"),
                    value=m.group("value"),
                    pct=bool(m.group("pct")),
                    pm=m.group("pm"),
                    source=source,
                    line=idx + 1,
                    text=_snippet(line, m.start(), m.end()),
                    kind="code" if in_code else "prose",
                )
            )
            taken.append(m.span())
        for m in METRIC_VALUE_RE.finditer(line):
            if any(a <= m.start() < b for a, b in taken) or not _value_ok(m, line):
                continue
            if m.group("den"):
                continue
            if in_code and re.search(r"--[\w-]*" + re.escape(m.group("name")), line):
                continue  # a command-line flag such as --eval_loss=..., not a result
            claims.append(
                _claim(
                    metric=m.group("name"),
                    value=m.group("value"),
                    pct=bool(m.group("pct")),
                    pm=None,
                    source=source,
                    line=idx + 1,
                    text=_snippet(line, m.start(), m.end()),
                    kind="code" if in_code else "prose",
                )
            )
    claims.sort(key=lambda c: (c["line"], c["kind"] != "table"))
    return claims


def _snippet(line: str, start: int, end: int, reach: int = 160) -> str:
    """The sentence around a match, so a claim buried in a long paragraph stays readable."""
    if len(line) <= 300:
        return line
    left = max(line.rfind(". ", 0, start), line.rfind("? ", 0, start), line.rfind("! ", 0, start))
    left = left + 2 if left >= 0 and start - left <= reach else max(0, start - reach)
    right_candidates = [i for i in (line.find(". ", end), line.find("? ", end)) if i >= 0]
    right = min(right_candidates) + 1 if right_candidates else len(line)
    if right - end > reach:
        right = end + reach
    text = line[left:right].strip()
    tail = "..." if right < len(line) and not text.endswith((".", "?", "!")) else ""
    return ("..." if left > 0 else "") + text + tail


def _clean_keep_pm(cell: str) -> str:
    return re.sub(r"<[^>]+>", "", cell).replace("&plusmn;", "±").strip()


def _claim(
    *,
    metric: str,
    value: str | None,
    pct: bool,
    pm: str | None,
    source: str,
    line: int | None,
    text: str,
    kind: str,
    lo: str | None = None,
    hi: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    c: dict[str, Any] = {
        "metric": normalize_metric(metric),
        "raw_metric": metric,
        "value": float(value) if value is not None else None,
        "value_text": value,
        "lo": float(lo) if lo is not None else None,
        "hi": float(hi) if hi is not None else None,
        "lo_text": lo,
        "hi_text": hi,
        "plus_minus": float(pm) if pm is not None else None,
        "percent": pct,
        "source": source,
        "line": line,
        "text": text.strip()[:400],
        "kind": kind,
    }
    if extra:
        c.update(extra)
    return c
