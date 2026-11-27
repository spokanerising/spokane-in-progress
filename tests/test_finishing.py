"""Finishing touches (polish round, phase C): the site icons and manifest,
grey placeholder rows while the list loads, the 404 page, the no-JavaScript
note, and printing a project page."""
import json, os, sys
from PIL import Image
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

# The icon files.
ico = Image.open(os.path.join(REPO, "favicon.ico"))
check(ico.info.get("sizes") == {(16, 16), (32, 32), (48, 48)}, f"favicon.ico sizes {ico.info.get('sizes')}")
for name, px in [("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512), ("icon-maskable-512.png", 512)]:
    im = Image.open(os.path.join(REPO, name))
    check(im.size == (px, px), f"{name} is {im.size}")
    check(im.convert("RGB").getpixel((px // 2, 4)) == (18, 18, 18), f"{name}: ink to the edge (home screens round it)")
svg = open(os.path.join(REPO, "favicon.svg")).read()
check(svg.startswith("<svg") and "<path" in svg and "<text" not in svg, "favicon.svg draws the S as a path, needs no font")
man = json.load(open(os.path.join(REPO, "site.webmanifest")))
check(man["name"] == "Spokane in Progress" and {i["src"] for i in man["icons"]} == {"/icon-192.png", "/icon-512.png", "/icon-maskable-512.png"}, man)
check(any(i.get("purpose") == "maskable" for i in man["icons"]), "a maskable icon")
for page in ["index.html", "stats.html", "about.html", "glossary.html", "404.html"]:
    html = open(os.path.join(REPO, page)).read()
    for tag in ['rel="icon" href="/favicon.ico"', 'rel="icon" href="/favicon.svg"', 'rel="apple-touch-icon"', 'rel="manifest" href="/site.webmanifest"']:
        check(tag in html, f"{page}: {tag}")
some_page = os.path.join(REPO, "p", sorted(os.listdir(os.path.join(REPO, "p")))[0], "index.html")
check('href="/favicon.svg"' in open(some_page).read(), "project share pages name the icon too")

site, _ = make_site(with_facts=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)

    # Hold projects.json back to see the loading state.
    held = []
    pg.route(f"{SITE}/projects.json*", lambda r: held.append(r))
    pg.goto(SITE + "/")
    pg.wait_for_function("window.Share")
    check(pg.locator("#cards .skel").count() == 8, "8 placeholder rows while loading")
    check(pg.locator("#cards").get_attribute("aria-busy") == "true", "list marked busy")
    check(pg.locator("#lede").inner_text() == "Counting homes…", pg.locator("#lede").inner_text())
    check(pg.eval_on_selector("#lede", "e => getComputedStyle(e).color") == "rgb(107, 105, 100)", "loading headline is muted")
    skel_h = pg.eval_on_selector("#cards .skel", "e => e.getBoundingClientRect().height")
    pg.screenshot(path=os.path.join(SHOTS, "loading.png"))
    check(held, "projects.json was asked for")
    held[0].fulfill(path=os.path.join(site, "projects.json"), content_type="application/json")
    pg.wait_for_selector(".card")
    check(pg.locator("#cards .skel").count() == 0 and pg.locator("#cards").get_attribute("aria-busy") is None, "placeholders replaced")
    check(pg.locator("#lede").inner_text().startswith("At least") and "is-loading" not in pg.get_attribute("#lede", "class"), "headline filled in")
    card_h = pg.eval_on_selector_all("#cards > li", "els => els.map(e => e.getBoundingClientRect().height)")
    typical = sorted(card_h)[len(card_h) // 2]
    check(abs(skel_h - typical) <= 4, f"placeholder row {skel_h}px vs a project row {typical}px")
    check(pg.locator("noscript").count() == 1, "a note for browsers without JavaScript")

    # Printing a project.
    pg.locator(".card").first.click()
    pg.wait_for_selector("[data-copy-project]")
    pid = pg.locator(".card.is-active").get_attribute("data-id")
    pg.emulate_media(media="print")
    vis = lambda sel: pg.eval_on_selector(sel, "e => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0")
    check(not vis(".mapwrap") and not vis(".panel") and not vis(".masthead") and not vis(".detail__bar"), "print: map, list and buttons hidden")
    check(vis("#detail") and vis("#detail-body h2"), "print: the project shows")
    after = pg.eval_on_selector("#detail", "e => getComputedStyle(e, '::after').content")
    check(f"/p/{pid}/" in after, f"print: page address at the foot {after}")
    pg.pdf(path=os.path.join(SHOTS, "print-project.pdf"))
    pg.emulate_media(media="screen")

    # 404.
    resp = pg.goto(SITE + "/no-such-page")
    check(resp.status == 404, f"status {resp.status}")
    check(pg.locator("h1").inner_text() == "There’s nothing at this address", pg.locator("h1").inner_text())
    check(pg.eval_on_selector('meta[name="robots"]', "e => e.content") == "noindex", "404 is noindex")
    check(pg.eval_on_selector(".masthead", "e => getComputedStyle(e).borderBottomWidth") == "1px", "404 is styled (stylesheet loaded from /)")
    pg.goto(SITE + "/p/deep/missing/page")
    check(pg.eval_on_selector(".masthead", "e => getComputedStyle(e).borderBottomWidth") == "1px", "styled at a deep address too")
    pg.screenshot(path=os.path.join(SHOTS, "404.png"))

    check(not errors, f"page errors: {errors}")
    b.close()

print(f"{ok} checks passed")
