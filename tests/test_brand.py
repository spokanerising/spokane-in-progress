"""The brand (issue #36): brand/brand.json is the one place for colors, stage
colors, fonts and logos, and everything else follows it.

Checks:
  - brand.css, the manifest and each page's theme-color were regenerated after
    the last brand.json edit (tools/make_brand.py --check)
  - no color is typed anywhere else in the site's code
  - the logos are plain shapes (no text that needs a font installed)
  - colors stay readable: text 4.5:1, map dots 3:1 on the paper and basemap,
    and stages stay apart for people with color-vision differences
  - projects.json carries the same stages as brand.json
  - in a browser, every page loads brand.css and uses its colors
"""
import itertools, json, math, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, REPO
sys.path.insert(0, REPO)
import branding  # noqa: E402

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1


C = branding.COLORS

# ---- generated files are current --------------------------------------------
r = subprocess.run([sys.executable, os.path.join(REPO, "tools", "make_brand.py"), "--check"], capture_output=True, text=True)
check(r.returncode == 0, r.stdout + r.stderr)

# ---- no colors typed outside the brand files ---------------------------------
COLOR = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|%23[0-9a-fA-F]{3,6}\b|rgba?\(\s*\d")
SKIP_DIRS = {"p", "n", "d", "data", "permit-reports", "tests", "brand", ".git", ".github", "node_modules", "__pycache__", "cards-samples", "vendor"}
SKIP_FILES = {
    "brand.css",                         # generated from brand.json
    "branding.py",                       # the loader (its docstring shows examples)
    "tools/trace_logo.py",               # draws the logo files in brand/
    "favicon.svg",                       # drawn by tools/make_icons.py from brand.json
    "tools/setup-sheet-validation.gs",   # the retired Google Sheet, not the site
}
CODE = (".html", ".css", ".js", ".py", ".svg")
found = []
for root, dirs, files in os.walk(REPO):
    rel_root = os.path.relpath(root, REPO)
    if rel_root.split(os.sep)[0] in SKIP_DIRS:
        dirs[:] = []
        continue
    for f in files:
        rel = os.path.normpath(os.path.join(rel_root, f)).replace(os.sep, "/")
        if not f.endswith(CODE) or rel in SKIP_FILES:
            continue
        for n, line in enumerate(open(os.path.join(root, f), encoding="utf-8", errors="replace"), 1):
            if "brand-exempt" in line or '<meta name="theme-color"' in line:
                continue
            if COLOR.search(line):
                found.append(f"{rel}:{n}: {line.strip()[:120]}")
check(not found, "Colors typed outside brand/brand.json (use a brand.css variable or branding.COLORS):\n  " + "\n  ".join(found))

# ---- every page loads brand.css before styles.css ----------------------------
for page in ["index.html", "about.html", "stats.html", "glossary.html", "404.html", "styleguide.html", "admin/index.html"]:
    s = open(os.path.join(REPO, page), encoding="utf-8").read()
    b, st = s.find('brand.css" rel="stylesheet"'), s.find('styles.css" rel="stylesheet"')
    check(0 <= b < st, f"{page}: brand.css must be linked before styles.css")

# ---- the header logo on every public page --------------------------------------
for page in ["index.html", "about.html", "stats.html", "glossary.html", "404.html"]:
    s = open(os.path.join(REPO, page), encoding="utf-8").read()
    check(f'<a class="lockup__logo" href="{branding.BRAND["parent"]["url"]}">' in s, f"{page}: logo should link to {branding.BRAND['parent']['url']}")
    check(re.search(r'<img class="lockup__img" src="/?' + re.escape(branding.BRAND["logo"]["main"]) + r'" alt="' + re.escape(branding.BRAND["parent"]["name"]) + '"', s), f"{page}: logo image and its name")
    check(re.search(r'<a class="masthead__home" href="(/|\./)">', s), f"{page}: the title links home")

# ---- logos are shapes, not text ----------------------------------------------
for key, rel in branding.BRAND["logo"].items():
    if key.startswith("_"):
        continue
    s = open(os.path.join(REPO, rel), encoding="utf-8").read()
    check(s.lstrip().startswith("<svg") and "<text" not in s and "font-family" not in s, f"{rel} must be outlines only (no <text>), so it never depends on a font")
    check(C["brand"] in s, f"{rel} should use the brand color {C['brand']}")
# The secondary logo has no background: inside the frame stays transparent.
main_logo = open(os.path.join(REPO, branding.BRAND["logo"]["main"]), encoding="utf-8").read()
check(not re.search(r'<rect(?![^>]*fill="none")[^>]*width="1000"', main_logo), "brand/logo.svg should have no background fill (keep it transparent)")

# ---- contrast -----------------------------------------------------------------
def lin(h):
    c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
def lum(h):
    r, g, b = lin(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
def contrast(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)

GROUNDS = {name: C[name] for name in ("paper", "paper-2", "surface")}
for name in ("ink", "ink-2", "muted", "link", "alert"):
    for g, bg in GROUNDS.items():
        check(contrast(C[name], bg) >= 4.5, f"text color {name} {C[name]} on {g} {bg} is {contrast(C[name], bg):.2f}:1; needs 4.5:1")

# Map dots against the paper and Positron's land, residential and park fills (WCAG 1.4.11).
MAP = {"paper": C["paper"], "land": "#f2f3f0", "residential": "#eaeae6", "parks": "#e6e9e5"}  # brand-exempt: the basemap's own colors
for s in branding.STAGES:
    for g, bg in MAP.items():
        check(contrast(s["color"], bg) >= 3, f"stage {s['name']} {s['color']} on {g} is {contrast(s['color'], bg):.2f}:1; needs 3:1")

# ---- stages stay apart with color-vision differences ---------------------------
# Machado et al. (2009) full-strength simulations in linear RGB, distance in OKLab x100.
CVD = {
    "protanopia":  [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deuteranopia": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritanopia":  [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}
def oklab(rgb):
    r, g, b = [min(1, max(0, v)) for v in rgb]
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (x ** (1 / 3) for x in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)
def seen(h, kind):
    c = lin(h)
    if kind:
        c = [sum(CVD[kind][i][j] * c[j] for j in range(3)) for i in range(3)]
    return oklab(c)
MIN_GAP = 9.5   # the narrowest pair, worst case across normal and color-blind vision (Nov. 2026 palette: 10.0; the old reds were 6.2)
for kind in (None, *CVD):
    for a, b in itertools.combinations(branding.STAGES, 2):
        gap = 100 * math.dist(seen(a["color"], kind), seen(b["color"], kind))
        check(gap >= MIN_GAP, f"{a['name']} and {b['name']} are only {gap:.1f} apart ({kind or 'normal vision'}); need {MIN_GAP}")

# ---- the data carries the brand's stages ---------------------------------------
data = json.load(open(os.path.join(REPO, "projects.json"), encoding="utf-8"))
check(data["stages"] == branding.STAGES, "projects.json stages differ from brand/brand.json; run python3 build.py (or the data workflow)")

# ---- in a browser -------------------------------------------------------------
from playwright.sync_api import sync_playwright  # noqa: E402
site, _ = make_site(with_facts=False)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page()
    wire(pg, site)
    for path in ["/", "/about.html", "/stats.html", "/glossary.html", "/styleguide.html", "/nope"]:
        pg.goto(SITE + path)
        got = pg.evaluate("""() => {
          const css = getComputedStyle(document.documentElement);
          const v = (n) => css.getPropertyValue('--' + n).trim();
          return { ink: v('ink'), paper: v('paper'), stage0: v('stage-0'), chevron: v('icon-chevron').length,
                   bg: getComputedStyle(document.body).backgroundColor };
        }""")
        check(got["ink"] == C["ink"] and got["paper"] == C["paper"], f"{path}: brand.css not loaded ({got})")
        check(got["stage0"] == branding.STAGES[0]["color"], f"{path}: stage colors missing from brand.css")
        check(got["chevron"] > 50, f"{path}: icon variables missing")
    # The header logo shows the page through its frame.
    pg.goto(SITE + "/")
    pg.wait_for_selector(".lockup__img")
    pg.wait_for_function("() => document.querySelector('.lockup__img').complete")
    box = pg.locator(".lockup__img").bounding_box()
    from PIL import Image
    import io
    shot = Image.open(io.BytesIO(pg.screenshot(clip={"x": box["x"] + box["width"] * 0.3, "y": box["y"] + box["height"] * 0.25, "width": 2, "height": 2}))).convert("RGB")
    check(shot.getpixel((0, 0)) == branding.rgb("paper"), f"inside the logo's frame should be the page color, got {shot.getpixel((0, 0))}")
    # The map's colors come from brand.css too.
    pg.goto(SITE + "/")
    pg.wait_for_function("() => typeof map !== 'undefined' && map && map.getLayer && map.getLayer('project-dot')", timeout=15000)
    stroke = pg.evaluate("() => JSON.stringify(map.getPaintProperty('project-dot', 'circle-stroke-color'))")
    check(C["ink"] in stroke and C["surface"] in stroke, f"map dot edges should use brand colors: {stroke}")
    b.close()

print(f"{ok} checks passed")
