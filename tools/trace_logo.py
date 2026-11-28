"""Rebuilds the Spokane Rising logos as plain shapes, so they never depend on a
font being installed.

The Affinity exports in brand/source/ keep the words as live text set in
Helvetica Neue Condensed Black, which most visitors don't have. This traces the
letters from the 1000px PNGs instead, and draws the square and frame from the
SVG exports' own measurements. Rendered back at 1000px the results match the
PNGs on all but about 0.1% of pixels (anti-aliased edges).

It also draws brand/logo-mark.svg, the small "SR" mark for the favicon, from
the same traced S and R.

Only needed if the logo PNGs change. If a designer exports SVGs with the text
converted to curves, put those in brand/ instead and skip this.

    pip install potracer scipy pillow numpy
    python3 tools/trace_logo.py
"""
import os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
import branding  # noqa: E402

SRC = os.path.join(REPO, "brand", "source")
K = 3  # trace at 3x for smoother curves


def trace(mask):
    import potrace
    # potracer traces the False pixels, so hand it the inverse.
    path = potrace.Bitmap(~mask).trace(turdsize=20, alphamax=1.0, opticurve=True, opttolerance=0.2)
    s = 1 / K
    f = lambda p: f"{p.x * s:.1f} {p.y * s:.1f}"
    d = []
    for c in path:
        d.append("M" + f(c.start_point))
        for g in c.segments:
            d.append(("L" + f(g.c) + "L" + f(g.end_point)) if g.is_corner else ("C" + f(g.c1) + " " + f(g.c2) + " " + f(g.end_point)))
        d.append("Z")
    return "".join(d)


def letters(png, light_letters):
    """The letters only: pixels of the letter color that don't touch the image edge
    (which drops the square or frame, drawn separately)."""
    from scipy import ndimage
    im = Image.open(png).convert("RGB")
    a = np.asarray(im.resize((im.width * K, im.height * K), Image.LANCZOS)).astype(int)
    light = a.sum(axis=2) > (3 * 255 + 250) / 2   # halfway between white and the teal
    m = light if light_letters else ~light
    lab, _ = ndimage.label(m)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    return m & ~np.isin(lab, list(edge))


def glyph_path(mask, x0, y0, scale):
    """A traced letter, moved so its box starts at (x0, y0) and scaled."""
    import potrace
    path = potrace.Bitmap(~mask).trace(turdsize=20, alphamax=1.0, opticurve=True, opttolerance=0.2)
    f = lambda p: f"{x0 + p.x * scale:.2f} {y0 + p.y * scale:.2f}"
    d = []
    for c in path:
        d.append("M" + f(c.start_point))
        for g in c.segments:
            d.append(("L" + f(g.c) + "L" + f(g.end_point)) if g.is_corner else ("C" + f(g.c1) + " " + f(g.c2) + " " + f(g.end_point)))
        d.append("Z")
    return "".join(d)


def mark_svg(teal, small=False):
    """The favicon mark: the logo's frame, with its S and R side by side in the
    bottom-right corner, like the wordmark. 100-unit square."""
    from scipy import ndimage
    m = letters(os.path.join(SRC, "Spokane_Rising_Logo_2026_-_Secondary.png"), False)
    lab, n = ndimage.label(m)
    boxes = ndimage.find_objects(lab)
    # Letter boxes: (top, left, bottom, right). S = leftmost on the top line, R = leftmost on the bottom.
    items = [(b[0].start, b[1].start, b[0].stop, b[1].stop, i + 1) for i, b in enumerate(boxes) if (b[0].stop - b[0].start) > 200]
    mid = sum(t for t, *_ in items) / len(items)
    top = sorted([it for it in items if it[0] < mid], key=lambda it: it[1])
    bot = sorted([it for it in items if it[0] >= mid], key=lambda it: it[1])
    picks = [top[0], bot[0]]   # S, R
    # The 16 px version gets bigger letters and a heavier frame, so 1-pixel
    # strokes don't blur away.
    H = 62.0 if small else 52.0    # letter height in the 100-unit mark
    stroke = 13.0 if small else 10.0
    k = H / max(b - t for t, l, b, r, _ in picks)
    widths = [(r - l) * k for t, l, b, r, _ in picks]
    gap = 3.0
    right, bottom = (88.0, 88.0) if small else (85.0, 86.0)
    x = right - sum(widths) - gap
    parts = []
    for (t, l, b, r, idx), w in zip(picks, widths):
        letter = (lab[t:b, l:r] == idx)
        parts.append(glyph_path(letter, x, bottom - (b - t) * k, k))
        x += w + gap
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="Spokane Rising">'
            f'<rect width="100" height="100" fill="#fff"/><rect x="{stroke / 2}" y="{stroke / 2}" width="{100 - stroke}" height="{100 - stroke}" fill="none" stroke="{teal}" stroke-width="{stroke}"/>'
            f'<path fill="{teal}" d="{"".join(parts)}"/></svg>')


def main():
    teal = branding.COLORS["brand"]
    head = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" role="img" aria-label="Spokane Rising">'
    p = trace(letters(os.path.join(SRC, "Spokane_Rising_Logo_2026_-_Primary.png"), True))
    s = trace(letters(os.path.join(SRC, "Spokane_Rising_Logo_2026_-_Secondary.png"), False))
    with open(os.path.join(REPO, "brand", "logo-primary.svg"), "w") as f:
        f.write(f'{head}<rect width="1000" height="1000" fill="{teal}"/><path fill="#fff" d="{p}"/></svg>')
    # Frame geometry from the Affinity export: rect 14,13 973x972, 75px stroke.
    with open(os.path.join(REPO, "brand", "logo.svg"), "w") as f:
        # No background: the inside of the frame stays transparent, as in the
        # original artwork, so the page shows through.
        f.write(f'{head}<rect x="14" y="13" width="973" height="972" fill="none" stroke="{teal}" stroke-width="75"/>'
                f'<path fill="{teal}" d="{s}"/></svg>')
    with open(os.path.join(REPO, "brand", "logo-mark.svg"), "w") as f:
        f.write(mark_svg(teal))
    with open(os.path.join(REPO, "brand", "logo-mark-16.svg"), "w") as f:
        f.write(mark_svg(teal, small=True))
    print("wrote brand/logo.svg, brand/logo-primary.svg and brand/logo-mark.svg")


if __name__ == "__main__":
    main()
