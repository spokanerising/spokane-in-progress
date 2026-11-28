"""Internal links point at the address a page actually lives at (issue #41).
Cloudflare Pages serves stats.html at /stats and answers /stats.html with a
redirect, so a link to "stats.html" costs every reader an extra round trip.
Also: canonical addresses and the sitemap use the same form, and the map
library comes from the site itself, not unpkg."""
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
    pg.on("request", lambda r: not r.url.startswith(SITE) and "unpkg.com" in r.url and outside.append(r.url))
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
    check(not outside, f"nothing comes from unpkg: {outside}")
    # The glossary popover's "All terms" link.
    pg.goto(f"{SITE}/?p={pid}")
    pg.wait_for_selector("#detail:not([hidden]) .gloss")
    pg.locator("#detail .gloss").first.click()
    pg.wait_for_selector(".glosspop:not([hidden])")
    more = pg.locator(".glosspop a").get_attribute("href")
    check(more.startswith("/glossary#g-"), f"popover links to /glossary: {more}")
    # The map library loaded from the site's own copy.
    check(pg.evaluate("typeof maplibregl !== 'undefined' && maplibregl.getVersion ? maplibregl.getVersion() : ''") == "4.7.1", "MapLibre 4.7.1 from vendor/")
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
# _headers: the rules are there, and no two of them can set Cache-Control on one file.
rules = open(os.path.join(REPO, "_headers"), encoding="utf-8").read()
check("/vendor/*" in rules and "immutable" in rules, "_headers caches vendor/ for a long time")
paths = [l.strip() for l in rules.splitlines() if l.startswith("/")]
check(len(paths) == len(set(paths)), f"_headers paths unique {paths}")

print(f"{ok} checks passed")
