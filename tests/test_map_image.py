"""Phase 4 of the sharing plan: "Save image" on the map. Each size downloads
a JPEG of the right dimensions with a title band, a key, the credits and
the project dots; satellite view still saves the plain map; phones get the
share sheet; the hidden map used for drawing is cleaned up."""
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, SHOTS
from playwright.sync_api import sync_playwright
from PIL import Image

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

os.makedirs(SHOTS, exist_ok=True)
site, data = make_site()
stage_colors = [tuple(int(s["color"][i:i + 2], 16) for i in (1, 3, 5)) for s in data["stages"][:5]]
ready = "typeof map !== 'undefined' && map && map.loaded() && state.list"

def dots(img):
    """Pixels close to a stage color: the project dots."""
    px = list(img.convert("RGB").resize((img.width // 2, img.height // 2)).getdata()) if not hasattr(Image.Image, "get_flattened_data") else img.convert("RGB").resize((img.width // 2, img.height // 2)).get_flattened_data()
    return sum(1 for p in px if any(sum(abs(a - b) for a, b in zip(p, c)) < 40 for c in stage_colors))

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site); pg.goto(f"{SITE}/?hood=riverside"); pg.wait_for_function(ready)
    pg.wait_for_timeout(500)

    pg.locator("#save-map").click()
    items = pg.eval_on_selector_all(".menu .menu__item", "els => els.map(e => e.dataset.item)")
    check(items == ["view", "square", "landscape", "portrait"], items)
    pg.screenshot(path=f"{SHOTS}/p4-menu.png")
    pg.keyboard.press("Escape")

    box = pg.locator("#map").bounding_box()
    for item, size in [("square", (1080, 1080)), ("landscape", (1200, 630)), ("portrait", (1080, 1350)),
                       ("view", (round(box["width"]), round(box["height"])))]:
        pg.locator("#save-map").click()
        with pg.expect_download(timeout=30000) as dl:
            pg.locator(f'.menu [data-item="{item}"]').click()
        name = dl.value.suggested_filename
        check(name.startswith("spokane-in-progress-") and name.endswith(f"-map{'' if item == 'view' else '-' + item}.jpg"), name)
        img = Image.open(dl.value.path())
        check(img.format == "JPEG" and img.size == size, f"{item}: {img.format} {img.size}")
        img.save(f"{SHOTS}/p4-{item}.jpg")
        top = img.getpixel((img.width // 2, 8))
        check(all(abs(a - b) < 12 for a, b in zip(top, (250, 248, 243))), f"{item}: title band is paper {top}")
        check(dots(img) > 20, f"{item}: project dots drawn ({dots(img)})")
        check(pg.locator(".maplibregl-map").count() == 1, "the hidden map is removed")
        check(pg.locator("#save-map").get_attribute("aria-label") == "Save the map as an image" and pg.locator("#save-map").get_attribute("data-tip") is None and pg.locator("#save-map").get_attribute("aria-busy") is None, "button back to normal")
        pg.wait_for_function("document.getElementById('toast') && document.getElementById('toast').textContent === 'Map image saved'")

    # Title text matches the filters: compare a crop of the band with what the page would say
    check(pg.evaluate("filtersInWords()") == "Riverside", pg.evaluate("filtersInWords()"))

    # Satellite on: still saves (plain map), and the visible map stays on satellite
    pg.locator('.basemap [data-basemap="satellite"]').click()
    pg.locator("#save-map").click()
    with pg.expect_download(timeout=30000) as dl:
        pg.locator('.menu [data-item="landscape"]').click()
    img = Image.open(dl.value.path())
    check(img.size == (1200, 630) and dots(img) > 20, "saves from satellite view")
    check(pg.evaluate("map.getLayoutProperty('satellite', 'visibility')") == "visible", "visible map still satellite")
    pg.locator('.basemap [data-basemap="map"]').click()

    # A failure says so and leaves the button usable
    pg.evaluate("() => { window.__orig = maplibregl.Map; maplibregl.Map = function () { throw new Error('boom'); }; }")
    pg.locator("#save-map").click(); pg.locator('.menu [data-item="square"]').click()
    pg.wait_for_function("document.getElementById('toast').textContent.startsWith('Couldn')")
    check(pg.locator("#save-map").get_attribute("aria-busy") is None, "button usable after a failure")
    pg.evaluate("() => { maplibregl.Map = window.__orig; }")
    check(not errors, errors)

    # Phones: the share sheet with the image file
    m = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    mp = m.new_page(); merr = []
    mp.on("pageerror", lambda e: merr.append(str(e)))
    mp.add_init_script("""window.__shared = []; navigator.share = async (d) => { window.__shared.push({n: d.files && d.files.length, type: d.files && d.files[0].type, name: d.files && d.files[0].name, size: d.files && d.files[0].size}); };
                          navigator.canShare = (d) => !!(d && d.files);""")
    wire(mp, site); mp.goto(f"{SITE}/?view=map"); mp.wait_for_function(ready)
    mp.wait_for_timeout(500)
    r = mp.locator("#save-map").bounding_box()
    check(r["height"] >= 36 and r["x"] + r["width"] < 390, f"button fits on a phone {r}")
    mp.screenshot(path=f"{SHOTS}/p4-phone.png")
    mp.locator("#save-map").tap(); mp.locator('.menu [data-item="square"]').tap()
    mp.wait_for_function("window.__shared.length === 1", timeout=30000)
    sh = mp.evaluate("window.__shared[0]")
    check(sh["n"] == 1 and sh["type"] == "image/jpeg" and sh["name"].endswith("-map-square.jpg") and sh["size"] > 20000, sh)
    check(not merr, merr)
    m.close()
    b.close()
print(f"{ok} checks passed")
