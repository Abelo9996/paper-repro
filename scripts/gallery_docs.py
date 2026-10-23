"""Write docs/gallery.md and the README gallery table from src/paper_repro/data/gallery.yaml.

    uv run python scripts/gallery_docs.py

Every number comes from a recipe's `vetted` block, which scripts/vet_gallery.py fills from a
recorded run. Nothing here is typed in.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GALLERY = ROOT / "src" / "paper_repro" / "data" / "gallery.yaml"
DOC = ROOT / "docs" / "gallery.md"
README = ROOT / "README.md"
START, END = "<!-- gallery:start -->", "<!-- gallery:end -->"


def _dur(s: float | None) -> str:
    if s is None:
        return "n/a"
    if s < 60:
        return f"{s:.0f}s"
    m, sec = divmod(int(round(s)), 60)
    return f"{m}m {sec:02d}s"


def _claim(e: dict) -> str:
    c = e["claim"]
    pct = "%" if c.get("percent") else ""
    if c.get("pm") is not None:
        return f"{c['value']:g} ± {c['pm']:g}{pct}"
    if c.get("range"):
        return f"{c['range'][0]:g} to {c['range'][1]:g}{pct}"
    return f"{c['value']:g}{pct}"


def _measured(e: dict) -> str:
    v = e.get("vetted") or {}
    if v.get("measured") is None:
        return "not measured"
    pct = "%" if e["claim"].get("percent") else ""
    out = f"{v['measured']:.5g}{pct}"
    n = len(v.get("values") or [])
    if n > 1:
        out += f" (mean of {n}, std {v['std']:.2g})" if v.get("std") else f" (mean of {n})"
    return out


def table(entries: list[dict], link_prefix: str) -> list[str]:
    rows = [
        "| Paper | Area | Claim | Measured | Verdict | Runs | Slug |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        v = e.get("vetted") or {}
        title = e["title"].split(":")[0] if len(e["title"]) > 60 else e["title"]
        rows.append(
            f"| {title} | {e['area']} | {_claim(e)} | {_measured(e)} | "
            f"**{v.get('label', 'not vetted')}** | {_dur(v.get('run_wall_seconds')) if v.get('run_wall_seconds') else 'none'} | "
            f"[`{e['slug']}`]({link_prefix}#{e['slug']}) |"
        )
    return rows


def entry_section(e: dict) -> list[str]:
    v = e.get("vetted") or {}
    c = e["claim"]
    L = [f"## {e['slug']}", "", f"**{e['title']}**", ""]
    paper = (
        f"[arXiv:{e['arxiv']}](https://arxiv.org/abs/{e['arxiv']})"
        if e.get("arxiv")
        else "no paper"
    )
    L.append(
        f"- Paper: {paper}. Code: [{e['repo']}](https://github.com/{e['repo']}) at "
        f"`{e['commit'][:12]}`, Python {e['python']}."
    )
    where = c.get("where") or (
        f"{'README' + (':' + str(c['line']) if c.get('line') else '') if c['source'] == 'readme' else 'arXiv:' + str(e.get('arxiv')) + ' ' + str(c.get('table', ''))}"
        + (f", row {c['row']}, column {c['column']}" if c.get("row") else "")
    )
    L.append(f"- Claim: {c.get('metric') or e['metric']['name']} {_claim(e)} ({where}).")
    seeds = e.get("seeds")
    L.append(f"- Command: `{e['command']}`" + (f", seeds {seeds}" if seeds else ""))
    if e.get("setup"):
        L.append("- Setup: " + "; ".join(f"`{s}`" for s in e["setup"]))
    if e.get("tolerance"):
        t = e["tolerance"]
        amount = f"±{t['abs']:g}" if "abs" in t else f"±{t['rel'] * 100:g}% relative"
        L.append(f"- Tolerance: {amount}. {t['why']}")
    if v:
        L.append(f"- Verdict: **{v['label']}**. {v['headline']}")
        if v.get("values") and len(v["values"]) > 1:
            L.append(f"- Per run: {', '.join(f'{x:g}' for x in v['values'])} (seeds {v['seeds']}).")
        if v.get("reason"):
            L.append(
                f"- Blocked at {v.get('blocked_at')}: `{(v.get('error') or '').strip()[:300]}`"
            )
        pk = ", ".join(f"{k} {val}" for k, val in (v.get("key_packages") or {}).items())
        L.append(
            f"- Vetted {v['date']} with paper-repro {v['paper_repro']} on {v['host']}, "
            f"Python {v.get('python')}" + (f", {pk}" if pk else "") + ". "
            f"Runs took {_dur(v.get('run_wall_seconds'))}, {_dur(v.get('wall_seconds'))} end to end "
            "(environment from the uv cache)."
        )
    else:
        L.append("- Not vetted yet.")
    for d in e.get("deviations") or []:
        L.append(f"- Deviation: {d}")
    for n in e.get("not_checked") or []:
        L.append(f"- Not checked: {n}")
    L.append(f"- Rerun: `uvx paper-repro repro {e['slug']}`")
    L.append("")
    return L


def main() -> int:
    entries = yaml.safe_load(GALLERY.read_text(encoding="utf-8"))["papers"]
    doc = [
        "# Gallery",
        "",
        "Papers whose official code was run end to end with `paper-repro repro <slug>` on a CPU",
        "laptop. Each entry pins the commit, Python, environment, command, seeds, metric and claim",
        "(`src/paper_repro/data/gallery.yaml`), so a rerun needs no authoring. Every measured value",
        "below was written by `scripts/vet_gallery.py` from a recorded run; failures and partial",
        "results stay in, with the number or the blocking error.",
        "",
        *table(entries, ""),
        "",
        "Runs is the wall time of the training runs; end to end adds cloning, the environment and",
        "the paper download. Environments came from a warm uv cache; a cold cache adds the",
        "download time of PyTorch and friends.",
        "",
    ]
    for e in entries:
        doc += entry_section(e)
    DOC.write_text("\n".join(doc), encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    if START in readme:
        new = "\n".join([START, *table(entries, "docs/gallery.md"), END])
        readme = re.sub(re.escape(START) + ".*?" + re.escape(END), new, readme, flags=re.S)
        README.write_text(readme, encoding="utf-8")
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
