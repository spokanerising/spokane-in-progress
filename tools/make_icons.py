"""Draws the site icons: the favicon (option B, chosen Nov. 26, 2026: an ink
square, a paper Newsreader S, and the five stage colors along the bottom).

    python3 tools/make_icons.py

Writes, in the site root:
  favicon.svg            the master, for browsers that take SVG favicons
  favicon.ico            16, 32 and 48 px, for everything else
  apple-touch-icon.png   180 px, for iPhone and iPad home screens
  icon-192.png, icon-512.png            for Android home screens
  icon-maskable-512.png                 the same with room for Android's crop
  site.webmanifest

The S is the real Newsreader 600 glyph, turned into a path, so the SVG needs
no font. The 16 px size is drawn separately: a taller color strip with no gaps
between colors, because 1px gaps blur away at that size. Needs fontTools and
brotli (pip install fonttools brotli), Pillow, and Playwright's Chromium.
Rerun only when the design changes; the files are committed.
"""
import io, json, os, sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from make_site_card import font_path  # noqa: E402

sys.path.insert(0, ROOT)
import branding  # noqa: E402  (brand/brand.json)

INK, PAPER = branding.COLORS["ink"], branding.COLORS["paper"]
RAMP = [s["color"] for s in branding.STAGES][:5]   # Pre-Application … Complete


def s_glyph():
    """The S as an SVG path in font units (y up), with its bounds."""
    font = TTFont(font_path("newsreader", "newsreader-latin-600-normal.woff2"))
    gs = font.getGlyphSet()
    name = font.getBestCmap()[ord("S")]
    pen = SVGPathPen(gs)
    gs[name].draw(pen)
    bounds = BoundsPen(gs)
    gs[name].draw(bounds)
    return pen.getCommands(), bounds.bounds


def placed_s(size, cx, top, height):
    """A <path> with the S scaled to `height` px tall, centered on cx, its top at `top`."""
    d, (x0, y0, x1, y1) = s_glyph()
    k = height / (y1 - y0)
    tx = cx - (x0 + x1) / 2 * k
    ty = top + y1 * k              # flip: font y goes up, SVG y goes down
    return f'<path d="{d}" fill="{PAPER}" transform="translate({tx:.3f} {ty:.3f}) scale({k:.5f} {-k:.5f})"/>'


def master_svg(radius=5, inset=0.0):
    """64-unit design. inset (0–1) shrinks the artwork inside a full-bleed
    square, for the maskable icon's safe zone."""
    inner = 64 * (1 - inset)
    o = (64 - inner) / 2
    u = inner / 64
    bars = "".join(
        f'<rect x="{o + (6 + i * 10.8) * u:.2f}" y="{o + 50 * u:.2f}" width="{9.6 * u:.2f}" height="{8 * u:.2f}" fill="{c}"/>'
        for i, c in enumerate(RAMP))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<rect width="64" height="64" rx="{radius}" fill="{INK}"/>'
            f'{placed_s(64, 32, o + 9 * u, 34 * u)}{bars}</svg>')


def small_svg():
    """16-unit design for the 16 px favicon: S on top, a 4px strip of the five
    colors touching each other along the bottom."""
    w = 16 / 5
    bars = "".join(f'<rect x="{i * w:.2f}" y="12" width="{w + 0.05:.2f}" height="4" fill="{c}"/>' for i, c in enumerate(RAMP))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
            f'<rect width="16" height="16" rx="1" fill="{INK}"/>{placed_s(16, 8, 1.2, 9.6)}{bars}</svg>')


def rasterize(jobs):
    """jobs: [(svg, px)] → [PNG bytes], drawn by headless Chromium."""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(device_scale_factor=1)
        for svg, px in jobs:
            pg.set_viewport_size({"width": px, "height": px})
            pg.set_content(f'<html><body style="margin:0;background:transparent">'
                           f'{svg.replace("<svg ", f"<svg width=\"{px}\" height=\"{px}\" ", 1)}</body></html>')
            out.append(pg.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": px, "height": px}))
        b.close()
    return out


def main():
    master = master_svg()
    square = master_svg(radius=0)              # home screens round the corners themselves
    maskable = master_svg(radius=0, inset=0.2)
    small = small_svg()

    open(os.path.join(ROOT, "favicon.svg"), "w").write(master + "\n")
    p16, p32, p48, p180, p192, p512, pmask = rasterize(
        [(small, 16), (master, 32), (master, 48), (square, 180), (square, 192), (square, 512), (maskable, 512)])

    ims = [Image.open(io.BytesIO(p)).convert("RGBA") for p in (p16, p32, p48)]
    ims[2].save(os.path.join(ROOT, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                append_images=ims[:2])
    for name, data in [("apple-touch-icon.png", p180), ("icon-192.png", p192), ("icon-512.png", p512),
                       ("icon-maskable-512.png", pmask)]:
        open(os.path.join(ROOT, name), "wb").write(data)

    manifest = {
        "name": "Spokane in Progress",
        "short_name": "Spokane in Progress",
        "description": "Tracking Spokane's housing progress.",
        "start_url": "/",
        "display": "browser",
        "background_color": PAPER,
        "theme_color": PAPER,
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    open(os.path.join(ROOT, "site.webmanifest"), "w").write(json.dumps(manifest, indent=2) + "\n")
    print("Wrote favicon.svg, favicon.ico, apple-touch-icon.png, icon-192.png, icon-512.png, icon-maskable-512.png, site.webmanifest")


if __name__ == "__main__":
    main()
