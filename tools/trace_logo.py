"""Rebuilds the Spokane Rising logos as plain shapes, so they never depend on a
font being installed.

The Affinity exports in brand/source/ keep the words as live text set in
Helvetica Neue Condensed Black, which most visitors don't have. This traces the
letters from the 1000px PNGs instead, and draws the square and frame from the
SVG exports' own measurements. Rendered back at 1000px the results match the
PNGs on all but about 0.1% of pixels (anti-aliased edges).

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


def main():
    teal = branding.COLORS["brand"]
    head = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" role="img" aria-label="Spokane Rising">'
    p = trace(letters(os.path.join(SRC, "Spokane_Rising_Logo_2026_-_Primary.png"), True))
    s = trace(letters(os.path.join(SRC, "Spokane_Rising_Logo_2026_-_Secondary.png"), False))
    with open(os.path.join(REPO, "brand", "logo-primary.svg"), "w") as f:
        f.write(f'{head}<rect width="1000" height="1000" fill="{teal}"/><path fill="#fff" d="{p}"/></svg>')
    # Frame geometry from the Affinity export: rect 14,13 973x972, 75px stroke.
    with open(os.path.join(REPO, "brand", "logo.svg"), "w") as f:
        f.write(f'{head}<rect width="1000" height="1000" fill="#fff"/><rect x="14" y="13" width="973" height="972" fill="none" stroke="{teal}" stroke-width="75"/>'
                f'<path fill="{teal}" d="{s}"/></svg>')
    print("wrote brand/logo.svg and brand/logo-primary.svg")


if __name__ == "__main__":
    main()
