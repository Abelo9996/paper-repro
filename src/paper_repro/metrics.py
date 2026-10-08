"""Pull metric values out of logs and result files, keeping the source line for each one."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from .study import Study, StudyError
from .util import NAME_RE, NUM_RE, normalize_metric

# name, optional separator words, then a value. Covers `accuracy: 0.913`, `acc=91.3%`,
# `F1 81.2`, `val loss 1.88`, `loss of only 1.88`, `best validation loss is 1.4697`.
SEP_RE = (
    r"[ \t]*(?:\([^)]{0,20}\))?[ \t]*(?:[:=]|\bis\b|\bof\b|\bwas\b|\bto\b|\bat\b|\breaches\b|\bhits\b)?"
    r"[ \t]*(?:(?:only|about|around|approximately|approx\.?|roughly|~|≈)[ \t]*)?"
)
VALUE_RE = r"(?P<value>" + NUM_RE + r")(?:[ \t]*/[ \t]*(?P<den>\d+))?[ \t]*(?P<pct>%)?"
METRIC_VALUE_RE = re.compile(NAME_RE + SEP_RE + VALUE_RE, re.IGNORECASE)

EXCEPTION_LINE_RE = re.compile(
    r"^\s*(Traceback \(most recent call last\)|[\w.]*(Error|Exception|Warning)\b:)"
)
MAX_VALUES_PER_EXTRACTION = 5000
STRUCTURED_SUFFIXES = {".json", ".csv", ".tsv"}
TEXT_SUFFIXES = {".txt", ".log", ".out", ".md"}
CAPTURE_SUFFIXES = STRUCTURED_SUFFIXES | TEXT_SUFFIXES | {".jsonl"}
MAX_FILE_BYTES = 5 * 2**20


def _value_ok(match: re.Match, line: str) -> bool:
    """Reject numbers that are really part of something else (a version, a date, a word)."""
    end = match.end("value") if not match.group("den") else match.end("den")
    rest = line[end : end + 2]
    if rest[:1].isalpha() and not rest.lower().startswith("e"):
        # "3x", "12k", "5 epochs" is fine because of the space; "5epochs" is not a value
        return False
    return not (rest[:1] == "." and rest[1:2].isdigit())


def extract_from_text(text: str, source: str, start_line: int = 1) -> list[dict]:
    """Find `metric <sep> value` pairs on every line."""
    found: list[dict] = []
    for offset, line in enumerate(text.splitlines()):
        if len(line) > 2000:
            line = line[:2000]
        if EXCEPTION_LINE_RE.match(line):
            continue  # "RuntimeError: CUDA error 2" is not a metric
        for m in METRIC_VALUE_RE.finditer(line):
            if not _value_ok(m, line):
                continue
            raw = m.group("value")
            value = float(raw)
            entry: dict[str, Any] = {
                "name": normalize_metric(m.group("name")),
                "raw_name": m.group("name"),
                "value": value,
                "raw": m.group(0).strip(),
                "percent": bool(m.group("pct")),
                "source": source,
                "line": start_line + offset,
                "text": line.strip()[:300],
            }
            if m.group("den"):
                den = int(m.group("den"))
                if den == 0:
                    continue
                entry["value"] = value / den
                entry["fraction"] = f"{raw}/{den}"
                entry["percent"] = False
            found.append(entry)
    return found


def _flatten(obj: Any, prefix: str = "") -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:1000]):
            out.extend(_flatten(v, f"{prefix}[{i}]"))
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, int | float):
        out.append((prefix, float(obj)))
    return out


def extract_from_json(text: str, source: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # JSON lines
        found = []
        for i, line in enumerate(text.splitlines(), start=1):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key, val in _flatten(obj):
                found.append(_structured(key, val, source, i, line))
        return found
    lines = text.splitlines()
    found = []
    for key, val in _flatten(data):
        leaf = re.sub(r"\[\d+\]$", "", key).split(".")[-1]
        line_no = 1
        for i, line in enumerate(lines, start=1):
            if f'"{leaf}"' in line:
                line_no = i
                break
        found.append(_structured(key, val, source, line_no, lines[line_no - 1] if lines else ""))
    return found


def extract_from_csv(text: str, source: str, delimiter: str = ",") -> list[dict]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    lines = text.splitlines()
    found = []
    for r_index, row in enumerate(rows[1:1001], start=2):
        label = row[0] if row else ""
        for col, cell in zip(header, row, strict=False):
            cell_s = cell.strip().rstrip("%")
            if not re.fullmatch(NUM_RE, cell_s):
                continue
            name = col if not label or col == header[0] else col
            entry = _structured(
                name,
                float(cell_s),
                source,
                r_index,
                lines[r_index - 1] if r_index - 1 < len(lines) else "",
            )
            entry["percent"] = cell.strip().endswith("%")
            entry["row"] = label
            found.append(entry)
    return found


def _structured(key: str, value: float, source: str, line: int, text: str) -> dict:
    return {
        "name": normalize_metric(key),
        "raw_name": key,
        "value": value,
        "raw": f"{key}={value}",
        "percent": False,
        "source": source,
        "line": line,
        "text": text.strip()[:300],
    }


def extract_from_file(path: Path, display: str) -> list[dict]:
    if path.stat().st_size > MAX_FILE_BYTES:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix == ".json" or suffix == ".jsonl":
        return extract_from_json(text, display)
    if suffix == ".csv":
        return extract_from_csv(text, display)
    if suffix == ".tsv":
        return extract_from_csv(text, display, delimiter="\t")
    return extract_from_text(text, display)


def extract_metrics(
    study: Study,
    run_ids: list[str] | None = None,
    files: list[str] | None = None,
    names: list[str] | None = None,
) -> dict:
    """Extract metric values from runs' output and files, record them, return the entry."""
    st = study.state()
    run_ids = run_ids or []
    files = files or []
    if not run_ids and not files:
        if not st["runs"]:
            raise StudyError("Nothing to extract from: no runs recorded and no --file given.")
        run_ids = [list(st["runs"])[-1]]
    values: list[dict] = []
    sources: list[str] = []
    for rid in run_ids:
        run = st["runs"].get(rid)
        if not run:
            raise StudyError(f"Unknown run id {rid!r}. Known: {', '.join(st['runs']) or 'none'}")
        captured = {c["path"]: c for c in run.get("files", {}).get("captured", [])}
        for stream in ("stdout", "stderr"):
            rel = run[stream]["path"]
            p = study.root / rel
            if p.exists():
                sources.append(rel)
                for v in extract_from_text(p.read_text(encoding="utf-8", errors="replace"), rel):
                    v["run"] = rid
                    values.append(v)
        for f in run.get("files", {}).get("written", []):
            # Read the copy taken when the run finished, not the live file, which a later
            # run may have overwritten.
            cap = captured.get(f["path"])
            if not cap:
                continue
            fp = study.root / cap["copy"]
            if fp.exists():
                disp = cap["copy"]
                sources.append(disp)
                for v in extract_from_file(fp, disp):
                    v["run"] = rid
                    values.append(v)
    for f in files:
        fp = (study.repo / f).resolve()
        if not fp.exists():
            fp = Path(f).expanduser().resolve()
        if not fp.exists():
            raise StudyError(f"File not found: {f}")
        try:
            disp = "repo/" + str(fp.relative_to(study.repo.resolve()))
        except ValueError:
            disp = str(fp)
        sources.append(disp)
        found = extract_from_file(fp, disp)
        # attribute a file to the run that wrote it, if any
        rel = disp[5:] if disp.startswith("repo/") else None
        for rid, run in st["runs"].items():
            if rel and any(w["path"] == rel for w in run.get("files", {}).get("written", [])):
                for v in found:
                    v.setdefault("run", rid)
        values.extend(found)
    if names:
        wanted = {normalize_metric(n) for n in names}
        values = [
            v
            for v in values
            if v["name"] in wanted or any(v["name"].endswith("_" + w) for w in wanted)
        ]
    truncated = len(values) > MAX_VALUES_PER_EXTRACTION
    values = values[:MAX_VALUES_PER_EXTRACTION]
    mid = study.next_id("m", "metrics")
    for i, v in enumerate(values, start=1):
        v["id"] = f"{mid}.{i}"
    entry = study.append(
        "metrics",
        {
            "id": mid,
            "runs": run_ids,
            "files": files,
            "filter": names or [],
            "sources": sources,
            "values": values,
            "truncated": truncated,
            "summary": summarize(values),
        },
    )
    return entry


def summarize(values: list[dict]) -> list[dict]:
    """Per metric name: count, first, last, min, max with the ids to select them."""
    groups: dict[str, list[dict]] = {}
    for v in values:
        groups.setdefault(v["name"], []).append(v)
    out = []
    for name, vs in groups.items():
        lo = min(vs, key=lambda v: v["value"])
        hi = max(vs, key=lambda v: v["value"])
        out.append(
            {
                "name": name,
                "count": len(vs),
                "last": {"id": vs[-1]["id"], "value": vs[-1]["value"]},
                "first": {"id": vs[0]["id"], "value": vs[0]["value"]},
                "min": {"id": lo["id"], "value": lo["value"]},
                "max": {"id": hi["id"], "value": hi["value"]},
            }
        )
    return out


def resolve_selectors(study: Study, selector: str) -> list[dict]:
    """Like resolve_selector, but `m2:acc:last@each` gives one value per run in m2."""
    sel = selector.strip()
    if sel.endswith("@each"):
        base = sel[: -len("@each")]
        ext_id = base.split(":", 1)[0]
        ext = study.state()["metrics"].get(ext_id)
        if not ext:
            raise StudyError(f"Unknown metrics extraction {ext_id!r}")
        runs = list(dict.fromkeys(v.get("run") for v in ext["values"] if v.get("run")))
        if not runs:
            raise StudyError(f"{ext_id} has no values tied to runs; @each needs run output.")
        out = []
        for r in runs:
            try:
                out.append(resolve_selector(study, f"{base}@{r}"))
            except StudyError:
                continue
        if not out:
            raise StudyError(f"No values match {base!r} in any run of {ext_id}.")
        return out
    return [resolve_selector(study, sel)]


def resolve_selector(study: Study, selector: str) -> dict:
    """Resolve `m2.17` or `m2:val_loss:last|first|min|max[@r3]` to one recorded value."""
    st = study.state()
    sel = selector.strip()
    run_filter = None
    if "@r" in sel and ":" in sel:
        sel, run_filter = sel.rsplit("@", 1)
    m = re.fullmatch(r"(m\d+)\.(\d+)", sel)
    if m:
        ext = st["metrics"].get(m.group(1))
        if not ext:
            raise StudyError(f"Unknown metrics extraction {m.group(1)!r}")
        for v in ext["values"]:
            if v["id"] == sel:
                return v
        raise StudyError(f"No value {sel!r} in {m.group(1)}")
    m = re.fullmatch(r"(m\d+):([^:]+)(?::(last|first|min|max))?", sel)
    if m:
        ext = st["metrics"].get(m.group(1))
        if not ext:
            raise StudyError(f"Unknown metrics extraction {m.group(1)!r}")
        name = normalize_metric(m.group(2))
        how = m.group(3) or "last"
        vs = [v for v in ext["values"] if v["name"] == name]
        if run_filter:
            vs = [v for v in vs if v.get("run") == run_filter]
        if not vs:
            names = sorted({v["name"] for v in ext["values"]})
            raise StudyError(f"No {name!r} values in {m.group(1)}. Names found: {', '.join(names)}")
        if how == "last":
            return vs[-1]
        if how == "first":
            return vs[0]
        if how == "min":
            return min(vs, key=lambda v: v["value"])
        return max(vs, key=lambda v: v["value"])
    raise StudyError(
        f"Bad selector {selector!r}. Use an id like m2.17, a name like m2:val_loss:last, "
        "m2:val_loss:last@r3 for one run, or m2:val_loss:last@each for every run"
    )
