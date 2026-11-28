"""Draws the site icons from the Spokane Rising logos in brand/ (issue #36).

    python3 tools/make_icons.py

Writes, in the site root:
  favicon.svg            the "SR" mark (brand/logo-mark.svg), for browsers that take SVG
  favicon.ico            16, 32 and 48 px; 16 px uses brand/logo-mark-16.svg,
                         with bigger letters and a heavier frame so it stays sharp
  apple-touch-icon.png   180 px, the full logo inset on white, so the frame
                         survives the rounded corners iPhones and iPads add
  icon-192.png, icon-512.png   the full logo, for Android home screens
  icon-maskable-512.png        the logo small and centered on white, inside
                               the circle Android may crop it to

Colors live in the logo files, which come from brand/brand.json via
tools/trace_logo.py; site.webmanifest's colors come from tools/make_brand.py.
Needs Pillow and Playwright's Chromium. Rerun when the logos change; the
files are committed.
"""
import io, os, re, sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import branding  # noqa: E402

BRAND_DIR = os.path.join(ROOT, "brand")


def read(name):
    return open(os.path.join(BRAND_DIR, name), encoding="utf-8").read()


def inner(svg):
    """An SVG's drawing, without its outer <svg> tag."""
    return re.sub(r"^<svg[^>]*>|</svg>\s*$", "", svg.strip())


def placed(svg, scale):
    """The 1000-unit logo on a white square, scaled about the center."""
    o = 1000 * (1 - scale) / 2
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">'
            f'<rect width="1000" height="1000" fill="{branding.COLORS["surface"]}"/>'
            f'<g transform="translate({o:.1f} {o:.1f}) scale({scale})">{inner(svg)}</g></svg>')


def rasterize(jobs):
    """jobs: [(svg, px)] → [PNG bytes], drawn by headless Chromium."""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(device_scale_factor=1)
        for svg, px in jobs:
            pg.set_viewport_size({"width": px, "height": px})
            sized = svg.replace("<svg ", f'<svg width="{px}" height="{px}" ', 1)
            pg.set_content(f'<html><body style="margin:0;background:transparent">{sized}</body></html>')
            out.append(pg.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": px, "height": px}))
        b.close()
    return out


def main():
    mark, mark16, logo = read("logo-mark.svg"), read("logo-mark-16.svg"), read("logo.svg")
    apple = placed(logo, 0.86)      # room for iOS's rounded corners
    maskable = placed(logo, 0.56)   # inside Android's crop circle (radius 40% of the icon)

    open(os.path.join(ROOT, "favicon.svg"), "w").write(mark + "\n")
    p16, p32, p48, p180, p192, p512, pmask = rasterize(
        [(mark16, 16), (mark, 32), (mark, 48), (apple, 180), (logo, 192), (logo, 512), (maskable, 512)])

    ims = [Image.open(io.BytesIO(p)).convert("RGBA") for p in (p16, p32, p48)]
    ims[2].save(os.path.join(ROOT, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                append_images=ims[:2])
    for name, data in [("apple-touch-icon.png", p180), ("icon-192.png", p192), ("icon-512.png", p512),
                       ("icon-maskable-512.png", pmask)]:
        open(os.path.join(ROOT, name), "wb").write(data)
    print("Wrote favicon.svg, favicon.ico, apple-touch-icon.png, icon-192.png, icon-512.png, icon-maskable-512.png")


if __name__ == "__main__":
    main()
