"""Icon buttons (polish round, phase B): every icon button has a name, draws an
icon that exists, shows its tooltip on hover and keyboard focus, and the
project bar's Copy link and Report a correction do what they say."""
import os, sys
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

SHOTS = os.path.join(os.path.dirname(__file__), ".shots")
AUDIT = """() => [...document.querySelectorAll('.iconbtn')].filter(e => e.getClientRects().length).map(e => {
  const use = e.querySelector('svg.icon use'), id = use && use.getAttribute('href');
  const r = e.getBoundingClientRect();
  return {name: e.getAttribute('aria-label') || '', icon: id, exists: !!(id && document.querySelector(id + ' path, ' + id + ' rect, ' + id + ' circle')),
          text: e.textContent.trim(), w: Math.round(r.width), h: Math.round(r.height)};
})"""

def audit(pg, size, where):
    found = pg.evaluate(AUDIT)
    check(found, f"{where}: icon buttons present")
    for f in found:
        check(f["name"], f"{where}: icon button has a label {f}")
        check(f["exists"], f"{where}: {f['name']} draws an existing icon {f['icon']}")
        check(f["text"] == "", f"{where}: {f['name']} has no visible text")
        check(abs(f["w"] - size) <= 1 and abs(f["h"] - size) <= 1, f"{where}: {f['name']} is {f['w']}x{f['h']}")
    return found

site, _ = make_site(with_facts=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)
    pg.goto(SITE + "/")
    pg.wait_for_selector(".card")

    names = {f["name"] for f in audit(pg, 36, "map page")}
    check({"Download this list", "Share this view", "Save the map as an image"} <= names, names)
    check(pg.locator(".sharebtn").count() == 0, "no text Share/Download buttons left on the map page")

    # Tooltip on hover (after a pause) and gone on leaving.
    pg.hover("#share-view")
    check(not pg.locator(".tip-label.is-on").count(), "no tooltip straight away on hover")
    pg.wait_for_selector(".tip-label.is-on", timeout=2000)
    check(pg.locator(".tip-label").inner_text() == "Share this view", "hover tooltip text")
    tip = pg.locator(".tip-label").bounding_box(); btn = pg.locator("#share-view").bounding_box()
    check(tip["y"] >= btn["y"] + btn["height"] and tip["x"] >= 0 and tip["x"] + tip["width"] <= 1280, f"tooltip under the button, on screen {tip}")
    pg.mouse.move(700, 600)
    pg.wait_for_function("!document.querySelector('.tip-label.is-on')")
    # Clicking hides it and opens the menu.
    pg.hover("#download-list"); pg.wait_for_selector(".tip-label.is-on")
    pg.locator("#download-list").click()
    check(pg.locator(".menu").is_visible() and not pg.locator(".tip-label.is-on").count(), "click: menu open, tooltip gone")
    pg.keyboard.press("Escape")

    # Keyboard focus shows it at once.
    pg.keyboard.press("Tab")
    pg.focus("#share-view")
    pg.wait_for_selector(".tip-label.is-on", timeout=300)
    check(pg.locator(".tip-label").inner_text() == "Share this view", "focus tooltip")
    pg.keyboard.press("Escape")
    check(not pg.locator(".tip-label.is-on").count(), "Escape hides the tooltip")

    # The project bar.
    pg.locator(".card").first.click()
    pg.wait_for_selector("[data-share-project]")
    bar = audit(pg, 36, "project bar")
    check({"Share this project", "Copy link to this project", "Report a correction", "Close project"} <= {f["name"] for f in bar}, bar)
    pid = pg.locator(".card.is-active").get_attribute("data-id")
    pname = pg.locator("#detail-body h2").inner_text()
    pg.locator("[data-copy-project]").click()
    clip = pg.evaluate("navigator.clipboard.readText()")
    check(clip == f"{SITE}/p/{pid}/", f"copied {clip}")
    pg.wait_for_selector("#toast.is-on")
    check(pg.locator("#toast").inner_text() == f"Link to {pname} copied", pg.locator("#toast").inner_text())
    href = pg.locator("[data-correction]").get_attribute("href")
    u = urlparse(href); q = parse_qs(u.query)
    check(u.scheme == "mailto" and u.path == "spokanerising@gmail.com", href)
    check(q["subject"] == [f"Correction: {pname} ({pid})"], q["subject"])
    body = q["body"][0]
    check(f"Page: {SITE}/p/{pid}/" in body and "What's wrong:" in body and "What it should say:" in body and "Data as of:" in body, body)
    # Bar layout: tools on the left, close on the right.
    tools = pg.locator("#detail-tools").bounding_box(); close = pg.locator("#detail-close").bounding_box()
    check(tools["x"] < close["x"], "close is on the right")
    pg.screenshot(path=os.path.join(SHOTS, "icons-desktop.png"))
    pg.locator("#detail-close").click()
    check(pg.locator("#detail").is_hidden(), "close icon closes the project")

    # About page: one download icon per chart.
    pg.goto(SITE + "/stats.html")
    pg.wait_for_selector("#chart-size .chart__tools .iconbtn")
    found = audit(pg, 36, "about page")
    check(sum(f["name"] == "Download this chart" for f in found) == 5, found)
    pg.locator("#chart-size .iconbtn").click()
    items = pg.eval_on_selector_all(".menu .menu__item", "els => els.map(e => e.dataset.item)")
    check(items == ["png", "svg", "csv"], items)
    pg.keyboard.press("Escape")

    # Phones: 40px, and no tooltips (no hover on touch).
    m = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    mp = m.new_page(); mp.on("pageerror", lambda e: errors.append(str(e)))
    wire(mp, site); mp.goto(SITE + "/"); mp.wait_for_selector(".maplibregl-canvas")
    audit(mp, 40, "phone map")
    mp.locator('.viewswitch [data-view="list"]').tap()
    audit(mp, 40, "phone list")
    mp.locator(".card").first.tap(); mp.wait_for_selector("[data-copy-project]")
    audit(mp, 40, "phone project")
    check(not mp.locator(".tip-label.is-on").count(), "no tooltip after tapping on a phone")
    check(mp.evaluate("document.documentElement.scrollWidth") <= 390, "no sideways scroll")
    m.close()

    check(not errors, f"page errors: {errors}")
    b.close()

print(f"{ok} checks passed")
