"""The verdict card and badge render from report data alone."""

from PIL import Image

from paper_repro.card import H, W, badge, draw

DATA = {
    "title": "Semi-Supervised Classification with Graph Convolutional Networks",
    "arxiv": "1609.02907",
    "area": "graph nets",
    "repo": "tkipf/pygcn",
    "commit": "1600b5b",
    "verdict": "close",
    "label": "PARTIAL",
    "metric": "accuracy",
    "claimed": "81.5%",
    "claim_source": "arXiv:1609.02907, page 7, Table 2 (GCN (this paper), Cora)",
    "measured": "83.3%",
    "measured_note": "accuracy, mean of 3 runs, ± 0.4",
    "hardware": "Apple M4, macOS 26.2, 16 GB RAM, CPU only",
    "runs": 3,
    "run_wall_seconds": 31.0,
    "wall_seconds": 75.0,
    "verify_with": "uvx paper-repro repro pygcn-cora",
    "slug": "pygcn-cora",
}


def test_png_and_svg(tmp_path):
    cv = draw(DATA)
    svg = cv.svg()
    assert f'width="{W}" height="{H}"' in svg
    for text in (
        "PARTIAL",
        "81.5%",
        "83.3%",
        "tkipf/pygcn @ 1600b5b",
        "uvx paper-repro repro pygcn-cora",
    ):
        assert text in svg
    assert "Apple M4" in svg and "runs 31s, 1m 15s end to end" in svg
    cv.png(tmp_path / "card.png")
    img = Image.open(tmp_path / "card.png")
    assert img.size == (1200, 630)
    # The verdict badge is drawn in the verdict's color.
    assert img.getpixel((70, 290)) == (0xA1, 0x5C, 0x00)


def test_long_title_is_wrapped_and_cut():
    data = DATA | {"title": "word " * 80}
    lines = [op for op in draw(data).ops if op[0] == "text" and op[4] == 44]
    assert len(lines) == 2 and lines[-1][3].endswith("...")


def test_badge_markdown():
    b = badge(DATA)
    assert b["url"] == (
        "https://img.shields.io/badge/paper--repro-PARTIAL%2083.3%25%20vs%2081.5%25-a15c00"
    )
    assert b["markdown"].startswith("[![paper-repro: PARTIAL](")
    assert b["link"].endswith("docs/gallery.md#pygcn-cora")
    cnr = badge(
        DATA
        | {
            "verdict": "could_not_run",
            "label": "COULD NOT RUN (GPU required)",
            "measured": "not measured",
        }
    )
    assert "COULD%20NOT%20RUN%20%28GPU%20required%29-475467" in cnr["url"]
