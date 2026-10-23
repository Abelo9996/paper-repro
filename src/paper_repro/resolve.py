"""From an arXiv id to the paper's official code repository, saying how it was found.

The order of trust: a GitHub link in the arXiv abstract page (comments or abstract, written by
the authors), then links in the paper PDF itself (link annotations and plain text, earlier pages
first), and only then a GitHub search for repositories that mention the arXiv id. A search hit
is not the authors' statement, and the result says so.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import __version__
from .study import StudyError

ARXIV_RE = re.compile(
    r"^(?:arxiv:|https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)?(?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$",
    re.IGNORECASE,
)
GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9][\w.-]*)/([A-Za-z0-9_.-]+)", re.IGNORECASE)
# Repositories a paper links to because it uses them, not because they hold its code.
NOT_PAPER_CODE = {
    "pytorch/pytorch",
    "pytorch/examples",
    "pytorch/vision",
    "tensorflow/tensorflow",
    "tensorflow/models",
    "google/jax",
    "jax-ml/jax",
    "huggingface/transformers",
    "huggingface/datasets",
    "facebookresearch/fairseq",
    "scikit-learn/scikit-learn",
    "numpy/numpy",
    "keras-team/keras",
    "openai/gym",
    "farama-foundation/gymnasium",
    "pyg-team/pytorch_geometric",
    "rusty1s/pytorch_geometric",
    "dmlc/dgl",
    "mlfoundations/open_clip",
    "openai/clip",
}
CODE_WORDS_RE = re.compile(
    r"\b(code|implementation|available|released|open[- ]source|reproduc|repository)\b", re.I
)


def arxiv_id(target: str) -> str | None:
    m = ARXIV_RE.match(target.strip())
    return m.group("id") if m else None


def _get(url: str, timeout: float = 30, accept: str | None = None) -> bytes:
    headers = {"User-Agent": f"paper-repro/{__version__}"}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StudyError(f"Could not fetch {url}: {exc}") from exc


def _clean_repo(owner: str, name: str) -> str | None:
    name = re.sub(r"\.git$", "", name.rstrip(".,;:)]}'\""))
    if not name or owner.lower() in ("orgs", "users", "topics", "about", "features", "sponsors"):
        return None
    return f"{owner}/{name}"


def links_in_text(text: str) -> list[str]:
    """owner/name of every GitHub repository mentioned in some text, in order, with repeats."""
    out = []
    for m in GITHUB_RE.finditer(text):
        repo = _clean_repo(m.group(1), m.group(2))
        if repo:
            out.append(repo)
    return out


def parse_abs_page(page: str) -> dict[str, Any]:
    """Title, authors and the GitHub links an arXiv abstract page states (comments, abstract)."""
    meta = dict.fromkeys(("title", "abstract"), None)
    for key in meta:
        m = re.search(rf'<meta name="citation_{key}" content="([^"]*)"', page)
        if m:
            meta[key] = html_lib.unescape(m.group(1)).strip()
    authors = [
        html_lib.unescape(a)
        for a in re.findall(r'<meta name="citation_author" content="([^"]*)"', page)
    ]
    comments = ""
    m = re.search(r'<td class="tablecell comments[^"]*">(.*?)</td>', page, re.S)
    if m:
        comments = m.group(1)
    links = []
    for where, text in (("arXiv comments", comments), ("arXiv abstract", meta["abstract"] or "")):
        for repo in links_in_text(html_lib.unescape(text)):
            links.append({"repo": repo, "where": where, "text": _plain(text)[:300]})
    return {"title": meta["title"], "authors": authors, "links": links}


def _plain(s: str) -> str:
    s = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>.*?</a>', r"\1", s, flags=re.S)  # "this https URL"
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def pdf_links(pdf: Path) -> list[dict[str, Any]]:
    """GitHub links in a PDF: link annotations (what the reader clicks) and plain text."""
    from pypdf import PdfReader

    out: list[dict[str, Any]] = []
    try:
        reader = PdfReader(str(pdf))
    except Exception as exc:  # pypdf raises many types on damaged files
        raise StudyError(f"Could not read {pdf.name}: {exc}") from exc
    for n, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        flat = re.sub(r"\s+", " ", text)
        for m in GITHUB_RE.finditer(flat):
            repo = _clean_repo(m.group(1), m.group(2))
            if repo:
                ctx = flat[max(0, m.start() - 120) : m.end() + 40]
                out.append({"repo": repo, "where": f"paper page {n} (text)", "text": ctx})
        for annot in page.get("/Annots") or []:
            try:
                action = annot.get_object().get("/A")
                uri = str(action.get_object().get("/URI") or "") if action else ""
            except Exception:  # noqa: BLE001
                continue
            for repo in links_in_text(uri):
                out.append({"repo": repo, "where": f"paper page {n} (link)", "text": uri})
    return out


def rank_candidates(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per repository, best first. A link in the arXiv page outranks the PDF; in the
    PDF, earlier pages, more mentions and words like "code is available" count."""
    by_repo: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = defaultdict(int)
    for i, link in enumerate(links):
        key = link["repo"].lower()
        if key in NOT_PAPER_CODE:
            continue
        counts[key] += 1
        score = 0.0
        if link["where"].startswith("arXiv"):
            score += 100
        else:
            m = re.search(r"page (\d+)", link["where"])
            page = int(m.group(1)) if m else 99
            score += max(0, 20 - 2 * page)
        if CODE_WORDS_RE.search(link.get("text") or ""):
            score += 10
        best = by_repo.get(key)
        if best is None or score > best["score"]:
            by_repo[key] = {
                "repo": link["repo"],
                "score": score,
                "where": link["where"],
                "text": link.get("text"),
                "order": best["order"] if best else i,
            }
    for key, c in by_repo.items():
        c["mentions"] = counts[key]
        c["score"] += min(counts[key], 10)
    ranked = sorted(by_repo.values(), key=lambda c: (-c["score"], c["order"]))
    for c in ranked:
        c.pop("order", None)
    return ranked


def parse_github_search(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for item in payload.get("items") or []:
        out.append(
            {
                "repo": item["full_name"],
                "stars": item.get("stargazers_count"),
                "description": item.get("description"),
            }
        )
    return out


def github_search(aid: str, timeout: float = 30) -> list[dict[str, Any]]:
    q = urllib.parse.quote(f'"{aid}" in:readme')
    raw = _get(
        f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=5",
        timeout,
        accept="application/vnd.github+json",
    )
    return parse_github_search(json.loads(raw))


def resolve_arxiv(aid: str, pdf_dest: Path, timeout: float = 60) -> dict[str, Any]:
    """Find the code for arXiv paper `aid`. Downloads the PDF to `pdf_dest` (reused if present).

    Returns the chosen repo (or None), how it was found, the evidence and every candidate."""
    page = _get(f"https://arxiv.org/abs/{aid}", timeout).decode("utf-8", errors="replace")
    meta = parse_abs_page(page)
    links = list(meta["links"])
    if not pdf_dest.exists():
        pdf_dest.parent.mkdir(parents=True, exist_ok=True)
        data = _get(f"https://arxiv.org/pdf/{aid}", timeout)
        if data[:5] != b"%PDF-":
            raise StudyError(f"arxiv.org/pdf/{aid} did not return a PDF.")
        pdf_dest.write_bytes(data)
    links += pdf_links(pdf_dest)
    ranked = rank_candidates(links)
    out: dict[str, Any] = {
        "arxiv": aid,
        "title": meta["title"],
        "authors": meta["authors"],
        "pdf": str(pdf_dest),
        "candidates": ranked[:8],
    }
    if ranked:
        best = ranked[0]
        out.update(
            repo=best["repo"],
            method="arxiv-page" if best["where"].startswith("arXiv") else "paper-pdf",
            evidence=f"{best['where']}: {best['text']}",
            stated_by_authors=True,
        )
        return out
    try:
        hits = github_search(aid, timeout)
    except StudyError as exc:
        hits = []
        out["search_error"] = str(exc)
    out["candidates"] = hits
    if hits:
        out.update(
            repo=hits[0]["repo"],
            method="github-search",
            evidence=(
                f"neither the arXiv page nor the PDF links a repository; GitHub search for "
                f'"{aid}" in READMEs, most starred first: '
                + ", ".join(f"{h['repo']} ({h['stars']} stars)" for h in hits[:3])
            ),
            stated_by_authors=False,
        )
    else:
        out.update(repo=None, method=None, evidence="no repository linked or found")
    return out
