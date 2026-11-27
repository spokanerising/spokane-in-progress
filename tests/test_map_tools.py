"""Map tools (polish round, phase D): the scale bar, the "Whole city" button,
skip links, and getting around the map by keyboard ([ ] to step through
projects, Enter to open, 0 for the whole city, Escape back to where you were)."""
import os, shutil, sys
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
site, _ = make_site(with_facts=True)
shutil.copy(os.path.join(REPO, "boundaries.geojson"), site)

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)
    pg.goto(SITE + "/")
    pg.wait_for_selector(".card")
    pg.wait_for_function("typeof map !== \"undefined\" && map && map.getSource(\"projects\")")
    pg.wait_for_selector(".maplibregl-ctrl-scale")

    # Scale bar, in feet or miles.
    scale = pg.locator(".maplibregl-ctrl-scale").inner_text()
    check(scale.endswith(("mi", "ft")), f"imperial scale {scale}")
    box = pg.locator(".maplibregl-ctrl-scale").bounding_box()
    key = pg.locator("#mapkey").bounding_box()
    check(box["x"] > key["x"] + key["width"], "scale bar clear of the map key")

    # Whole city: zoom in somewhere, then back out to the city's edge.
    city = pg.evaluate("""() => fetch('boundaries.geojson').then(r => r.json()).then(g => {
        let w = 180, s = 90, e = -180, n = -90;
        g.features.filter(f => f.properties.kind === 'district').forEach(f => {
          const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
          polys.forEach(p => p[0].forEach(([x, y]) => { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }));
        });
        return [w, s, e, n];
    })""")
    pg.evaluate("map.jumpTo({center: [-117.42, 47.66], zoom: 16})")
    check(pg.locator("#whole-city").get_attribute("aria-label") == "Show the whole city", "whole city button labelled")
    pg.locator("#whole-city").click()
    pg.wait_for_function("!map.isMoving() && map.getZoom() < 14", timeout=5000)
    pg.wait_for_timeout(200)
    bb = pg.evaluate("map.getBounds().toArray().flat()")
    check(bb[0] <= city[0] + 0.002 and bb[1] <= city[1] + 0.002 and bb[2] >= city[2] - 0.002 and bb[3] >= city[3] - 0.002, f"whole city in view {bb} vs {city}")
    check(pg.evaluate("map.getZoom()") > 10, "and not zoomed out past it")

    # Skip links: the first two tab stops.
    def fresh():
        pg.goto(SITE + "/")
        pg.wait_for_selector(".card")
        pg.wait_for_function("typeof map !== 'undefined' && map && map.getSource('projects')")
    fresh()
    pg.keyboard.press("Tab")
    check(pg.evaluate("document.activeElement.id") == "skip-list", "first tab stop: skip to the list")
    sk = pg.locator("#skip-list").bounding_box()
    check(sk["y"] >= 0, "skip link shows when focused")
    pg.keyboard.press("Enter")
    check(pg.evaluate("document.activeElement.classList.contains('card')"), "Enter lands on the first project row")
    fresh()
    pg.keyboard.press("Tab"); pg.keyboard.press("Tab")
    check(pg.evaluate("document.activeElement.id") == "skip-map", "second tab stop: skip to the map")
    pg.keyboard.press("Enter")
    check(pg.evaluate("document.activeElement === map.getCanvas()"), "Enter focuses the map")
    check(pg.evaluate("document.body.dataset.mapkeys") == "on" and pg.locator("#keyhint").is_visible(), "keyboard hint shows")
    ring = pg.evaluate("getComputedStyle(map.getCanvas()).outlineStyle")
    check(ring == "solid", f"map shows the focus ring ({ring})")
    pg.screenshot(path=os.path.join(SHOTS, "map-keys.png"))

    # [ and ] step through projects in view, nearest the middle first.
    pg.keyboard.press("]")
    first = pg.locator("#map-live").inner_text()
    check(" of " in first and "in view" in first and "Press Enter" in first, first)
    hovered1 = pg.evaluate("hovered")
    check(hovered1, "the stepped-to project is highlighted")
    check(pg.locator(".tip").count() == 1, "its name shows on the map")
    center_d = pg.evaluate("""(id) => { const p = state.projects.find(x => x.id === id), c = map.project(map.getCenter());
        const d = q => map.project([q.lng, q.lat]).dist(c);
        const b = map.getBounds();
        return [d(p), Math.min(...state.onMap.filter(q => b.contains([q.lng, q.lat])).map(d))]; }""", hovered1)
    check(abs(center_d[0] - center_d[1]) < 0.5, f"starts nearest the middle {center_d}")
    pg.keyboard.press("]")
    hovered2 = pg.evaluate("hovered")
    check(hovered2 and hovered2 != hovered1 and pg.locator("#map-live").inner_text().split(".")[1].strip().startswith("2 of"), "] moves on")
    pg.keyboard.press("[")
    check(pg.evaluate("hovered") == hovered1, "[ moves back")

    # Enter opens it; Escape closes it and returns to the map.
    pg.keyboard.press("Enter")
    pg.wait_for_selector("#detail:not([hidden])")
    check(pg.evaluate("state.selected") == hovered1, "Enter opens the stepped-to project")
    check(pg.evaluate("document.activeElement.id") == "detail-close", "focus moves to the project")
    pg.keyboard.press("Escape")
    check(pg.locator("#detail").is_hidden(), "Escape closes it")
    check(pg.evaluate("document.activeElement === map.getCanvas()"), "and focus goes back to the map")

    # 0: whole city from the keyboard.
    pg.evaluate("map.jumpTo({center: [-117.42, 47.66], zoom: 16})")
    pg.keyboard.press("0")
    pg.wait_for_function("!map.isMoving() && map.getZoom() < 14", timeout=5000)
    check(True, "0 zooms out to the whole city")

    # From a list row: Escape returns focus to that row.
    card = pg.locator(".card").nth(2)
    cid = card.get_attribute("data-id")
    card.focus(); pg.keyboard.press("Enter")
    pg.wait_for_selector("#detail:not([hidden])")
    pg.keyboard.press("Escape")
    check(pg.evaluate("document.activeElement.dataset.id") == cid, "focus back on the row that opened it")
    # The × does the same.
    pg.locator(".card").nth(3).click()
    pg.wait_for_selector("#detail:not([hidden])")
    cid3 = pg.locator(".card").nth(3).get_attribute("data-id")
    pg.locator("#detail-close").click()
    check(pg.evaluate("document.activeElement.dataset.id") == cid3, "× returns focus to the row too")

    # Escape inside an open menu closes the menu, not the project.
    pg.locator(".card").first.click()
    pg.wait_for_selector("[data-share-project]")
    pg.locator("[data-share-project]").click()
    pg.keyboard.press("Escape")
    check(pg.locator(".menu").count() == 0 and pg.locator("#detail").is_visible(), "Escape in a menu leaves the project open")

    # Leaving the map hides the hint.
    pg.evaluate("map.getCanvas().blur()")
    check(not pg.locator("#keyhint").is_visible(), "hint hides when the map loses focus")

    check(not errors, f"page errors: {errors}")
    b.close()

print(f"{ok} checks passed")
