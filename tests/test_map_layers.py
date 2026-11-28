"""Map layers (issue #5, PR 2): the Layers panel (the filters' checklist
parts), one shaded layer at a time, any number of outlines, the address bar,
the map key, the hover card, satellite view, phones, and saved map images
with a layer legend. Uses the real files in layers/."""
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, SHOTS, REPO
from playwright.sync_api import sync_playwright
from PIL import Image
sys.path.insert(0, REPO)
import branding

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

os.makedirs(SHOTS, exist_ok=True)
site, data = make_site()
ready = "typeof map !== 'undefined' && map && map.loaded() && state.list && layerMeta && !document.getElementById('layers').hidden"
vis = "(id) => map.getLayer(id) ? map.getLayoutProperty(id, 'visibility') : 'missing'"
C = branding.COLORS

def near(px, hexcolor, tol=30):
    rgb = tuple(int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return sum(abs(a - b) for a, b in zip(px[:3], rgb)) < tol

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    pg = ctx.new_page(); errors = []; console = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and console.append(m.text))
    wire(pg, site)
    pg.goto(SITE + "/"); pg.wait_for_function(ready)

    # Everything off at load: no layer drawn, no layer files fetched, plain key.
    check(pg.evaluate("state.shade === null && state.lines.size === 0"), "layers start off")
    check(pg.evaluate("Object.keys(layerFiles).length") == 0, "no layer file fetched before one is turned on")
    check(pg.locator("#mapkey .mapkey__layer, #mapkey .mapkey__lines").count() == 0, "key has no layer legend")
    check(pg.locator("#layers-count").is_hidden(), "no count on the button")

    # The panel: the filter checklist's parts, radio rows for shading, grouped checkboxes for outlines.
    pg.locator("#layers summary").click()
    panel = pg.locator("#layers-panel")
    pg.wait_for_selector('#layers-panel input[name="shade"]')
    check(panel.is_visible(), "panel opens")
    check(panel.locator('input[name="shade"]').count() == 12, f"Nothing + 11 shaded layers ({panel.locator('input[name=shade]').count()})")
    check(panel.locator("input[data-line]").count() == 6, "six outline layers")
    check(panel.locator("input[data-line-group]").count() == 2, "two outline groups with group boxes")
    check(panel.locator(".picker__group").count() >= 6 and panel.locator(".picker__item").count() >= 20, "built from picker parts")
    check(panel.locator('input[name="shade"][value=""]').is_checked(), "'Nothing' ticked")
    pr = panel.bounding_box(); mr = pg.locator("#map").bounding_box()
    check(pr["y"] + pr["height"] <= mr["y"] + mr["height"] + 1, "panel stays inside the map")
    pg.screenshot(path=f"{SHOTS}/layers-panel.png")

    # One shaded layer: rent burden.
    panel.locator('input[name="shade"][value="rent-burden"]').check()
    pg.wait_for_function(f"({vis})('lyr-tracts-fill') === 'visible'")
    check("layer=rent-burden" in pg.url, pg.url)
    check(pg.evaluate("JSON.stringify(map.getPaintProperty('lyr-tracts-fill', 'fill-color'))").startswith('["match",["get","c_rentBurden"]'), "tracts colored by rent burden")
    check(pg.evaluate("JSON.stringify(map.getFilter('lyr-tracts-hatch'))") == '["==",["get","lr_rentBurden"],1]', "hatch follows the measure")
    check(pg.locator("#layers-count").inner_text() == "1", "button counts 1")
    check(pg.locator("#mapkey .ramp span").count() == 5 and pg.locator("#mapkey .ramp__ticks span").count() == 4, "key: 5-step ramp, 4 ticks")
    check("Renters paying 30%+" in pg.locator("#mapkey").inner_text() and "Census Bureau" in pg.locator("#mapkey .source").inner_text(), "key title and Census credit")
    # Classes: every tract has one, and they spread across all five.
    classes = pg.evaluate("layerFiles.tracts.then(d => d.features.map(f => f.properties.c_rentBurden))")
    check(len(classes) >= 50 and set(classes) >= {0, 1, 2, 3, 4}, f"five classes used {sorted(set(classes))}")
    # Switching measure replaces it (one at a time).
    panel.locator('input[name="shade"][value="zoning"]').check()
    pg.wait_for_function(f"({vis})('lyr-zoning-fill') === 'visible' && ({vis})('lyr-tracts-fill') === 'none'")
    check(pg.locator("#mapkey .mapkey__cats li").count() == 5, "zoning key: five families")
    panel.locator('input[name="shade"][value="growth"]').check()
    pg.wait_for_function(f"({vis})('lyr-tracts-fill') === 'visible' && ({vis})('lyr-zoning-fill') === 'none'")
    check("+25%" in pg.locator("#mapkey .ramp__ticks").inner_text(), "population change uses its fixed classes")

    # Outlines: any number, grouped like the building-type filter.
    panel.locator('input[data-line="historic"]').check()
    panel.locator('input[data-line="oz"]').check()
    pg.wait_for_function(f"({vis})('lyr-historic-districts-line') === 'visible' && ({vis})('lyr-oz2-line') === 'visible'")
    check("lines=historic,oz" in pg.url, pg.url)
    grp = panel.locator('input[data-line-group="Designated areas"]')
    check(grp.evaluate("e => e.indeterminate") and not grp.is_checked(), "group box half-ticked")
    check(pg.locator("#mapkey .mapkey__lines li").count() == 2 and pg.locator("#layers-count").inner_text() == "3", "two outlines in the key; 3 on")
    n_oz = pg.evaluate("state.onMap.filter(p => p.oz2 === true).length")
    tagged = pg.evaluate("state.projects.some(p => p.oz2 !== undefined)")
    check(panel.locator('[data-layer-n="oz"]').inner_text() == (str(n_oz) if tagged else ""), "Opportunity Zone count: tagged projects, blank before the build tags them")
    check(panel.locator('[data-layer-n="mfte"]').inner_text() == "", "no count for MFTE (it covers the whole city)")
    grp.check()
    pg.wait_for_function(f"({vis})('lyr-mfte-line') === 'visible' && ({vis})('lyr-qct-line') === 'visible'")
    check(grp.is_checked() and pg.evaluate("state.lines.size") == 4, "group box turns on the whole group")
    pg.screenshot(path=f"{SHOTS}/layers-on.png")

    # The hover card says what's under the pointer, in words.
    words = pg.evaluate("""() => {
      const s = activeShade();
      const tract = { source: 'lyr-tracts', properties: { name: 'Census tract 35', popChange: 0.123, c_popChange: 3, lr_popChange: 1 } };
      const hd = { source: 'lyr-historic-districts', properties: { name: "Browne's Addition" } };
      const mf = { source: 'lyr-mfte', properties: { name: 'Spokane Targeted Investment Area', terms: '8, 12 or 20 years', area: 'STIA' } };
      return areaLines([tract, hd, mf, hd]).join(' | ');
    }""")
    check("Census tract 35" in words and "+12%" in words and "less reliable" in words, words)
    check("Browne&#39;s Addition</b> Local Historic District" in words and words.count("Browne") == 1 and "8, 12 or 20 years" in words, words)

    # Filters still work with layers on, and Clear filters leaves the layers alone.
    before = pg.evaluate("state.list.length")
    pg.locator("#status-chips button").first.click()
    pg.wait_for_function(f"state.list.length !== {before}")
    pg.locator("#clear-filters").click()
    pg.wait_for_function(f"state.list.length === {before}")
    check(pg.evaluate("state.shade") == "growth" and pg.evaluate("state.lines.size") == 4, "clearing filters keeps layers")

    # Satellite: shading lightens; the switch back restores it.
    pg.keyboard.press("Escape")
    pg.locator('.basemap [data-basemap="satellite"]').click()
    check(pg.evaluate("map.getPaintProperty('lyr-tracts-fill', 'fill-opacity')") == 0.5, "lighter over satellite")

    # Saved image: still works, with a taller band holding the layer legend.
    pg.locator("#save-map").click()
    with pg.expect_download(timeout=30000) as dl:
        pg.locator('.menu [data-item="landscape"]').click()
    img = Image.open(dl.value.path()).convert("RGB"); img.save(f"{SHOTS}/layers-export.jpg")
    check(img.size == (1200, 630), img.size)
    band = img.crop((0, int(630 - pg.evaluate("exportBand().bottom") * 1.2), 1200, 630))
    px = list(band.getdata())
    check(any(near(p, C["line-oz"], 40) for p in px) and any(near(p, C["layer-loss"], 25) for p in px), "legend swatches drawn in the band")
    check(pg.evaluate("exportBand().bottom") > 78, "band grows for the legend")
    check(pg.evaluate("map.getLayoutProperty('satellite', 'visibility')") == "visible", "visible map still satellite")
    check(pg.locator(".maplibregl-map").count() == 1, "hidden copy removed")
    pg.locator('.basemap [data-basemap="map"]').click()
    check(pg.evaluate("map.getPaintProperty('lyr-tracts-fill', 'fill-opacity')") == 0.62, "back to plain opacity")

    # Turn all off.
    pg.locator("#layers summary").click()
    panel.locator("[data-layers-clear]").click()
    pg.wait_for_function(f"({vis})('lyr-tracts-fill') === 'none' && ({vis})('lyr-oz2-line') === 'none'")
    check("layer=" not in pg.url and "lines=" not in pg.url and pg.locator("#layers-count").is_hidden(), "all off, address clean")
    check(pg.locator("#mapkey .mapkey__layer, #mapkey .mapkey__lines").count() == 0, "key back to plain")
    # Keyboard: Escape closes and returns focus to the button.
    panel.locator('input[name="shade"][value="redlining"]').focus()
    pg.keyboard.press("Escape")
    check(not pg.evaluate("document.getElementById('layers').open") and pg.evaluate("document.activeElement.matches('#layers summary')"), "Escape closes, focus back")

    # A shared link opens with its layers on.
    pg.goto(SITE + "/?layer=redlining&lines=transit,centers,nonsense"); pg.wait_for_function(ready)
    pg.wait_for_function(f"({vis})('lyr-holc-fill') === 'visible' && ({vis})('lyr-transit-fill') === 'visible' && ({vis})('lyr-centers-line') === 'visible'")
    check(pg.evaluate("[...state.lines].sort().join()") == "centers,transit", "unknown layer keys ignored")
    check(pg.locator("#mapkey .mapkey__cats li").count() == 4 and "Mapping Inequality" in pg.locator("#mapkey .source").inner_text(), "HOLC key and credit")
    check("layer=redlining" in pg.url and "lines=centers,transit" in pg.url, pg.url)
    pg.goto(SITE + "/?layer=bogus"); pg.wait_for_function(ready)
    check(pg.evaluate("state.shade") is None, "bogus layer ignored")

    # No layers folder (a fresh copy, or a failed fetch): no button, nothing breaks.
    pg.route(f"{SITE}/layers/meta.json", lambda r: r.fulfill(status=404, body="nope"))
    pg.goto(SITE + "/?layer=zoning"); pg.wait_for_function("map && map.loaded() && state.list")
    pg.wait_for_timeout(300)
    check(pg.locator("#layers").is_hidden() and pg.evaluate("!map.getLayer('lyr-zoning-fill')"), "no meta, no Layers button")
    pg.unroute(f"{SITE}/layers/meta.json")

    check(not errors, errors)
    bad = [c for c in console if "hatch" in c or "lyr-" in c or "layer" in c.lower()]
    check(not bad, bad)

    # Phones: the button fits beside the map's controls, the panel fits the screen.
    m = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    m.on("pageerror", lambda e: errors.append(str(e)))
    wire(m, site); m.goto(SITE + "/"); m.wait_for_function(ready)
    btn = m.locator("#layers summary").bounding_box()
    zoom = m.locator(".maplibregl-ctrl-top-right").bounding_box()
    check(btn["x"] + btn["width"] <= zoom["x"] - 4, f"Layers button clear of the zoom buttons {btn} {zoom}")
    tools = m.locator(".maptools").bounding_box()
    check(tools["x"] + tools["width"] <= zoom["x"] - 4, f"map tools clear of the zoom buttons {tools} {zoom}")
    # The smallest phones keep the icon and count; the name stays for screen readers.
    s = b.new_page(viewport={"width": 360, "height": 740}, is_mobile=True, has_touch=True, device_scale_factor=2)
    wire(s, site); s.goto(SITE + "/"); s.wait_for_function(ready)
    t2 = s.locator(".maptools").bounding_box(); z2 = s.locator(".maplibregl-ctrl-top-right").bounding_box()
    check(t2["x"] + t2["width"] <= z2["x"] - 4, f"360px: tools clear of zoom {t2} {z2}")
    check(s.evaluate("document.getElementById('layers').querySelector('summary').getAttribute('aria-label')") == "Layers", "name kept for screen readers")
    s.close()
    m.locator("#layers summary").tap()
    m.wait_for_selector('#layers-panel input[name="shade"]')
    m.locator('#layers-panel input[name="shade"][value="income"]').tap()
    m.wait_for_function(f"({vis})('lyr-tracts-fill') === 'visible'")
    r = m.locator("#layers-panel").bounding_box()
    check(r["x"] >= 0 and r["x"] + r["width"] <= 390, f"panel fits the phone {r}")
    check(m.evaluate("document.documentElement.scrollWidth") <= 390, "no sideways scroll")
    m.screenshot(path=f"{SHOTS}/layers-phone.png")
    mb = m.locator("#map").bounding_box()
    m.locator("#map").tap(position={"x": mb["width"] - 15, "y": mb["height"] - 70})   # outside the panel: closes it
    m.wait_for_timeout(300)
    check(not m.evaluate("document.getElementById('layers').open"), "tap outside closes the panel")
    m.screenshot(path=f"{SHOTS}/layers-phone-key.png")
    check(not errors, errors)
    b.close()

print(f"{ok} checks passed")
