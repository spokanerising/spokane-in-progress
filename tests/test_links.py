"""Internal links point at the address a page actually lives at (issue #41).
Cloudflare Pages serves stats.html at /stats and answers /stats.html with a
redirect, so a link to "stats.html" costs every reader an extra round trip.
Also: canonical addresses and the sitemap use the same form, and the map
library and the fonts come from the site itself, not unpkg or Google."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, REPO
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

HTML_LINK = re.compile(r"\.html($|[#?])")
site, data = make_site(with_facts=False)
pid = data["projects"][0]["id"]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    wire(pg, site)
    outside = []
    pg.on("request", lambda r: not r.url.startswith(SITE) and ("unpkg.com" in r.url or "fonts.g" in r.url) and outside.append(r.url))
    for path, ready in [("/", "#cards > *"), (f"/?p={pid}", "#detail:not([hidden])"), ("/stats", ".chart"),
                        ("/about", "main"), ("/glossary", "#glossary .gloss__term, #glossary dt, #glossary h3"),
                        ("/nope", "body")]:
        pg.goto(SITE + path)
        pg.wait_for_selector(ready)
        pg.wait_for_timeout(300)
        hrefs = pg.evaluate("() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))")
        own = [h for h in hrefs if not re.match(r"^[a-z]+:", h) or h.startswith(SITE)]
        bad = sorted({h for h in own if HTML_LINK.search(h)})
        check(not bad, f"{path}: links to .html addresses {bad}")
        check(len(own) > 0, f"{path}: has internal links")
        # The extensionless addresses really work here, as on Cloudflare.
        for h in {h.split("#")[0] for h in own if h.split("#")[0] in ("/stats", "/about", "/glossary")}:
            check(pg.evaluate("(u) => fetch(u).then(r => r.status)", SITE + h) == 200, f"{h} serves a page")
    check(not outside, f"nothing comes from unpkg or Google Fonts: {outside}")
    # A link to an id that's gone opens the project now carrying that permit,
    # and the address bar shows its current id; an unknown id just shows the map.
    moved = next(p for p in data["projects"] if len(p.get("permitNumbers") or []) > 1
                 and "city-" + p["permitNumbers"][-1].lower() != p["id"])
    old_id = "city-" + moved["permitNumbers"][-1].lower()
    pg.goto(f"{SITE}/?p={old_id}")
    pg.wait_for_selector("#detail:not([hidden])")
    check(pg.evaluate("state.selected") == moved["id"] and f"p={moved['id']}" in pg.url, f"old id {old_id} opens {moved['id']}: {pg.url}")
    pg.goto(f"{SITE}/?p=city-b0000000bldc")
    pg.wait_for_selector("#cards > *")
    pg.wait_for_timeout(300)
    check(pg.locator("#detail").is_hidden() and "p=" not in pg.url, f"unknown id: just the map {pg.url}")
    # The glossary popover's "All terms" link.
    pg.goto(f"{SITE}/?p={pid}")
    pg.wait_for_selector("#detail:not([hidden]) .gloss")
    pg.locator("#detail .gloss").first.click()
    pg.wait_for_selector(".glosspop:not([hidden])")
    more = pg.locator(".glosspop a").get_attribute("href")
    check(more.startswith("/glossary#g-"), f"popover links to /glossary: {more}")
    # The map library loaded from the site's own copy.
    check(pg.evaluate("typeof maplibregl !== 'undefined' && maplibregl.getVersion ? maplibregl.getVersion() : ''") == "4.7.1", "MapLibre 4.7.1 from vendor/")
    # Both typefaces really load, from the site's own copy, at the weights used.
    for face in ("600 20px Literata", "400 20px Literata", "400 16px 'Libre Franklin'", "700 16px 'Libre Franklin'"):
        check(pg.evaluate("(f) => document.fonts.load(f).then(l => l.length > 0 && document.fonts.check(f))", face), f"font loads: {face}")
    browser.close()

# Canonical and share addresses, and the sitemap.
for name in ("stats", "about", "glossary"):
    text = open(os.path.join(REPO, f"{name}.html"), encoding="utf-8").read()
    check(f'rel="canonical" href="https://projects.spokanerising.com/{name}"' in text, f"{name}: canonical without .html")
    check(f'og:url" content="https://projects.spokanerising.com/{name}"' in text, f"{name}: og:url without .html")
sitemap = open(os.path.join(site, "sitemap.xml"), encoding="utf-8").read()
check(not re.search(r"<loc>[^<]*\.html</loc>", sitemap), "sitemap has no .html addresses")
check("<loc>https://site.test/about</loc>" in sitemap, "sitemap lists /about")
index = open(os.path.join(REPO, "index.html"), encoding="utf-8").read()
check("unpkg" not in index and "/vendor/maplibre-gl-4.7.1/maplibre-gl.js" in index, "index.html uses the site's MapLibre")
# Every page: no Google Fonts, the font stylesheet and preloads point at files that exist.
import json
fonts = json.load(open(os.path.join(REPO, "brand", "brand.json"), encoding="utf-8"))["fonts"]
for rel in ("index.html", "about.html", "stats.html", "glossary.html", "404.html", "styleguide.html", "admin/index.html"):
    text = open(os.path.join(REPO, rel), encoding="utf-8").read()
    check("fonts.googleapis" not in text and "fonts.gstatic" not in text, f"{rel}: no Google Fonts")
    check(f'href="{fonts["webfonts"]}"' in text, f"{rel}: loads {fonts['webfonts']}")
    for u in fonts["preload"]:
        check(f'rel="preload" href="{u}"' in text, f"{rel}: preloads {u}")
for u in [fonts["webfonts"]] + fonts["preload"]:
    check(u.startswith("/vendor/") and os.path.isfile(os.path.join(REPO, u.lstrip("/"))), f"{u} is in the repo")
css = open(os.path.join(REPO, fonts["webfonts"].lstrip("/")), encoding="utf-8").read()
for f in re.findall(r"url\(\./([^)]+)\)", css):
    check(os.path.isfile(os.path.join(REPO, os.path.dirname(fonts["webfonts"]).lstrip("/"), f)), f"fonts.css file {f} exists")
check("font-display: swap" in css, "fonts.css swaps in fonts (text shows right away)")
size = sum(os.path.getsize(os.path.join(REPO, u.lstrip("/"))) for u in fonts["preload"])
check(size < 150_000, f"first-load fonts under 150 KB: {size}")
# _headers: the rules are there, and no two of them can set Cache-Control on one file.
rules = open(os.path.join(REPO, "_headers"), encoding="utf-8").read()
check("/vendor/*" in rules and "immutable" in rules, "_headers caches vendor/ for a long time")
paths = [l.strip() for l in rules.splitlines() if l.startswith("/")]
check(len(paths) == len(set(paths)), f"_headers paths unique {paths}")

print(f"{ok} checks passed")
