"""`card`: a 1200x630 verdict card (PNG and SVG) and a README badge, built from the report.

The card states only what the report states: the paper, repo and commit, the claim next to the
measured value, the verdict label, the machine, the wall time, and the one command that reruns
it. Everything comes from report.json, which comes from the evidence log.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .compare import verdict_label
from .study import Study, StudyError

W, H = 1200, 630
COLORS = {
    "reproduced": "#1f7a3a",
    "close": "#a15c00",
    "not_reproduced": "#b42318",
    "reimplemented": "#5b3fa8",
    "inconclusive": "#475467",
    "could_not_run": "#475467",
    None: "#475467",
}
INK, MUTED, RULE, PAPER = "#101828", "#475467", "#d0d5dd", "#ffffff"
GALLERY_URL = "https://github.com/Abelo9996/paper-repro/blob/main/docs/gallery.md"
HOME_URL = "https://github.com/Abelo9996/paper-repro"

FONTS = {
    "sans": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
    "bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "mono": [
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "C:/Windows/Fonts/consola.ttf",
    ],
}
SVG_FAMILY = {
    "sans": "Arial, Helvetica, 'DejaVu Sans', sans-serif",
    "bold": "Arial, Helvetica, 'DejaVu Sans', sans-serif",
    "mono": "Menlo, Consolas, 'DejaVu Sans Mono', monospace",
}


def _font(kind: str, size: int):
    from PIL import ImageFont

    for path in FONTS[kind]:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


@dataclass
class Canvas:
    """Drawing operations recorded once and rendered to both SVG and PNG."""

    ops: list[tuple] = field(default_factory=list)

    def rect(self, x, y, w, h, fill, radius=0):
        self.ops.append(("rect", x, y, w, h, fill, radius))

    def text(self, x, y, s, size, kind="sans", fill=INK):
        """Text with its top-left corner at (x, y)."""
        self.ops.append(("text", x, y, s, size, kind, fill))

    @staticmethod
    def width(s: str, size: int, kind: str = "sans") -> float:
        return _font(kind, size).getlength(s)

    def svg(self) -> str:
        out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">'
        ]
        for op in self.ops:
            if op[0] == "rect":
                _, x, y, w, h, fill, r = op
                out.append(
                    f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"/>'
                )
            else:
                _, x, y, s, size, kind, fill = op
                weight = ' font-weight="bold"' if kind == "bold" else ""
                # SVG places text by its baseline; about 0.8 em below the top for these fonts.
                out.append(
                    f'<text x="{x}" y="{y + round(size * 0.8)}" font-family="{SVG_FAMILY[kind]}" '
                    f'font-size="{size}"{weight} fill="{fill}">{escape(s)}</text>'
                )
        out.append("</svg>")
        return "\n".join(out) + "\n"

    def png(self, path: Path) -> None:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(img)
        for op in self.ops:
            if op[0] == "rect":
                _, x, y, w, h, fill, r = op
                d.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=r, fill=fill)
            else:
                _, x, y, s, size, kind, fill = op
                font = _font(kind, size)
                d.text((x, y + round(size * 0.8)), s, font=font, fill=fill, anchor="ls")
        img.save(path, "PNG", optimize=True)


def _wrap(s: str, size: int, kind: str, width: float, lines: int) -> list[str]:
    words, out, cur = s.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if Canvas.width(trial, size, kind) <= width or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        last = out[-1]
        while last and Canvas.width(last + "...", size, kind) > width:
            last = last[:-1]
        out[-1] = last.rstrip() + "..."
    return out


def _fit(s: str, size: int, kind: str, width: float) -> str:
    if Canvas.width(s, size, kind) <= width:
        return s
    while s and Canvas.width(s + "...", size, kind) > width:
        s = s[:-1]
    return s.rstrip() + "..."


def _fmt(x: float | None) -> str:
    if x is None:
        return "n/a"
    if x == 0:
        return "0"
    return f"{x:.5g}"


def _dur(s: float | None) -> str:
    if s is None:
        return "n/a"
    if s < 60:
        return f"{s:.0f}s"
    m, sec = divmod(int(round(s)), 60)
    return f"{m}m {sec:02d}s" if m < 60 else f"{m // 60}h {m % 60:02d}m"


def card_data(study: Study) -> dict[str, Any]:
    """Everything the card shows, from report.json."""
    path = study.root / "report.json"
    if not path.exists():
        raise StudyError("No report.json yet: run `paper-repro report` first.")
    rep = json.loads(path.read_text(encoding="utf-8"))
    ks = [k for k in rep["comparisons"] if not k.get("superseded_by")]
    if not ks:
        raise StudyError("The report has no verdict to put on a card (no claim was compared).")
    k = ks[-1]
    c = k["claim"]
    repo = rep["repo"]
    url = repo.get("url") or repo.get("source") or ""
    short = re.sub(r"^https?://(www\.)?github\.com/", "", url).removesuffix(".git")
    rp = rep.get("repro") or {}
    unit = "%" if c.get("percent") else ""
    if c.get("value") is not None:
        claimed = f"{c.get('value_text') or _fmt(c['value'])}{unit}"
        if c.get("plus_minus"):
            claimed = f"{c.get('value_text') or _fmt(c['value'])} ± {c['plus_minus']:g}{unit}"
    else:
        claimed = f"{c.get('lo_text')} to {c.get('hi_text')}{unit}"
    stats = k.get("stats")
    if stats:
        measured = f"{_fmt(stats['mean'])}{unit}"
        if stats["n"] > 1:
            spread = f"± {_fmt(stats['std'])}" if stats.get("std") else "identical"
            measured_note = f"mean of {stats['n']} runs, {spread}"
        else:
            measured_note = "1 run"
        names = sorted({v["name"] for v in k["measured"] if v.get("name")})
        if names:
            measured_note = f"{', '.join(names)}, {measured_note}"
    else:
        measured, measured_note = "not measured", k.get("reason") or ""
        if k.get("reason"):
            from .compare import REASONS

            measured_note = REASONS.get(k["reason"], k["reason"])
    where = c.get("source") or ""
    if c.get("line"):
        where += f":{c['line']}"
    if c.get("table"):
        cell = ", ".join(x for x in (c.get("row"), c.get("column")) if x)
        where += f", {c['table']}" + (f" ({cell})" if cell else "")
    host = rep.get("host") or {}
    os_name = {"Darwin": "macOS"}.get(host.get("os") or "", host.get("os") or "")
    hw = [host.get("cpu") or host.get("machine") or "unknown CPU"]
    hw.append(f"{os_name} {host.get('os_version') or host.get('os_release') or ''}".strip())
    if host.get("memory_gb"):
        hw.append(f"{host['memory_gb']:g} GB RAM")
    if rp.get("device") == "cpu":
        hw.append("CPU only")
    runs = [x for x in rep["commands"] if x["scope"] in ("full", "smoke")]
    run_wall = rp.get("run_wall_seconds")
    if run_wall is None:
        run_wall = sum(x["wall_seconds"] or 0 for x in runs)
    slug = rp.get("recipe")
    return {
        "title": rp.get("title") or short,
        "arxiv": rp.get("arxiv"),
        "area": rp.get("area"),
        "repo": short,
        "commit": (repo.get("commit") or "")[:7] or "no commit",
        "verdict": k["verdict"],
        "label": k.get("label") or verdict_label(k),
        "metric": c.get("raw_metric") or c.get("metric"),
        "claimed": claimed,
        "claim_source": where,
        "measured": measured,
        "measured_note": measured_note,
        "hardware": ", ".join(hw),
        "runs": len(runs),
        "run_wall_seconds": run_wall,
        "wall_seconds": rp.get("wall_seconds"),
        "verify_with": rp.get("verify_with") or f"uvx paper-repro inspect {short}",
        "slug": slug,
        "version": rep["tool"]["version"],
        "evidence_head": (rep["evidence"].get("head_sha256") or "")[:12],
        "evidence_entries": rep["evidence"].get("entries"),
        "date": rep["generated_at"][:10],
    }


def draw(data: dict[str, Any]) -> Canvas:
    cv = Canvas()
    color = COLORS.get(data["verdict"], COLORS[None])
    cv.rect(0, 0, W, H, PAPER)
    cv.rect(0, 0, 16, H, color)
    x, right = 64, W - 64
    width = right - x
    # Header line
    head = "paper-repro verdict"
    if data.get("arxiv"):
        head += f"  |  arXiv:{data['arxiv']}"
    if data.get("area"):
        head += f"  |  {data['area']}"
    cv.text(x, 40, _fit(head, 22, "sans", width), 22, "sans", MUTED)
    # Title
    y = 80
    for line in _wrap(data["title"], 44, "bold", width, 2):
        cv.text(x, y, line, 44, "bold")
        y += 54
    cv.text(
        x, y + 6, _fit(f"{data['repo']} @ {data['commit']}", 26, "mono", width), 26, "mono", MUTED
    )
    # Verdict badge
    y = 250
    label = data["label"]
    size = 40
    while Canvas.width(label, size, "bold") > width - 56 and size > 22:
        size -= 2
    bw = Canvas.width(label, size, "bold") + 56
    cv.rect(x, y, bw, 76, color, radius=14)
    cv.text(x + 28, y + 38 - round(size * 0.55), label, size, "bold", "#ffffff")
    # Claim and measurement
    y = 360
    col2 = x + width // 2
    cv.text(x, y, f"Claimed {data['metric']}", 22, "sans", MUTED)
    cv.text(col2, y, f"Measured {data['metric']}", 22, "sans", MUTED)
    cv.text(x, y + 32, _fit(data["claimed"], 52, "bold", width / 2 - 24), 52, "bold")
    cv.text(col2, y + 32, _fit(data["measured"], 52, "bold", width / 2), 52, "bold")
    cv.text(x, y + 98, _fit(data["claim_source"], 20, "sans", width / 2 - 24), 20, "sans", MUTED)
    cv.text(col2, y + 98, _fit(data["measured_note"], 20, "sans", width / 2), 20, "sans", MUTED)
    # Footer
    cv.rect(x, 520, width, 2, RULE)
    took = f"runs {_dur(data['run_wall_seconds'])}"
    if data.get("wall_seconds"):
        took += f", {_dur(data['wall_seconds'])} end to end"
    foot = f"{data['hardware']}  |  {took}"
    cv.text(x, 536, _fit(foot, 20, "sans", width), 20, "sans", MUTED)
    cv.text(x, 572, _fit(f"verify with: {data['verify_with']}", 24, "mono", width), 24, "mono")
    return cv


def badge(data: dict[str, Any]) -> dict[str, str]:
    """A shields.io static badge and the Markdown to paste into a README."""

    def esc(s: str) -> str:
        return urllib.parse.quote(s.replace("-", "--").replace("_", "__"), safe="")

    message = data["label"]
    if data["measured"] != "not measured":
        message += f" {data['measured']} vs {data['claimed']}"
    color = COLORS.get(data["verdict"], COLORS[None]).lstrip("#")
    url = f"https://img.shields.io/badge/{esc('paper-repro')}-{esc(message)}-{color}"
    link = f"{GALLERY_URL}#{data['slug']}" if data.get("slug") else HOME_URL
    alt = f"paper-repro: {data['label']}"
    return {"url": url, "link": link, "markdown": f"[![{alt}]({url})]({link})"}


def write_card(study: Study, out_dir: str | Path | None = None) -> dict[str, str]:
    data = card_data(study)
    dest = Path(out_dir).expanduser().resolve() if out_dir else study.root
    dest.mkdir(parents=True, exist_ok=True)
    cv = draw(data)
    svg, png = dest / "card.svg", dest / "card.png"
    svg.write_text(cv.svg(), encoding="utf-8")
    cv.png(png)
    b = badge(data)
    md = dest / "badge.md"
    md.write_text(b["markdown"] + "\n", encoding="utf-8")
    return {"png": str(png), "svg": str(svg), "badge_md": str(md), "badge": b["markdown"]}
