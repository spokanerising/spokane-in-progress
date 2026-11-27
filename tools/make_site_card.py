"""Draws the site's sharing card: og-card.png, 1200 x 630, the image that
appears when the home page or About page is shared (and, until each project
has its own card, project pages too).

    python3 tools/make_site_card.py

Draws an HTML page in headless Chrome with the site's own typefaces (fetched
once from npm into tools/.fonts) and saves a screenshot. The map side
plots every project from projects.json over the council district outlines in
boundaries.geojson, colored by stage and sized by homes, like the site.
Needs: pip install playwright && python -m playwright install chromium
"""
import base64, json, math, os, subprocess, tarfile, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONTS = os.path.join(HERE, ".fonts")
OUT = os.path.join(ROOT, "og-card.png")
W, H = 1200, 630

FONT_FILES = {
    ("Newsreader", 600, "normal"): ("newsreader", "newsreader-latin-600-normal.woff2"),
    ("Newsreader", 500, "italic"): ("newsreader", "newsreader-latin-500-italic.woff2"),
    ("Newsreader", 500, "normal"): ("newsreader", "newsreader-latin-500-normal.woff2"),
    ("Libre Franklin", 500, "normal"): ("libre-franklin", "libre-franklin-latin-500-normal.woff2"),
    ("Libre Franklin", 600, "normal"): ("libre-franklin", "libre-franklin-latin-600-normal.woff2"),
}


def font_path(package, filename):
    folder = os.path.join(FONTS, package)
    path = os.path.join(folder, "package", "files", filename)
    if not os.path.exists(path):
        os.makedirs(folder, exist_ok=True)
        name = subprocess.check_output(["npm", "pack", f"@fontsource/{package}", "--silent"], cwd=folder, text=True).strip().splitlines()[-1]
        with tarfile.open(os.path.join(folder, name)) as tar:
            tar.extractall(folder, filter="data")
        os.remove(os.path.join(folder, name))
    return path


def font_faces():
    css = []
    for (family, weight, style), (package, filename) in FONT_FILES.items():
        data = base64.b64encode(open(font_path(package, filename), "rb").read()).decode()
        css.append(f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};"
                   f"src:url(data:font/woff2;base64,{data}) format('woff2');}}")
    return "\n".join(css)


def map_svg(projects, outlines, stages, box_w, box_h):
    """The city, as council districts, with a dot per project."""
    districts = [f for f in outlines.get("features", []) if f["properties"].get("kind") == "district"]
    rings = []
    for f in districts:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        rings += [ring for poly in polys for ring in poly]
    pts = [pt for ring in rings for pt in ring] or [[p["lng"], p["lat"]] for p in projects]
    lng0, lng1 = min(p[0] for p in pts), max(p[0] for p in pts)
    lat0, lat1 = min(p[1] for p in pts), max(p[1] for p in pts)
    kx = math.cos(math.radians((lat0 + lat1) / 2))
    pad = 6   # room for the outline's stroke at the box edges
    scale = min((box_w - 2 * pad) / ((lng1 - lng0) * kx), (box_h - 2 * pad) / (lat1 - lat0))
    ox = (box_w - (lng1 - lng0) * kx * scale) / 2
    oy = (box_h - (lat1 - lat0) * scale) / 2
    xy = lambda lng, lat: (ox + (lng - lng0) * kx * scale, oy + (lat1 - lat) * scale)
    color = {s["name"]: s["color"] for s in stages}
    # Just the city's outer edge (no district lines): the districts drawn
    # with a wide edge, then filled on top, which hides the inside borders.
    outline = "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (xy(*pt[:2]) for pt in ring)) + "Z" for ring in rings)
    parts = [f'<path d="{outline}" fill="#f2eee5" stroke="#b9b2a5" stroke-width="4" stroke-linejoin="round"/>',
             f'<path d="{outline}" fill="#f2eee5" stroke="#f2eee5" stroke-width="2" stroke-linejoin="round"/>']
    for p in sorted(projects, key=lambda p: -(p.get("units") or 0)):
        if not (isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float))):
            continue
        x, y = xy(p["lng"], p["lat"])
        if not (-10 < x < box_w + 10 and -10 < y < box_h + 10):
            continue
        u = p.get("units") or 0
        c = color.get(p.get("status"), "#6e8086")
        if u > 0:
            r = max(3.2, 0.95 * math.sqrt(u))
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{c}" fill-opacity="0.9" stroke="#fff" stroke-width="1"/>')
        else:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="#faf8f3" stroke="{c}" stroke-width="1.8"/>')
    return f'<svg width="{box_w}" height="{box_h}" viewBox="0 0 {box_w} {box_h}">{"".join(parts)}</svg>'


def stage_bar(projects, stages):
    homes = {s["name"]: 0 for s in stages}
    for p in projects:
        if (p.get("units") or 0) > 0 and p.get("status") in homes:
            homes[p["status"]] += p["units"]
    segs = "".join(f'<i style="flex-grow:{n};background:{s["color"]}"></i>' for s in stages if (n := homes[s["name"]]) > 0)
    return f'<div class="bar">{segs}</div>'


def html(projects, outlines, stages):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{font_faces()}
* {{ margin: 0; box-sizing: border-box; }}
body {{ width: {W}px; height: {H}px; background: #faf8f3; color: #121212; overflow: hidden; }}
.card {{ position: relative; width: {W}px; height: {H}px; padding: 64px 0 0 72px; }}
.rule {{ position: absolute; left: 72px; right: 72px; bottom: 76px; height: 1px; background: #121212; }}
h1 {{ font: 600 92px/0.98 'Newsreader'; letter-spacing: -0.5px; width: 560px; }}
h1 em {{ font-weight: 500; font-style: italic; }}
p.tag {{ margin-top: 26px; font: 500 36px/1.2 'Newsreader'; color: #3a3936; width: 520px; }}
.bar {{ display: flex; gap: 3px; width: 470px; height: 16px; margin-top: 92px; }}
.bar i {{ display: block; }}
.key {{ margin-top: 12px; font: 500 15px 'Libre Franklin'; color: #6b6964; letter-spacing: 0.02em; }}
.url {{ position: absolute; left: 72px; bottom: 36px; font: 600 17px 'Libre Franklin'; letter-spacing: 0.09em; text-transform: uppercase; }}
.map {{ position: absolute; right: 56px; top: 44px; }}
</style></head><body><div class="card">
<h1>Spokane <em>in Progress</em></h1>
<p class="tag">Tracking Spokane’s housing progress.</p>
{stage_bar(projects, stages)}
<p class="key">Homes by stage, proposed to complete</p>
<div class="map">{map_svg(projects, outlines, stages, 520, 470)}</div>
<div class="rule"></div>
<p class="url">projects.spokanerising.com</p>
</div></body></html>"""


def main():
    from playwright.sync_api import sync_playwright
    data = json.load(open(os.path.join(ROOT, "projects.json"), encoding="utf-8"))
    try:
        outlines = json.load(open(os.path.join(ROOT, "boundaries.geojson"), encoding="utf-8"))
    except (OSError, ValueError):
        outlines = {"features": []}
    page_html = html(data["projects"], outlines, data["stages"])
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(page_html)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.goto("file://" + f.name)
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(200)
        pg.screenshot(path=OUT, type="png")
        b.close()
    os.remove(f.name)
    print(f"Wrote {OUT} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
