"""Accessibility (issue #31): axe-core's WCAG 2.0/2.1/2.2 A and AA rules on
every page type and the main open states, at phone and desktop widths, plus
checks axe can't make: tooltips you can point at, Escape in the editor and in
"More filters", and the zero-count stage chips."""
import json, os, shutil, subprocess, sys, tarfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, REPO, HERE
from playwright.sync_api import sync_playwright

AXE_VERSION = "4.14.1"
AXE_DIR = os.path.join(HERE, ".vendor", "axe-core")

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1


def ensure_axe():
    """Like maplibre: an npm copy, fetched once into tests/.vendor (git-ignored)."""
    path = os.path.join(AXE_DIR, "axe.min.js")
    if os.path.isfile(path):
        return open(path).read()
    target = os.path.join(HERE, ".vendor")
    os.makedirs(target, exist_ok=True)
    name = subprocess.check_output(["npm", "pack", f"axe-core@{AXE_VERSION}", "--silent"], cwd=target, text=True).strip().splitlines()[-1]
    with tarfile.open(os.path.join(target, name)) as tar:
        tar.extractall(target, filter="data")
    if os.path.isdir(AXE_DIR):
        shutil.rmtree(AXE_DIR)
    os.replace(os.path.join(target, "package"), AXE_DIR)
    os.remove(os.path.join(target, name))
    return open(path).read()


# Problems already on the fix list (issue #31, phase 2). Each entry is
# (page state, axe rule); take it out when the fix ships, so it stays fixed.
KNOWN = set()

# ---- stage colors stand out from the map (WCAG 1.4.11, 3:1) ------------------
# Positron's land, residential and park fills: what most pins sit on.
def _lum(h):
    c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def _contrast(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)
for stage in json.load(open(os.path.join(REPO, "projects.json")))["stages"]:
    for name, bg in (("land", "#f2f3f0"), ("residential", "#eaeae6"), ("parks", "#e6e9e5")):
        check(_contrast(stage["color"], bg) >= 3, f"{stage['name']} {stage['color']} on {name}: {_contrast(stage['color'], bg):.2f}:1")

AXE = ensure_axe()
site, data = make_site(with_facts=True)
shutil.copy(os.path.join(REPO, "boundaries.geojson"), site)
shutil.copy(os.path.join(REPO, "editor.js"), site)
shutil.copytree(os.path.join(REPO, "admin"), os.path.join(site, "admin"))
projects = data["projects"]
big = max(projects, key=lambda p: p.get("units") or 0)
detailed = max(projects, key=lambda p: len(p.get("fields") or []) + len(p.get("permits") or []))
MAP_READY = "typeof map !== 'undefined' && map && map.getSource && map.getSource('projects')"


def fake_api(route):
    body = {"email": "spokanerising@gmail.com"} if route.request.url.endswith("/api/me") else {"ok": True}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def run_axe(pg):
    if not pg.evaluate("typeof axe !== 'undefined'"):
        pg.add_script_tag(content=AXE)
    return pg.evaluate("""async () => {
      const r = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } });
      return r.violations.map(v => ({ id: v.id, help: v.help, where: v.nodes.slice(0, 3).map(n => n.target.join(' ')) }));
    }""")


def home(pg):
    pg.goto(SITE + "/"); pg.wait_for_selector(".card", state="attached"); pg.wait_for_function(MAP_READY); pg.wait_for_timeout(500)

def opened(sel):
    def f(pg):
        home(pg)
        if not pg.locator(sel).is_visible() and pg.locator("[data-view=list]").is_visible():
            pg.click("[data-view=list]"); pg.wait_for_timeout(300)
        pg.click(sel); pg.wait_for_timeout(400)
    return f

def goto(path, ready=None):
    def f(pg):
        pg.goto(SITE + path)
        if ready: pg.wait_for_selector(ready, state="attached")
        pg.wait_for_timeout(700)
    return f

def editor(pg):
    pg.goto(f"{SITE}/?p={detailed['id']}"); pg.wait_for_selector("[data-edit-project]", state="attached"); pg.wait_for_timeout(300)
    pg.locator("[data-edit-project]:visible").first.click(); pg.wait_for_selector("dialog.editor[open]"); pg.wait_for_timeout(300)

STATES = {
    "map": home,
    "list": goto("/?view=list", ".card"),
    "more-filters": opened("#more-filters"),
    "share-menu": opened("#share-view"),
    "how-to-read": opened("#how-to-read"),
    "project": goto(f"/?p={detailed['id']}", "#detail-tools [data-copy-project]"),
    "project-big": goto(f"/?p={big['id']}", "#detail-tools [data-copy-project]"),
    "neighborhood": goto("/?hood=riverside", ".card"),
    "district": goto("/?district=2", ".card"),
    "about": goto("/about.html"),
    "stats": goto("/stats.html", "#chart-size .chart__tools"),
    "glossary": goto("/glossary.html"),
    "404": goto("/no-such-page"),
    "admin": goto("/admin/"),
    "editor": editor,
}
VIEWPORTS = {"phone": {"width": 390, "height": 844}, "desktop": {"width": 1280, "height": 900}}

with sync_playwright() as pw:
    b = pw.chromium.launch()

    # ---- axe on every state, both widths ---------------------------------
    for vpn, vp in VIEWPORTS.items():
        for name, setup in STATES.items():
            if vpn == "desktop" and name == "more-filters":
                continue  # desktop shows every filter already
            ctx = b.new_context(viewport=vp)
            if name == "editor":
                ctx.add_init_script("localStorage.setItem('sip-editor', '1')")
            pg = ctx.new_page(); wire(pg, site); pg.route(f"{SITE}/api/**", fake_api)
            setup(pg)
            found = run_axe(pg)
            new = [v for v in found if (name, v["id"]) not in KNOWN]
            check(not new, f"{vpn}/{name}: " + "; ".join(f"{v['id']} ({v['help']}) at {v['where']}" for v in new))
            ctx.close()
    # A known problem that has been fixed should come off the list.
    for name in sorted({k for k, _ in KNOWN}):
        ctx = b.new_context(viewport=VIEWPORTS["desktop"]); pg = ctx.new_page(); wire(pg, site)
        STATES[name](pg)
        still = {(name, v["id"]) for v in run_axe(pg)}
        gone = {k for k in KNOWN if k[0] == name} - still
        check(not gone, f"fixed, take off KNOWN: {sorted(gone)}")
        ctx.close()

    # ---- the project view never hides focus behind it --------------------
    # Phones: the page behind is inert. Tablets: Tab wraps inside the panel.
    # Desktop: the panel has its own column. Either way, 60 Tabs stay visible.
    for w, h in ((390, 844), (700, 900), (1024, 768), (1280, 900)):
        ctx = b.new_context(viewport={"width": w, "height": h}); pg = ctx.new_page(); wire(pg, site)
        pg.goto(f"{SITE}/?view=list"); pg.wait_for_selector(".card", state="attached"); pg.wait_for_timeout(600)
        pg.locator(".card:visible").first.focus(); pg.keyboard.press("Enter"); pg.wait_for_selector("#detail:not([hidden])"); pg.wait_for_timeout(300)
        hidden_behind = []
        for _ in range(60):
            pg.keyboard.press("Tab")
            hit = pg.evaluate("""() => { const e = document.activeElement, d = document.getElementById('detail');
              if (!e || d.contains(e)) return null; const r = e.getBoundingClientRect(), q = d.getBoundingClientRect();
              const under = r.left >= q.left && r.right <= q.right && r.top >= q.top && r.bottom <= q.bottom;
              return under ? (e.getAttribute('aria-label') || e.textContent || e.id).trim().slice(0, 30) : null; }""")
            if hit: hidden_behind.append(hit)
        check(not hidden_behind, f"{w}px: focus went behind the project: {hidden_behind[:5]}")
        if w == 390:
            check(pg.evaluate("document.querySelectorAll('[inert]').length") > 0, "phone: the page behind is inert")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        check(pg.evaluate("document.querySelectorAll('[inert]').length") == 0, f"{w}px: nothing left inert after closing")
        check(pg.evaluate("document.activeElement.classList.contains('card')"), f"{w}px: focus back on the card")
        ctx.close()

    # ---- the tab title names what's on screen -----------------------------
    ctx = b.new_context(viewport=VIEWPORTS["desktop"]); pg = ctx.new_page(); wire(pg, site)
    pg.goto(f"{SITE}/?p={detailed['id']}"); pg.wait_for_selector("#detail:not([hidden])"); pg.wait_for_timeout(300)
    check(pg.title() == f"{detailed['name']} · Spokane in Progress", f"project title: {pg.title()}")
    pg.goto(f"{SITE}/?hood=riverside"); pg.wait_for_selector(".card", state="attached"); pg.wait_for_timeout(300)
    check(pg.title() == "Riverside · Spokane in Progress", f"neighborhood title: {pg.title()}")
    pg.goto(f"{SITE}/?district=2"); pg.wait_for_selector(".card", state="attached"); pg.wait_for_timeout(300)
    check(pg.title() == "District 2 · Spokane in Progress", f"district title: {pg.title()}")
    pg.goto(f"{SITE}/"); pg.wait_for_selector(".card", state="attached"); pg.wait_for_timeout(300)
    check(pg.title() == "Spokane in Progress", f"home title: {pg.title()}")
    ctx.close()

    # ---- Stats: every chart's numbers reach a screen reader ----------------
    ctx = b.new_context(viewport=VIEWPORTS["desktop"]); pg = ctx.new_page(); wire(pg, site)
    STATES["stats"](pg)
    check(pg.locator('[role="img"]').count() == 0, "no chart is hidden inside role=img")
    check(pg.locator("#chart-density .strip__list a").count() == pg.locator("#chart-density .strip__dot").count() > 0, "every density dot has a link in the list")
    check(pg.evaluate("[...document.querySelectorAll('.strip__dot')].every(a => a.tabIndex === -1 && a.closest('[aria-hidden=true]'))"), "the dots themselves are a picture")
    check("approved" in pg.locator("#chart-district .bars__value .visually-hidden").first.text_content() or
          "applied" in pg.locator("#chart-district .bars__value .visually-hidden").first.text_content(), "bars spell out the stage split")
    ctx.close()

    # ---- zero-count chips stay readable (4.5:1, not faded) -----------------
    ctx = b.new_context(viewport=VIEWPORTS["desktop"]); pg = ctx.new_page(); wire(pg, site)
    pg.goto(f"{SITE}/?hood=riverside"); pg.wait_for_selector(".chip.is-zero", state="attached"); pg.wait_for_timeout(300)
    check(pg.evaluate("[...document.querySelectorAll('.chip.is-zero')].every(c => getComputedStyle(c).opacity === '1')"), "zero chips not faded")
    ctx.close()

    # ---- tooltips: you can move the pointer onto one -----------------------
    ctx = b.new_context(viewport=VIEWPORTS["desktop"]); pg = ctx.new_page(); wire(pg, site)
    home(pg)
    tip = "(() => { const t = document.querySelector('.tip-label'); return !!t && t.classList.contains('is-on'); })()"
    pg.hover("#share-view"); pg.wait_for_timeout(700)
    check(pg.evaluate(tip), "tooltip shows on hover")
    r = pg.locator(".tip-label").bounding_box()
    pg.mouse.move(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2, steps=6); pg.wait_for_timeout(500)
    check(pg.evaluate(tip), "tooltip stays while the pointer is on it")
    pg.mouse.move(640, 300); pg.wait_for_timeout(500)
    check(not pg.evaluate(tip), "tooltip goes when the pointer leaves")
    pg.hover("#share-view"); pg.wait_for_timeout(700); pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check(not pg.evaluate(tip), "Escape hides the tooltip")
    ctx.close()

    # ---- editor: Escape closes only the form, focus back on the pencil ------
    ctx = b.new_context(viewport=VIEWPORTS["desktop"]); ctx.add_init_script("localStorage.setItem('sip-editor', '1')")
    pg = ctx.new_page(); wire(pg, site); pg.route(f"{SITE}/api/**", fake_api)
    pg.goto(f"{SITE}/?p={detailed['id']}"); pg.wait_for_selector("[data-edit-project]", state="attached"); pg.wait_for_timeout(300)
    pen = pg.locator("#detail-tools [data-edit-project]")
    pen.focus(); pg.keyboard.press("Enter"); pg.wait_for_selector("dialog.editor[open]")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check(not pg.evaluate("!!document.querySelector('dialog.editor[open]')"), "Escape closes the form")
    check(not pg.evaluate("document.getElementById('detail').hidden"), "the project stays open")
    check(pg.evaluate("document.activeElement === document.querySelector('#detail-tools [data-edit-project]')"), "focus back on the pencil")
    pen.click(); pg.wait_for_selector("dialog.editor[open]")
    pg.locator("dialog.editor [data-close]").first.click(); pg.wait_for_timeout(300)
    check(pg.evaluate("document.activeElement === document.querySelector('#detail-tools [data-edit-project]')"), "focus back on the pencil after ×")
    ctx.close()

    # ---- phones: Escape closes "More filters" -----------------------------
    ctx = b.new_context(viewport=VIEWPORTS["phone"]); pg = ctx.new_page(); wire(pg, site)
    pg.goto(f"{SITE}/?view=list"); pg.wait_for_selector(".card", state="attached"); pg.wait_for_timeout(500)
    pg.click("#more-filters"); pg.wait_for_timeout(200)
    check(pg.evaluate("document.body.dataset.filters") == "open", "More filters opens")
    pg.keyboard.press("Tab"); pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check(pg.evaluate("document.body.dataset.filters") != "open", "Escape closes More filters")
    check(pg.evaluate("document.activeElement.id") == "more-filters", "focus back on the button")
    ctx.close()
    b.close()

print(f"{ok} checks passed")
