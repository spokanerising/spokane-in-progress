"""Phase 2 of the sharing plan: a page per project, neighborhood and council
district (pages.py), with its own link-preview tags, forwarding people to
the map; pages for things no longer tracked; the sitemap; the site card;
and share links that use these pages."""
import html.parser, json, os, shutil, sys, tempfile, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, SHOTS, REPO
sys.path.insert(0, REPO)
import pages
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1


class Tags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.meta = {}; self.links = {}; self.title = ""; self._t = False; self.scripts = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            self.meta[a.get("property") or a.get("name")] = a.get("content")
        if tag == "link":
            self.links[a.get("rel")] = a.get("href")
        self._t = tag == "title"; self._s = tag == "script"
    def handle_data(self, data):
        if self._t: self.title += data
        if getattr(self, "_s", False): self.scripts.append(data)
    def handle_endtag(self, tag):
        self._t = False; self._s = False

def tags(path):
    t = Tags(); t.feed(open(path, encoding="utf-8").read()); return t

data = json.load(open(os.path.join(REPO, "projects.json")))
P = data["projects"]
ORIGIN = "https://projects.spokanerising.com"

# ---- the pages on disk
root = tempfile.mkdtemp()
check(pages.write_all(P, root, ORIGIN) == [], "no warnings")
for p in P:
    f = os.path.join(root, "p", p["id"], "index.html")
    check(os.path.isfile(f), f"page for {p['id']}")
t = tags(os.path.join(root, "p", P[0]["id"], "index.html"))
check(t.title == f"{P[0]['name']} · Spokane in Progress", t.title)
check(t.meta["og:title"] == P[0]["name"] and t.meta["twitter:title"] == P[0]["name"], t.meta["og:title"])
check(t.meta["og:url"] == f"{ORIGIN}/p/{P[0]['id']}/" == t.links["canonical"], t.meta["og:url"])
check(t.meta["og:image"] == f"{ORIGIN}/og-card.png" and t.meta["og:image:width"] == "1200" and t.meta["og:image:height"] == "630", "image tags")
check(t.meta["twitter:card"] == "summary_large_image", "twitter card")
check(t.meta["og:description"] == t.meta["description"] and len(t.meta["description"]) > 20, t.meta["description"])
check(json.dumps(f"/?p={P[0]['id']}") in "".join(t.scripts), "forwards to the map")
check(not any("http-equiv" in open(os.path.join(root, "p", P[0]["id"], "index.html")).read() for _ in [0]), "no meta refresh (crawlers would follow it)")

hoods = {p["neighborhoodCouncil"] for p in P if p.get("neighborhoodCouncil")}
check(sorted(os.listdir(os.path.join(root, "n"))) == sorted(pages.slug(h) for h in hoods), "a page per neighborhood with projects")
check(sorted(os.listdir(os.path.join(root, "d"))) == sorted({str(p["councilDistrict"]) for p in P if isinstance(p.get("councilDistrict"), int)}), "a page per district")
riv = tags(os.path.join(root, "n", "riverside", "index.html"))
n_riv = sum(1 for p in P if p.get("neighborhoodCouncil") == "Riverside")
check(riv.meta["og:description"].startswith(f"{n_riv} housing project") and "Riverside" in riv.meta["og:title"], riv.meta["og:description"])

# Words: escaping, missing data, the est. rule
odd = {"id": "test-odd", "name": 'The "Quote" & <Tag> Building', "status": "Under Construction",
       "stageSource": "city permit records: 2 trade permit(s) issued", "units": 12, "address": "1 Main St"}
pages.write_all([odd], root, ORIGIN)
raw = open(os.path.join(root, "p", "test-odd", "index.html"), encoding="utf-8").read()
check("<Tag>" not in raw and "&lt;Tag&gt;" in raw and "&quot;Quote&quot;" in raw, "escaped")
check("likely under construction" in tags(os.path.join(root, "p", "test-odd", "index.html")).meta["description"], "inferred stage says likely")
bare = pages.project_description({"name": "x", "status": "Applied"})
check(bare == "In permit review.", bare)
check(pages.project_description({"status": "Approved", "statusUpdated": "2026-11-17", "stageSinceExact": True, "units": 2,
                                 "buildingType": "Duplex", "address": "4332 W Indian Trail Rd", "neighborhood": "Balboa"})
      == "Duplex with 2 homes, approved Nov. 17, 2026. 4332 W Indian Trail Rd, Balboa.", "event wording")

# Projects that leave the map keep a page; ids that can't be addresses are skipped
gone_id = P[0]["id"]
check(pages.write_all([p for p in P if p["id"] != gone_id], root, ORIGIN) == [], "rewrite without one project")
g = tags(os.path.join(root, "p", gone_id, "index.html"))
check("no longer tracked" in g.meta["og:title"] and P[0]["name"] in g.meta["og:title"] and json.dumps("/") in "".join(g.scripts), g.meta["og:title"])
before = open(os.path.join(root, "p", gone_id, "index.html")).read()
pages.write_all([p for p in P if p["id"] != gone_id], root, ORIGIN)
check(open(os.path.join(root, "p", gone_id, "index.html")).read() == before, "gone page written once, then left alone")
pages.write_all(P, root, ORIGIN)
check("no longer tracked" not in tags(os.path.join(root, "p", gone_id, "index.html")).meta["og:title"], "comes back when the project does")
w = pages.write_all(P + [{"id": "bad id/../x", "name": "Bad"}], root, ORIGIN)
check(w and "can't be a page address" in w[0] and not os.path.exists(os.path.join(root, "x")), w)
w = pages.write_all(P + [dict(P[1])], root, ORIGIN)
check(w and "duplicate" in w[0], "refuses duplicate ids")
sm = open(os.path.join(root, "sitemap.xml")).read()
check(sm.count("<url>") == 4 + len(P) + len(hoods) + len(os.listdir(os.path.join(root, "d"))), "sitemap lists everything current")
shutil.rmtree(root)

# The repo's own copy of the pages matches today's data
check(os.path.isfile(os.path.join(REPO, "og-card.png")), "site card exists")
from struct import unpack
with open(os.path.join(REPO, "og-card.png"), "rb") as f:
    head = f.read(24)
check(head[:8] == b"\x89PNG\r\n\x1a\n" and unpack(">II", head[16:24]) == (1200, 630), "card is a 1200x630 PNG")
for f in ["index.html", "stats.html", "about.html", "glossary.html"]:
    t = tags(os.path.join(REPO, f))
    check(t.meta.get("og:image", "").endswith("/og-card.png") and t.meta.get("og:image:width") == "1200", f"{f} uses the card")

# ---- in a browser
site, _ = make_site()
with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 860}, permissions=["clipboard-read", "clipboard-write"])
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)
    target = next(p for p in P if p.get("units"))
    pg.goto(f"{SITE}/p/{target['id']}/")
    pg.wait_for_url(f"{SITE}/?p={target['id']}")
    pg.wait_for_selector("#detail:not([hidden]) h2")
    check(pg.locator("#detail h2").inner_text() == target["name"], "project page opens the project on the map")
    # (An address without the final slash is redirected by Cloudflare itself;
    # the test browser can't follow a stubbed redirect, so that isn't tested.)
    pg.goto(f"{SITE}/n/riverside/")
    pg.wait_for_url(f"{SITE}/?hood=riverside")
    pg.wait_for_function("typeof state !== 'undefined' && state.list && state.list.length > 0")
    check(pg.evaluate("state.list.length") == n_riv, "neighborhood page opens the filtered map")
    pg.goto(f"{SITE}/d/2/"); pg.wait_for_url(f"{SITE}/?district=2")
    check(True, "district page")

    # Share links use the pages
    pg.goto(f"{SITE}/?hood=riverside"); pg.wait_for_function("typeof map !== 'undefined' && map && state.list")
    pg.locator("#share-view").click()
    bt = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(pg.locator('.menu [data-item="bluesky"]').get_attribute("href")).query))["text"]
    check(bt.endswith(f"{SITE}/n/riverside/"), f"one neighborhood shares its page: {bt}")
    pg.keyboard.press("Escape")
    pg.goto(f"{SITE}/?district=3"); pg.wait_for_function("typeof map !== 'undefined' && map && state.list")
    pg.locator("#share-view").click()
    check(pg.locator('.menu [data-item="linkedin"]').get_attribute("href").endswith(urllib.parse.quote(f"{SITE}/d/3/", safe="")), "one district shares its page")
    pg.keyboard.press("Escape")
    pg.goto(f"{SITE}/?hood=riverside&size=100"); pg.wait_for_function("typeof map !== 'undefined' && map && state.list")
    pg.locator("#share-view").click()
    rd = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(pg.locator('.menu [data-item="reddit"]').get_attribute("href")).query))["url"]
    check("hood=riverside" in rd and "size=100" in rd, f"other filters share the full view: {rd}")
    pg.keyboard.press("Escape")
    pg.goto(f"{SITE}/?p={target['id']}"); pg.wait_for_selector("[data-share-project]")
    pg.locator("[data-share-project]").click()
    pg.locator('.menu [data-item="copy"]').click(); pg.wait_for_selector("#toast.is-on")
    check(pg.evaluate("navigator.clipboard.readText()") == f"{SITE}/p/{target['id']}/", "project link is its page")
    check(not errors, errors)
    b.close()
print(f"{ok} checks passed")
