"""Phase 1 of the sharing plan: the Download menu (CSV and GeoJSON of what
the list shows) and the Share menu for a view and for a project, on desktop
(menu) and on phones (the phone's own share sheet)."""
import csv, io, json, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, SHOTS
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

os.makedirs(SHOTS, exist_ok=True)
site, data = make_site()
P = data["projects"]; N = len(P)
q = lambda href: dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(href).query))
ready = "typeof map !== 'undefined' && map && map.loaded() && state.list"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True,
                        permissions=["clipboard-read", "clipboard-write"])
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    wire(pg, site); pg.goto(f"{SITE}/?size=100"); pg.wait_for_function(ready)
    big = [p for p in P if (p.get("units") or 0) >= 100]
    check(pg.evaluate("state.list.length") == len(big), "filtered to 100+ homes")

    # ---- Download menu
    pg.locator("#download-list").click()
    check(pg.locator(".menu").is_visible() and pg.locator("#download-list").get_attribute("aria-expanded") == "true", "menu opens")
    check(pg.evaluate("document.activeElement.dataset.item") == "csv", "focus on the first item")
    check(f"these {len(big)} projects" in pg.locator('.menu [data-item="csv"]').inner_text(), pg.locator('.menu [data-item="csv"]').inner_text())
    pg.screenshot(path=f"{SHOTS}/p1-download-menu.png")
    with pg.expect_download() as dl:
        pg.keyboard.press("Enter")
    name = dl.value.suggested_filename
    check(name.startswith("spokane-in-progress-") and name.endswith("-filtered.csv"), name)
    rows = list(csv.DictReader(io.StringIO(open(dl.value.path(), encoding="utf-8-sig").read())))
    check(len(rows) == len(big), f"{len(rows)} rows for {len(big)} projects")
    check({r["id"] for r in rows} == {p["id"] for p in big}, "the right projects")
    check(all(r["link"].endswith(f"/p/{urllib.parse.quote(r['id'])}/") for r in rows), "link column is the project's page")
    check(pg.locator(".menu").count() == 0, "menu closes after choosing")
    check(pg.evaluate("document.activeElement.id") == "download-list", "focus returns to the button")

    pg.locator("#download-list").click()
    with pg.expect_download() as dl:
        pg.locator('.menu [data-item="geojson"]').click()
    check(dl.value.suggested_filename.endswith("-filtered.geojson"), dl.value.suggested_filename)
    gj = json.load(open(dl.value.path(), encoding="utf-8"))
    check(gj["type"] == "FeatureCollection" and len(gj["features"]) == len(big), "geojson features")
    f0 = gj["features"][0]
    src = next(p for p in big if p["id"] == f0["properties"]["id"])
    check(abs(f0["geometry"]["coordinates"][0] - src["lng"]) < 1e-5 and abs(f0["geometry"]["coordinates"][1] - src["lat"]) < 1e-5, "coordinates are lng, lat")
    check("lat" not in f0["properties"] and f0["properties"]["units"] == src["units"], "properties")
    check(gj["filters"] == "100 or more homes" and "size=100" in gj["view"] and gj["dataAsOf"], (gj["filters"], gj["view"]))

    # Unfiltered: "all", no -filtered suffix. Only-in-view: follows the map.
    pg.goto(f"{SITE}/"); pg.wait_for_function(ready)
    pg.locator("#download-list").click()
    check(f"all {N} projects" in pg.locator('.menu [data-item="csv"]').inner_text(), "all projects label")
    with pg.expect_download() as dl:
        pg.locator('.menu [data-item="csv"]').click()
    check(not dl.value.suggested_filename.endswith("-filtered.csv"), dl.value.suggested_filename)
    check(len(list(csv.reader(open(dl.value.path(), encoding="utf-8-sig")))) == N + 1, "all rows")
    pg.evaluate("map.jumpTo({center: [-117.4233, 47.6576], zoom: 15})"); pg.wait_for_timeout(300)
    pg.locator("#inview-only").check()
    n_view = pg.evaluate("state.list.length")
    pg.locator("#download-list").click()
    with pg.expect_download() as dl:
        pg.locator('.menu [data-item="csv"]').click()
    check(len(list(csv.reader(open(dl.value.path(), encoding="utf-8-sig")))) == n_view + 1, f"in-view download {n_view}")
    pg.locator("#inview-only").uncheck()

    # ---- Share menu (desktop)
    pg.goto(f"{SITE}/?hood=riverside&size=20-99,100"); pg.wait_for_function(ready)
    pg.locator("#share-view").click()
    items = pg.eval_on_selector_all(".menu .menu__item", "els => els.map(e => e.dataset.item)")
    check(items[:6] == ["copy", "bluesky", "reddit", "linkedin", "x", "email"], items)
    check(pg.locator(".menu .menu__rule").count() >= 1, "divider after Copy link")
    href = {i: pg.locator(f'.menu [data-item="{i}"]').get_attribute("href") for i in ["bluesky", "reddit", "linkedin", "x", "email"]}
    view = pg.url
    bt = q(href["bluesky"])["text"]
    check(bt.endswith(view) and "Riverside" in bt and "projects" in bt, bt)
    check(q(href["reddit"])["url"] == view and q(href["linkedin"])["url"] == view and q(href["x"])["url"] == view, "network links carry this view")
    check(pg.locator('.menu [data-item="bluesky"]').get_attribute("target") == "_blank", "networks open in a new tab")
    check(pg.locator('.menu [data-item="email"]').get_attribute("target") is None, "email doesn't")
    pg.screenshot(path=f"{SHOTS}/p1-share-menu.png")
    # keyboard
    pg.keyboard.press("ArrowDown"); check(pg.evaluate("document.activeElement.dataset.item") == "bluesky", "arrow down")
    pg.keyboard.press("End"); check(pg.evaluate("document.activeElement.dataset.item") in ("email", "more"), "end")
    pg.keyboard.press("ArrowDown"); check(pg.evaluate("document.activeElement.dataset.item") == "copy", "wraps to top")
    pg.keyboard.press("Escape")
    check(pg.locator(".menu").count() == 0 and pg.evaluate("document.activeElement.id") == "share-view", "escape closes, focus back")
    # click outside, and a second click on the button, both close
    pg.locator("#share-view").click(); pg.mouse.click(700, 500)
    check(pg.locator(".menu").count() == 0, "click outside closes")
    pg.locator("#share-view").click(); pg.locator("#share-view").click()
    check(pg.locator(".menu").count() == 0, "second click closes")
    # one menu at a time
    pg.locator("#share-view").click(); pg.locator("#download-list").click()
    check(pg.locator(".menu").count() == 1 and pg.locator("#share-view").get_attribute("aria-expanded") == "false", "one menu at a time")
    pg.keyboard.press("Escape")
    # menu stays on screen
    pg.locator("#share-view").click()
    box = pg.locator(".menu").bounding_box()
    check(box["x"] >= 0 and box["x"] + box["width"] <= 1440 and box["y"] + box["height"] <= 900, f"menu on screen {box}")
    pg.keyboard.press("Escape")

    # ---- Share a project
    peyton = next((p for p in P if p.get("units") and p.get("neighborhood")), P[0])
    pg.goto(f"{SITE}/?p={urllib.parse.quote(peyton['id'])}"); pg.wait_for_function(ready)
    pg.wait_for_selector("[data-share-project]")
    pg.locator("[data-share-project]").click()
    xt = q(pg.locator('.menu [data-item="x"]').get_attribute("href"))
    check(xt["url"].endswith(f"/p/{urllib.parse.quote(peyton['id'])}/"), xt["url"])
    check(xt["text"].startswith(f"{peyton['name']}:") and f"{peyton['units']:,} homes" in xt["text"] and peyton["neighborhood"] in xt["text"] and xt["text"].endswith("Via Spokane in Progress"), xt["text"])
    rt = q(pg.locator('.menu [data-item="reddit"]').get_attribute("href"))
    check(rt["title"].startswith(peyton["name"]), rt["title"])
    pg.locator('.menu [data-item="copy"]').click()
    pg.wait_for_selector("#toast.is-on")
    check(pg.evaluate("navigator.clipboard.readText()") == xt["url"], "copied the project link")
    pg.screenshot(path=f"{SHOTS}/p1-project.png")
    check(not errors, errors)

    # ---- Phones: the phone's share sheet, not the menu
    for w, h in [(390, 844)]:
        m = b.new_context(viewport={"width": w, "height": h}, is_mobile=True, has_touch=True, device_scale_factor=2)
        mp = m.new_page(); merr = []
        mp.on("pageerror", lambda e: merr.append(str(e)))
        mp.add_init_script("""window.__shared = []; navigator.share = async (d) => { window.__shared.push(d); };
                              navigator.canShare = () => true;""")
        wire(mp, site); mp.goto(f"{SITE}/?view=list&size=100"); mp.wait_for_function(ready)
        check(mp.evaluate("matchMedia('(pointer: coarse)').matches"), "touch phone")
        mp.locator("#share-view").tap(); mp.wait_for_function("window.__shared.length === 1")
        sh = mp.evaluate("window.__shared[0]")
        check(sh["url"] == mp.url and "100 or more homes" in sh["text"] and mp.locator(".menu").count() == 0, sh)
        mp.locator(".card").first.tap(); mp.wait_for_selector("[data-share-project]")
        mp.locator("[data-share-project]").tap(); mp.wait_for_function("window.__shared.length === 2")
        check("/p/" in mp.evaluate("window.__shared[1].url"), "project share sheet")
        # The person cancels the sheet: nothing else happens.
        mp.evaluate("() => { navigator.share = async () => { throw new DOMException('cancelled', 'AbortError'); }; }")
        mp.locator("[data-share-project]").tap(); mp.wait_for_timeout(300)
        check(mp.locator(".menu").count() == 0, "cancel shows no menu")
        # No share sheet at all (some Android browsers): the menu, big enough to tap.
        mp.evaluate("() => { navigator.share = undefined; }")
        mp.locator("[data-share-project]").tap()
        mp.wait_for_selector(".menu")
        hts = mp.eval_on_selector_all(".menu .menu__item", "els => els.map(e => e.getBoundingClientRect().height)")
        check(min(hts) >= 44, f"tap targets {hts}")
        mb = mp.locator(".menu").bounding_box()
        check(mb["x"] >= 0 and mb["x"] + mb["width"] <= w, f"menu inside the phone screen {mb}")
        mp.screenshot(path=f"{SHOTS}/p1-phone-menu.png")
        mp.keyboard.press("Escape")
        # Download on the phone
        mp.goto(f"{SITE}/?view=list"); mp.wait_for_function(ready)
        mp.locator("#download-list").tap(); mp.wait_for_selector(".menu")
        mp.screenshot(path=f"{SHOTS}/p1-phone-download.png")
        overflow = mp.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        check(not overflow, "no sideways scroll")
        check(not merr, merr)
        m.close()
    b.close()
print(f"{ok} checks passed")
