"""Checks the site against the real projects.json and boundaries.geojson the
daily build produced (no made-up values): every project has a unique id,
each filter's counts add up to the whole map, outlines load, project pages
show their site facts, and nothing logs an error."""
import json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, REPO
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

data = json.load(open(os.path.join(REPO, "projects.json")))
P = data["projects"]; N = len(P)
ids = [p["id"] for p in P]
dupes = sorted({i for i in ids if ids.count(i) > 1})
check(not dupes, f"duplicate project ids: {dupes}")
for p in P:
    if p.get("homesPerAcre") is not None:
        expect = p["units"] / p["acres"] if p.get("acres") else None
        check(expect and abs(p["homesPerAcre"] - expect) <= 0.01 * expect + 0.1,
              f"{p['name']}: homes per acre {p['homesPerAcre']} doesn't match units/acres {expect}")

site, _ = make_site(with_facts=False)
for f in ["projects.json", "boundaries.geojson"]:
    if os.path.exists(os.path.join(REPO, f)):
        shutil.copy(os.path.join(REPO, f), site)

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    wire(pg, site)
    pg.goto(f"{SITE}/")
    pg.wait_for_function("typeof map !== 'undefined' && map && map.loaded() && state.list")
    check(pg.evaluate("state.list.length") == N, "every project listed")

    pickers = pg.eval_on_selector_all(".picker", "els => els.map(e => e.dataset.picker)")
    print("filters on the live data:", pickers)
    parts = {"type": ["type"], "size": ["size"], "time": ["filed", "since"], "place": ["district", "hood"],
             "transit": ["transit"], "zone": ["zone"], "density": ["density"]}
    for pid in pickers:
        if pid not in parts:
            continue
        pg.locator(f'.picker[data-picker="{pid}"] summary').click()
        pg.wait_for_selector(f'.picker[data-picker="{pid}"] .picker__item [data-n]')
        for f in parts[pid]:
            ns = pg.eval_on_selector_all(f'[data-n^="{f}:"]:not([data-n*=":group:"])', "els => els.map(e => +e.textContent)")
            check(sum(ns) == N, f"{f}: counts add to {sum(ns)}, not {N}")
        pg.locator(f'.picker[data-picker="{pid}"] summary').click()

    # A neighborhood outline from the real city shapes.
    hood = next(p["neighborhoodCouncil"] for p in P if p.get("neighborhoodCouncil"))
    pg.evaluate(f"only('hood', slug({json.dumps(hood)})); afterFilterChange('hood')")
    pg.wait_for_timeout(1200)
    check(pg.evaluate("map.querySourceFeatures('areas').length") > 0, f"outline drawn for {hood}")

    # A project page with site facts.
    with_facts = next((p for p in P if p.get("zone") and p.get("transitMiles") is not None), None)
    if with_facts:
        pg.goto(f"{SITE}/?p={with_facts['id']}")
        pg.wait_for_selector(".specs--quiet")
        quiet = pg.locator(".specs--quiet").inner_text()
        check("ZONING" in quiet.upper() and "FREQUENT TRANSIT" in quiet.upper(), "project page shows zoning and transit")
    check(not errors, f"console errors: {errors}")
    b.close()
print(f"{ok} checks passed")
