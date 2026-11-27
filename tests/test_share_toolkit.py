"""share.js: share links for each network, copying, downloads, CSV, the
notice, the credit line; and the pages that use it (Copy link, Share this
view, the About page's CSV)."""
import csv, io, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

site, data = make_site()
N = len(data["projects"])
with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 860}, permissions=["clipboard-read", "clipboard-write"], accept_downloads=True)
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site); pg.goto(f"{SITE}/")
    pg.wait_for_function("typeof map !== 'undefined' && map && state.list")

    # Share links
    url = "https://projects.spokanerising.com/p/city-b2404005bldc/"
    text = "Peyton Building Conversion: 96 homes, under construction in Riverside. Via Spokane in Progress"
    links = pg.evaluate("([u, t]) => Share.shareLinks(u, t, 'Peyton Building Conversion')", [url, text])
    check([l["id"] for l in links] == ["bluesky", "reddit", "linkedin", "x", "email"], [l["id"] for l in links])
    q = lambda href: dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(href).query))
    bsky = q(links[0]["href"])["text"]
    check(bsky.endswith(url) and bsky.startswith("Peyton") and len(bsky) <= 300, bsky)
    check(q(links[1]["href"]) == {"url": url, "title": "Peyton Building Conversion"}, links[1]["href"])
    check(q(links[2]["href"]) == {"url": url}, links[2]["href"])
    check(q(links[3]["href"])["url"] == url and q(links[3]["href"])["text"] == text, links[3]["href"])
    mail = urllib.parse.urlsplit(links[4]["href"])
    check(mail.scheme == "mailto" and url in urllib.parse.unquote(mail.query), links[4]["href"])
    long = "x" * 500
    blong = q(pg.evaluate("([u, t]) => Share.shareLinks(u, t)[0].href", [url, long]))["text"]
    check(len(blong) <= 300 and blong.endswith(url) and "…" in blong, f"bluesky trims long text ({len(blong)})")
    xlong = q(pg.evaluate("([u, t]) => Share.shareLinks(u, t)[3].href", [url, long]))["text"]
    check(len(xlong) + 24 <= 280, f"x trims long text ({len(xlong)})")

    # CSV quoting
    csvtext = pg.evaluate("""() => Share.toCsv([{a: 'Plain', b: 'Has, comma'}, {a: 'Has "quote"', b: ['x', 'y']}, {a: null, b: 'Line\\nbreak'}],
                              [{label: 'A', value: r => r.a}, {label: 'B', value: r => r.b}])""")
    check(csvtext.startswith("﻿"), "BOM for Excel")
    rows = list(csv.reader(io.StringIO(csvtext.lstrip("﻿"))))
    check(rows == [["A", "B"], ["Plain", "Has, comma"], ['Has "quote"', "x; y"], ["", "Line\nbreak"]], rows)
    check(pg.evaluate("Share.filename(['filtered'], 'csv', new Date('2026-11-26T12:00:00Z'))") == "spokane-in-progress-2026-11-26-filtered.csv", "filename")
    check(pg.evaluate("Share.creditLine(new Date(2026, 10, 26), ['© OpenStreetMap contributors'])")
          == "Spokane in Progress · projects.spokanerising.com · Data as of Nov. 26, 2026 · © OpenStreetMap contributors", "credit line")

    # Canvas download
    with pg.expect_download() as dl:
        pg.evaluate("() => { const c = document.createElement('canvas'); c.width = 40; c.height = 20; c.getContext('2d').fillRect(0,0,40,20); return Share.downloadCanvas(c, 'test.png'); }")
    path = dl.value.path()
    check(open(path, "rb").read(8) == b"\x89PNG\r\n\x1a\n", "canvas saved as PNG")

    # Copy link (from the Share menu): clipboard + notice
    pg.locator("#share-view").click()
    pg.locator('.menu [data-item="copy"]').click()
    pg.wait_for_selector("#toast.is-on")
    check(pg.locator("#toast").inner_text() == "Link copied", pg.locator("#toast").inner_text())
    check(pg.evaluate("navigator.clipboard.readText()") == pg.url, "clipboard holds the page address")
    pg.wait_for_timeout(2900)
    check(not pg.locator("#toast").evaluate("e => e.classList.contains('is-on')"), "notice goes away")

    # Copy fails: the notice shows the link instead of a prompt dialog
    dialogs = []
    pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    pg.evaluate("Share.copyText = async () => false")
    pg.locator("#share-view").click()
    pg.locator('.menu [data-item="copy"]').click()
    pg.wait_for_function("document.getElementById('toast').textContent.startsWith('Copy this link:')")
    check(not dialogs, "no prompt dialog")

    # About page CSV goes through the toolkit and has the new columns
    ab = ctx.new_page(); ab.on("pageerror", lambda e: errors.append(str(e)))
    wire(ab, site); ab.goto(f"{SITE}/about.html")
    ab.wait_for_selector("#download")
    with ab.expect_download() as dl:
        ab.locator("#download").click()
    check(dl.value.suggested_filename.startswith("spokane-in-progress-") and dl.value.suggested_filename.endswith(".csv"), dl.value.suggested_filename)
    rows = list(csv.reader(io.StringIO(open(dl.value.path(), encoding="utf-8-sig").read())))
    check(len(rows) == N + 1, f"{len(rows) - 1} rows, {N} projects")
    for col in ["zoning", "lot_acres", "homes_per_acre", "miles_to_frequent_transit", "link"]:
        check(col in rows[0], f"column {col}")
    check(ab.locator("#toast").inner_text().startswith(f"Downloaded {N}"), "about notice")

    check(not errors, errors)
    b.close()
print(f"{ok} checks passed")
