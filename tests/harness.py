"""Serves a copy of the site to headless Chrome with the network stubbed out:
maplibre from the npm copy, a blank base map style, and fake answers for the
city's geocoder and OpenStreetMap search."""
import hashlib, json, math, mimetypes, os, shutil, tempfile
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHOTS = os.environ.get("SHOTS", os.path.join(HERE, ".shots"))
MAPLIBRE_VERSION = "4.7.1"  # keep in step with index.html and vendor/
VENDOR = os.path.join(REPO, "vendor", f"maplibre-gl-{MAPLIBRE_VERSION}")


def ensure_maplibre():
    """The map library is part of the site now (vendor/), so there's nothing
    to fetch. Kept so older callers still work."""
    assert os.path.isfile(os.path.join(VENDOR, "maplibre-gl.js")), f"{VENDOR} is missing"
SITE = "https://site.test"

STYLE = {"version": 8, "sources": {}, "layers": [{"id": "bg", "type": "background", "paint": {"background-color": "#ece9e2"}}]}


def h(s, n):
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % n


SITE_FILES = ["index.html", "brand.css", "about.html", "stats.html", "glossary.html", "app.js", "about.js", "stats.js", "styles.css", "share.js", "numbers.js", "og-card.png", "robots.txt", "styleguide.html",
              "404.html", "glossary.js", "glossary.json", "favicon.ico", "favicon.svg", "apple-touch-icon.png", "site.webmanifest", "icon-192.png", "icon-512.png", "icon-maskable-512.png"]


def make_site(with_facts=True):
    """A temporary copy of the site. with_facts=True swaps in made-up zoning,
    transit and density values so every filter has something to show."""
    ensure_maplibre()
    d = tempfile.mkdtemp(prefix="site-")
    for f in SITE_FILES:
        if not os.path.exists(os.path.join(REPO, f)):
            continue
        shutil.copy(os.path.join(REPO, f), d)
    shutil.copytree(os.path.join(REPO, "vendor"), os.path.join(d, "vendor"))
    # The logos (brand/logo.svg) and the rest of the brand folder.
    shutil.copytree(os.path.join(REPO, "brand"), os.path.join(d, "brand"), ignore=shutil.ignore_patterns("source"))
    data = json.load(open(os.path.join(REPO, "projects.json")))
    zones = [("RMF", "Residential", "Residential Multifamily"), ("RSF", "Residential", ""), ("CC2", "Centers & Corridors", ""),
             ("DTC", "Downtown", "Downtown Core"), ("GC", "Commercial & mixed use", ""), ("LI", "Industrial", "")]
    for p in data["projects"]:   # start from a clean slate either way
        for k in ("zone", "zoneBase", "zoneGroup", "zoneName", "transitMiles", "transitStop", "transitRoutes", "parcels", "acres", "homesPerAcre"):
            p.pop(k, None)
    if with_facts:
        for p in data["projects"]:
            k = h(p["id"], 100)
            if k < 90:
                z = zones[k % len(zones)]
                p.update(zone=z[0] + ("-70" if k % 3 == 0 else ""), zoneBase=z[0], zoneGroup=z[1])
                if z[2]: p["zoneName"] = z[2]
            p["transitMiles"] = round((k % 40) / 30, 2)
            p["transitStop"] = f"Stop {k}"
            p["transitRoutes"] = ["1"] if k % 2 else ["25", "90"]
            if p.get("units") and k % 5:
                p["parcels"] = [p["parcelId"]]
                p["acres"] = round(0.1 + (k % 17) / 10, 3)
                p["homesPerAcre"] = round(p["units"] / p["acres"], 1)
    json.dump(data, open(os.path.join(d, "projects.json"), "w"))
    # The sharing pages (pages.py), written for this copy of the site.
    import sys
    sys.path.insert(0, REPO)
    import pages
    pages.write_all(data["projects"], d, SITE)
    # Fake outlines: a box around each neighborhood's projects, and each district's.
    feats = []
    for kind, keyf in (("hood", lambda p: p.get("neighborhoodCouncil")), ("district", lambda p: p.get("councilDistrict"))):
        groups = {}
        for p in data["projects"]:
            k = keyf(p)
            if k: groups.setdefault(k, []).append(p)
        for name, ps in groups.items():
            xs = [p["lng"] for p in ps]; ys = [p["lat"] for p in ps]
            x0, x1, y0, y1 = min(xs) - .003, max(xs) + .003, min(ys) - .003, max(ys) + .003
            ring = [[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]
            feats.append({"type": "Feature", "properties": {"kind": kind, "name": name}, "geometry": {"type": "Polygon", "coordinates": [ring]}})
    json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(d, "boundaries.geojson"), "w"))
    return d, data


def _grey_tile():
    import io, zlib, struct
    w = h = 256
    raw = b"".join(b"\x00" + bytes([120, 128, 110]) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
GREY_TILE = _grey_tile()


def wire(page, site_dir, geocode_fail=False):
    def site(route):
        path = route.request.url.split("site.test/", 1)[1].split("?")[0].split("#")[0]
        full = os.path.join(site_dir, path)
        # Like Cloudflare Pages, "/stats" serves stats.html. (Cloudflare also
        # redirects "/stats.html" to "/stats"; here both are served, because
        # Chromium skips page.route for a redirect's follow-up request.
        # test_links.py checks that no page links to an .html address.)
        if path and "." not in os.path.basename(path) and not path.endswith("/") and os.path.isfile(full + ".html"):
            full = full + ".html"
        if os.path.isdir(full):
            if path and not path.endswith("/"):
                return route.fulfill(status=308, headers={"Location": f"{SITE}/{path}/"})
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            # Cloudflare Pages serves the site's 404.html, when there is one.
            nf = os.path.join(site_dir, "404.html")
            if os.path.isfile(nf):
                return route.fulfill(status=404, body=open(nf, "rb").read(), content_type="text/html")
            return route.fulfill(status=404, body="nope")
        route.fulfill(status=200, body=open(full, "rb").read(), content_type=mimetypes.guess_type(full)[0] or "application/octet-stream")
    page.route(f"{SITE}/**", site)
    # The site no longer loads anything from unpkg; a request there is a bug.
    page.route("https://unpkg.com/**", lambda r: r.fulfill(status=404, body="unpkg is not used"))
    page.route("https://tiles.openfreemap.org/**", lambda r: r.fulfill(status=200, body=json.dumps(STYLE), content_type="application/json"))
    # Satellite tiles: a plain grey square (the project page's satellite view
    # asks for them every time a project opens).
    page.route("https://server.arcgisonline.com/**", lambda r: r.fulfill(status=200, body=GREY_TILE, content_type="image/png"))
    # Fonts come from the site's own copy too (vendor/fonts-*, issue #41).
    page.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(status=404, body="Google Fonts is not used"))
    page.route("https://fonts.gstatic.com/**", lambda r: r.fulfill(status=404, body="Google Fonts is not used"))

    def geocoder(route):
        url = route.request.url
        if geocode_fail:
            return route.abort()
        if "AddressPoint" in url and "SingleLine=10%20N%20Post%20St" in url:
            return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"},
                                 body=json.dumps({"candidates": [{"address": "10 N POST ST", "score": 100, "location": {"x": -117.4233, "y": 47.6576}}]}))
        route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps({"candidates": []}))
    page.route("https://services.spokanegis.org/**", geocoder)

    def osm(route):
        if "Division" in route.request.url:
            return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"},
                                 body=json.dumps([{"lat": "47.6740", "lon": "-117.4110"}]))
        route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body="[]")
    page.route("https://nominatim.openstreetmap.org/**", osm)


def miles(a, b):
    r = math.pi / 180
    dlat = (b[0] - a[0]) * r; dlng = (b[1] - a[1]) * r
    x = math.sin(dlat / 2) ** 2 + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(dlng / 2) ** 2
    return 2 * 3958.7613 * math.asin(math.sqrt(x))
