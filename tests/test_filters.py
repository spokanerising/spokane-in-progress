import json, os, re, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, SHOTS, miles
from playwright.sync_api import sync_playwright

OUT = SHOTS; os.makedirs(OUT, exist_ok=True)
site, data = make_site()
P = data["projects"]; N = len(P)
ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

def tally(page): return page.locator("#tally").inner_text()
def count(page): return page.evaluate("state.list.length")
def params(page): return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(page.url).query))

def fresh(ctx, query="", errors=None):
    page = ctx.new_page()
    wire(page, site)
    if errors is not None:
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"{SITE}/{query}")
    page.wait_for_function("typeof map !== 'undefined' && map && map.loaded() && map.getSource('projects') && state.list")
    return page

def open_picker(page, pid):
    page.locator(f'.picker[data-picker="{pid}"] summary').click()
    page.wait_for_selector(f'.picker[data-picker="{pid}"][open] .picker__panel .picker__item, .picker[data-picker="{pid}"][open] .near')

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, geolocation={"latitude": 47.6588, "longitude": -117.426}, permissions=["geolocation"])
    errors = []
    page = fresh(ctx, errors=errors)
    check(count(page) == N, f"all {N} projects at start: {count(page)}")
    ids = page.eval_on_selector_all(".picker", "els => els.map(e => e.dataset.picker)")
    check(ids == ["type", "size", "time", "place", "near", "transit", "zone", "density"], ids)
    check(page.locator("#pills").is_hidden(), "no pills at start")
    page.screenshot(path=f"{OUT}/01-start.png")

    # --- size checklist: untick two buckets
    open_picker(page, "size")
    page.screenshot(path=f"{OUT}/02-size-open.png")
    page.locator('input[data-f="size"][data-o="2-4"]').uncheck()
    page.locator('input[data-f="size"][data-o="unknown"]').uncheck()
    expect = sum(1 for p in P if p.get("units") and p["units"] >= 5)
    check(count(page) == expect, f"size filter {count(page)} vs {expect}")
    check(params(page).get("size") == "5-19,20-99,100", params(page))
    check(page.locator('.picker[data-picker="size"] .picker__summary').inner_text() == "3 sizes", page.locator('.picker[data-picker="size"] .picker__summary').inner_text())
    check(page.locator(".pill").count() == 1 and "Project size" in page.locator(".pill").inner_text(), "size pill")
    check(page.evaluate("document.activeElement.matches('input[data-o=\"unknown\"]')"), "focus stays on the checkbox")

    # --- faceted counts: type counts now exclude the small/unknown projects
    open_picker(page, "type")
    n_apts = int(page.locator('[data-n="type:apartments"]').inner_text())
    exp_apts = sum(1 for p in P if p.get("buildingType") == "Apartments" and p.get("units") and p["units"] >= 5)
    check(n_apts == exp_apts, f"faceted count apartments {n_apts} vs {exp_apts}")
    n_duplex = int(page.locator('[data-n="type:duplex"]').inner_text())
    exp_d = sum(1 for p in P if p.get("buildingType") == "Duplex" and p.get("units") and p["units"] >= 5)
    check(n_duplex == exp_d, f"duplex count {n_duplex} vs {exp_d}")
    zeros = page.eval_on_selector_all('.picker[data-picker="type"] .picker__item.is-zero [data-n]', "els => els.map(e => +e.textContent)")
    check(zeros and all(z == 0 for z in zeros), f"zero rows grayed: {zeros}")
    # Only middle housing quick button
    page.get_by_role("button", name="Only middle housing").click()
    check(params(page).get("type") == "middle", params(page))
    check(page.locator('.picker[data-picker="type"] .picker__summary').inner_text() == "Middle housing", "type summary")
    page.keyboard.press("Escape")
    check(not page.locator('.picker[data-picker="type"]').evaluate("e => e.open"), "escape closes")

    # pill x removes one filter
    page.locator('.pill', has_text="Project size").click()
    check("size" not in params(page) and params(page).get("type") == "middle", params(page))
    page.locator('.pill', has_text="Building type").click()
    check(count(page) == N and page.locator("#pills").is_hidden(), "pills removed everything")

    # --- Where: only one neighborhood
    open_picker(page, "place")
    page.locator('.picker__search[data-search="hood"]').fill("rivers")
    visible = page.locator('.picker__part[data-part="hood"] .picker__item:not(.picker__item--head):visible').count()
    check(visible == 1, f"type-to-find shows 1 ({visible})")
    page.locator('.picker__part[data-part="hood"] .picker__item:not(.picker__item--head):visible').hover()
    page.locator('.picker__part[data-part="hood"] .picker__item:not(.picker__item--head):visible .only').click()
    exp = sum(1 for p in P if p.get("neighborhoodCouncil") == "Riverside")
    check(count(page) == exp and params(page).get("hood") == "riverside", (count(page), exp, params(page)))
    page.wait_for_timeout(900)
    nareas = page.evaluate("map.querySourceFeatures('areas').length")
    check(nareas >= 1, f"outline drawn {nareas}")
    z = page.evaluate("map.getZoom()")
    check(z > 13, f"map fitted to Riverside (zoom {z:.1f})")
    page.screenshot(path=f"{OUT}/03-riverside.png")
    # district part head: untick all districts → 0
    page.locator('.picker__part[data-part="district"] input[data-all]').uncheck()
    check(count(page) == 0 and params(page).get("district") == "none", params(page))
    check(page.locator("#empty").is_visible(), "empty message")
    page.locator('.picker__part[data-part="district"] input[data-all]').check()
    page.keyboard.press("Escape")

    # --- Timeline buckets don't overlap: ticking each one alone adds up to the total
    page.locator("#clear-filters").click()
    open_picker(page, "time")
    filed = page.eval_on_selector_all('[data-n^="filed:"]', "els => els.map(e => +e.textContent)")
    check(sum(filed) == N, f"filed buckets sum {sum(filed)} == {N}")
    since = page.eval_on_selector_all('[data-n^="since:"]', "els => els.map(e => +e.textContent)")
    check(sum(since) == N, f"since buckets sum {sum(since)} == {N}")
    page.locator('.picker__part[data-part="filed"] .picker__item:not(.picker__item--head)').first.hover()
    page.locator('.picker__part[data-part="filed"] .picker__item:not(.picker__item--head)').first.locator(".only").click()
    check(count(page) == filed[0] and params(page).get("filed") == "30", (count(page), filed[0]))
    s = page.locator('.picker[data-picker="time"] .picker__summary').inner_text()
    check(s.startswith("Filed:"), s)
    page.keyboard.press("Escape")
    page.locator("#clear-filters").click()

    # --- transit / zoning / density
    open_picker(page, "transit")
    page.locator('.picker__item:has(input[data-o="quarter"]) .only').click(force=True)
    exp = sum(1 for p in P if p["transitMiles"] <= 0.25)
    check(count(page) == exp, f"transit {count(page)} vs {exp}")
    page.keyboard.press("Escape")
    open_picker(page, "zone")
    groups = page.eval_on_selector_all('.picker[data-picker="zone"] input[data-group]', "els => els.map(e => e.dataset.group)")
    check(groups[:2] == ["residential", "centers-corridors"], groups)
    page.locator('.picker[data-picker="zone"] input[data-group="residential"]').uncheck()
    exp = sum(1 for p in P if p["transitMiles"] <= 0.25 and p.get("zoneGroup") != "Residential")
    check(count(page) == exp, f"zone group untick {count(page)} vs {exp}")
    check(page.locator('.picker[data-picker="zone"] input[data-group="residential"]').evaluate("e => !e.checked && !e.indeterminate"), "group box unticked")
    page.locator('.picker[data-picker="zone"] input[data-o="rmf"]').check()
    check(page.locator('.picker[data-picker="zone"] input[data-group="residential"]').evaluate("e => e.indeterminate"), "group box half-ticked")
    page.keyboard.press("Escape")
    open_picker(page, "density")
    page.locator('.picker[data-picker="density"] input[data-o="unknown"]').uncheck()
    page.locator('.picker[data-picker="density"] input[data-o="under20"]').uncheck()
    exp = sum(1 for p in P if p["transitMiles"] <= 0.25 and (p.get("zoneGroup") != "Residential" or p.get("zoneBase") == "RMF")
              and p.get("homesPerAcre") is not None and p["homesPerAcre"] >= 20)
    check(count(page) == exp, f"density {count(page)} vs {exp}")
    check(page.locator(".pill").count() == 3, page.locator(".pill").count())
    page.keyboard.press("Escape")
    page.screenshot(path=f"{OUT}/04-site-filters.png")

    # round trip: same URL, new tab
    url = page.url
    page2 = fresh(ctx, "?" + url.split("?", 1)[1])
    check(count(page2) == exp, f"round trip {count(page2)} vs {exp}")
    check(page2.locator(".pill").count() == 3, "round-trip pills")
    page2.close()

    # Clear
    page.locator("#clear-filters").click()
    check(count(page) == N and page.url.endswith("site.test/"), page.url)

    # --- stage chips: counts, double-click = only
    chip_n = page.eval_on_selector_all(".chip .chip__n", "els => els.map(e => +e.textContent)")
    check(sum(chip_n) == N, f"chip counts sum {chip_n}")
    page.locator('.chip[data-key="applied"]').dblclick()
    exp = sum(1 for p in P if p["status"] == "Applied")
    check(count(page) == exp and params(page).get("stage") == "applied", (count(page), params(page)))
    page.locator('.chipwrap:has(.chip[data-key="applied"])').hover()
    page.locator('.only[data-only="applied"]').click()
    check(count(page) == N, "only again restores all stages")

    # --- Near: address
    open_picker(page, "near")
    page.locator("#near-address").fill("10 N Post St")
    page.locator(".near__find").click()
    page.wait_for_function("state.near !== null")
    center = (47.6576, -117.4233)
    exp = sum(1 for p in P if miles(center, (p["lat"], p["lng"])) <= 0.5)
    check(count(page) == exp, f"near ½ mile {count(page)} vs {exp}")
    check(params(page).get("near") == "47.65760,-117.42330,0.5" and params(page).get("nearlabel") == "10 N Post St", params(page))
    check("Within ½ mile of 10 N Post St" in page.locator('.picker[data-picker="near"] .picker__summary').inner_text(), "near summary")
    page.locator('.seg label:has(input[value="1"])').click()
    exp1 = sum(1 for p in P if miles(center, (p["lat"], p["lng"])) <= 1)
    check(count(page) == exp1 and params(page)["near"].endswith(",1"), f"near 1 mile {count(page)} vs {exp1}")
    page.wait_for_timeout(700)
    check(page.evaluate("map.querySourceFeatures('near').length") >= 1, "circle drawn")
    page.screenshot(path=f"{OUT}/05-near.png")
    # not found
    page.locator("#near-address").fill("nowhere at all")
    page.locator(".near__find").click()
    page.wait_for_function("document.querySelector('.near__status').textContent.includes('Couldn')")
    check(params(page).get("nearlabel") == "10 N Post St", "a failed lookup keeps the old point")
    # OSM fallback for an intersection
    page.locator("#near-address").fill("Division & Indiana")
    page.locator(".near__find").click()
    page.wait_for_function("state.near && state.near.label === 'Division & Indiana'")
    check(abs(page.evaluate("state.near.lat") - 47.674) < 1e-6, "osm fallback")
    # my location
    page.get_by_role("button", name="Use my location").click()
    page.wait_for_function("state.near && state.near.label === 'your location'")
    check(True, "geolocation")
    # pick on map
    open_picker(page, "near") if not page.locator('.picker[data-picker="near"]').evaluate("e => e.open") else None
    page.get_by_role("button", name="Pick a spot on the map").click()
    check(page.locator("#pickhint").is_visible(), "pick hint shown")
    box = page.locator("#map").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.6)
    page.wait_for_function("state.near && state.near.label === 'the spot you picked'")
    page.wait_for_timeout(300)
    check(page.locator("#pickhint").is_hidden() and page.evaluate("state.selected") is None, "picked, no project opened")
    # remove via pill
    page.locator(".pill", has_text="Within").click()
    check(page.evaluate("state.near") is None and count(page) == N, "near removed")

    # --- only what's in map view
    page.evaluate("map.jumpTo({center: [-117.4233, 47.6576], zoom: 15})")
    page.wait_for_timeout(400)
    inview_n = page.evaluate("state.projects.filter(p => map.getBounds().contains([p.lng, p.lat])).length")
    page.locator("#inview-only").check()
    check(count(page) == inview_n and inview_n < N, f"in view {count(page)} vs {inview_n}")
    check(page.evaluate("map.querySourceFeatures('projects').length") > 0, "map keeps its dots")
    page.evaluate("map.jumpTo({center: [-117.40, 47.68], zoom: 14})")
    page.wait_for_timeout(500)
    inview2 = page.evaluate("state.projects.filter(p => map.getBounds().contains([p.lng, p.lat])).length")
    check(count(page) == inview2, f"list follows the map {count(page)} vs {inview2}")
    check(page.locator(".pill", has_text="Only what").count() == 1, "in-view pill")
    page.locator(".pill", has_text="Only what").click()
    check(count(page) == N and not page.locator("#inview-only").is_checked(), "in-view off")

    # --- legacy links
    for q, key, want in [("?time=filed:90", "filed", "30,90"), ("?time=stage:365", "since", "30,90,365"),
                         ("?place=district:2", "district", "2"), ("?place=hood:East%20Central", "hood", "east-central"),
                         ("?type=middle", "type", "middle"), ("?size=5-19", "size", "5-19"),
                         ("?stage=applied,approved", "stage", "applied,approved")]:
        pg = fresh(ctx, q)
        got = params(pg).get(key)
        check(got == want, f"legacy {q}: {key}={got}")
        check("time" not in params(pg) and "place" not in params(pg), "old params rewritten")
        pg.close()
    pg = fresh(ctx, "?zone=bogus&near=abc")
    check(count(pg) == N and pg.evaluate("state.near") is None, "junk params ignored")
    pg.close()

    # project click still works, and Back closes it
    page.locator(".card").first.click()
    check(page.evaluate("state.selected") is not None and "p" in params(page), "project opens")
    check(page.locator(".specs--quiet dt", has_text="Zoning").count() == 1, "zoning shown on the project page")
    check(page.locator(".specs--quiet dt", has_text="Frequent transit").count() == 1, "transit shown")
    page.screenshot(path=f"{OUT}/06-detail.png")
    page.go_back()
    check(page.evaluate("state.selected") is None, "back closes")

    real = [e for e in errors if "favicon" not in e]
    check(not real, f"console errors: {real}")

    # --- no facts in the data: those three filters simply don't appear
    from harness import make_site as ms
    site2, _ = ms(with_facts=False)
    pg = ctx.new_page(); wire(pg, site2); pg.goto(f"{SITE}/")
    pg.wait_for_function("typeof map !== 'undefined' && map && state.list")
    ids = pg.eval_on_selector_all(".picker", "els => els.map(e => e.dataset.picker)")
    check(ids == ["type", "size", "time", "place", "near"], ids)
    check(pg.locator('#sort option[value="density"]').count() == 0, "density sort hidden without data")
    pg.close()

    # --- phones
    for w, hgt in [(390, 844), (360, 740)]:
        mctx = b.new_context(viewport={"width": w, "height": hgt}, is_mobile=True, has_touch=True, device_scale_factor=2)
        pg = mctx.new_page(); wire(pg, site); pg.goto(f"{SITE}/?view=list")
        pg.wait_for_function("typeof map !== 'undefined' && map && state.list")
        pg.locator("#more-filters").click()
        for pid in ["type", "place", "near", "density"]:
            pg.locator(f'.picker[data-picker="{pid}"] summary').click()
            pg.wait_for_timeout(100)
            r = pg.locator(f'.picker[data-picker="{pid}"] .picker__panel').bounding_box()
            check(r["x"] >= 0 and r["x"] + r["width"] <= w + 0.5, f"{w}px: {pid} panel inside screen {r}")
            pg.screenshot(path=f"{OUT}/07-phone-{w}-{pid}.png")
            pg.locator(f'.picker[data-picker="{pid}"] summary').click()
        overflow = pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        check(not overflow, f"{w}px: no sideways scroll")
        # tap a checklist "only" (always visible on touch)
        pg.locator('.picker[data-picker="size"] summary').tap()
        pg.locator('.picker[data-picker="size"] .picker__item:has(input[data-o="100"]) .only').tap()
        check(pg.evaluate("state.list.length") == sum(1 for p in P if (p.get('units') or 0) >= 100), "tap only")
        check("1 on" in pg.locator("#more-filters").text_content(), pg.locator("#more-filters").text_content())
        pg.screenshot(path=f"{OUT}/08-phone-{w}-pills.png")
        mctx.close()

    b.close()
print(f"{ok} checks passed")
