"""Stats, About and Glossary as three pages (issue #30).

Every page has the same four-item nav with the current page marked; the map
links to all three. Old links into the combined page (about.html#g-…,
#h-charts, #h-data) land on the page that has that part now, and About's own
sections stay put. Stats draws its numbers and charts; About fills in the
live unit-count limit and its stage list from glossary.json; Glossary lists
every term with jump links to each group. Nothing runs off a phone screen."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, REPO
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

SHOTS = os.path.join(os.path.dirname(__file__), ".shots")
os.makedirs(SHOTS, exist_ok=True)
GLOSS = json.load(open(os.path.join(REPO, "glossary.json")))
PAGES = {"stats.html": "Stats", "about.html": "About", "glossary.html": "Glossary"}
NAV = ["Map", "Stats", "About", "Glossary"]

site, data = make_site(with_facts=False)
missing = sum(1 for p in data["projects"] if not (p.get("units") or 0) > 0)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)

    # ---- the nav, on every page -----------------------------------------------
    for f, name in PAGES.items():
        pg.goto(f"{SITE}/{f}")
        links = pg.locator(".pagenav a")
        check([links.nth(i).text_content().strip() for i in range(links.count())] == NAV, f"{f}: nav is {NAV}")
        check(pg.locator('.pagenav a[aria-current="page"]').text_content().strip() == name, f"{f}: {name} is marked current")
        check(pg.locator("title").inner_text().startswith(name), f"{f}: title starts with {name}")
        check(pg.locator('link[rel="canonical"]').get_attribute("href").endswith("/" + f), f"{f}: canonical")
    nf = open(os.path.join(REPO, "404.html")).read()
    for href in ('href="/stats"', 'href="/about"', 'href="/glossary"'):
        check(href in nf, f"404 nav has {href}")

    # ---- Stats ----------------------------------------------------------------
    pg.goto(f"{SITE}/stats.html")
    pg.wait_for_selector("#stats .stat")
    check(pg.locator("#stats .stat").count() == 5, "five big numbers")
    for c in ["type", "district", "hood", "quarter", "size"]:
        check(pg.locator(f"#chart-{c} .chart__title").count() == 1, f"chart {c} drawn")
        check(pg.locator(f"#chart-{c} .chart__tools button").count() == 1, f"chart {c} has its download")
    check("Data as of" in pg.locator("#asof").inner_text(), "Stats says when the data is from")
    check(pg.locator("#download").is_visible(), "the CSV download is on Stats")
    check(pg.locator('a[href="about.html#h-limits"]').count() == 1 and pg.locator('a[href="about.html#h-differ"]').count() == 1,
          "Stats points to the limits and to why the numbers differ")
    check("leave out" not in pg.locator("#dek").inner_text(), "the dek no longer promises the limits")
    pg.screenshot(path=os.path.join(SHOTS, "stats.png"), full_page=True)

    # ---- About ----------------------------------------------------------------
    pg.goto(f"{SITE}/about.html")
    pg.wait_for_function("document.getElementById('asof').textContent.includes('Data as of')")
    order = pg.evaluate("[...document.querySelectorAll('main h2')].map(h => h.id)")
    check(order[:2] == ["h-how", "h-limits"], f"limits come right after how it works: {order}")
    check(pg.locator("#h-limits ~ #h-differ, section:has(#h-limits) #h-differ").count() == 1, "why the numbers differ sits in the limits section")
    if missing:
        check(pg.locator("#limit-units strong").inner_text().startswith(f"{missing:,} project"), "live count of projects with no units")
    stages = next(g for g in GLOSS["groups"] if g["id"] == "stages")["terms"]
    pg.wait_for_function("document.querySelectorAll('#stage-list dt').length > 0")
    dts = pg.locator("#stage-list dt")
    check(dts.count() == len(stages), "every stage listed")
    check(pg.locator("#stage-list dd").first.inner_text() == stages[0]["definition"].replace("'", "’") or
          pg.locator("#stage-list dd").first.inner_text() == stages[0]["definition"], "stage text comes from glossary.json")
    dot = pg.evaluate("getComputedStyle(document.querySelector('#stage-list dt i')).backgroundColor")
    check(dot not in ("rgba(0, 0, 0, 0)", "transparent"), f"stage dots are colored ({dot})")
    check(pg.locator('a[href="glossary.html"]').count() >= 2, "About points to the Glossary")
    check(pg.locator("#chart-type, #glossary, #download").count() == 0, "no charts, glossary or download left on About")
    pg.screenshot(path=os.path.join(SHOTS, "about.png"), full_page=True)

    # ---- Glossary -------------------------------------------------------------
    pg.goto(f"{SITE}/glossary.html")
    pg.wait_for_selector("#glossary dt")
    total = sum(len(g["terms"]) for g in GLOSS["groups"])
    check(pg.locator("#glossary dt").count() == total, "every term")
    check(pg.locator("#glossary-jumps a").count() == len(GLOSS["groups"]), "a jump link per group")
    check(pg.locator("#glossary h2.section__hed").count() == len(GLOSS["groups"]), "a heading per group")
    pg.click('#glossary-jumps a[href="#status"]')
    pg.wait_for_function("location.hash === '#status'")
    check(pg.evaluate("document.getElementById('status').getBoundingClientRect().top") < 120, "jump link scrolls to its group")
    pg.goto(f"{SITE}/glossary.html#g-sepa")
    pg.wait_for_selector("#g-sepa.is-target")
    check(pg.evaluate("document.getElementById('g-sepa').getBoundingClientRect().top") < 300, "a term link scrolls to the term")
    pg.screenshot(path=os.path.join(SHOTS, "glossary.png"), full_page=True)

    # ---- old links into the combined page ---------------------------------------
    for old, new in [("about.html#g-finaled", "glossary.html#g-finaled"), ("about.html#h-glossary", "glossary.html"),
                     ("about.html#h-charts", "stats.html#h-charts"), ("about.html#h-data", "stats.html#h-data"),
                     ("about.html#stats", "stats.html#stats")]:
        pg.goto(f"{SITE}/{old}")
        pg.wait_for_url(f"{SITE}/{new}")
        check(pg.url == f"{SITE}/{new}", f"{old} → {new}")
    for stay in ["about.html#h-limits", "about.html#h-how", "about.html#h-differ", "about.html"]:
        pg.goto(f"{SITE}/{stay}")
        pg.wait_for_timeout(150)
        check(pg.url == f"{SITE}/{stay}", f"{stay} stays on About")
    check(not errors, errors)

    # ---- the map links to all three ---------------------------------------------
    pg.goto(f"{SITE}/index.html")
    hrefs = pg.evaluate("[...document.querySelectorAll('.masthead__nav a')].map(a => a.getAttribute('href'))")
    check(hrefs == ["stats.html", "about.html", "glossary.html"], f"map nav {hrefs}")

    # ---- phones and tablets: nothing runs off the side ------------------------
    for w in (320, 390, 700, 1024):
        m = b.new_page(viewport={"width": w, "height": 800})
        wire(m, site)
        for f in ["index.html", *PAGES]:
            m.goto(f"{SITE}/{f}")
            m.wait_for_timeout(300)
            check(not m.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"), f"{f} fits at {w}px")
            nav = ".masthead__nav" if f == "index.html" else ".pagenav"
            boxes = m.evaluate(f"[...document.querySelectorAll('{nav} a')].map(a => a.getBoundingClientRect()).map(r => [r.left, r.right, r.top])")
            check(all(0 <= l and r <= w for l, r, _ in boxes), f"{f} nav on screen at {w}px {boxes}")
            if f == "index.html":
                title = m.evaluate("document.querySelector('.masthead h1').getBoundingClientRect().right")
                navl = min(l for l, _, t in boxes)
                navtop = min(t for _, _, t in boxes)
                h1b = m.evaluate("document.querySelector('.masthead h1').getBoundingClientRect().bottom")
                check(navl >= title or navtop >= h1b - 2, f"map nav doesn't overlap the title at {w}px")
        m.screenshot(path=os.path.join(SHOTS, f"info-nav-{w}.png"))
        m.close()
    b.close()
print(f"{ok} checks passed")
