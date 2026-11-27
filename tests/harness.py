"""Serves a copy of the site to headless Chrome with the network stubbed out:
maplibre from the npm copy, a blank base map style, and fake answers for the
city's geocoder and OpenStreetMap search."""
import hashlib, json, math, mimetypes, os, shutil, tempfile
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHOTS = os.environ.get("SHOTS", os.path.join(HERE, ".shots"))
VENDOR = os.environ.get("MAPLIBRE_DIST", os.path.join(HERE, ".vendor", "maplibre-gl", "dist"))
MAPLIBRE_VERSION = "4.7.1"  # keep in step with index.html


def ensure_maplibre():
    """The sandbox and CI can't reach unpkg, so tests serve maplibre from an
    npm copy, fetched once into tests/.vendor (git-ignored)."""
    if os.path.isfile(os.path.join(VENDOR, "maplibre-gl.js")):
        return
    import subprocess, tarfile
    target = os.path.join(HERE, ".vendor")
    os.makedirs(target, exist_ok=True)
    name = subprocess.check_output(["npm", "pack", f"maplibre-gl@{MAPLIBRE_VERSION}", "--silent"], cwd=target, text=True).strip().splitlines()[-1]
    with tarfile.open(os.path.join(target, name)) as tar:
        tar.extractall(target, filter="data")
    os.replace(os.path.join(target, "package"), os.path.join(target, "maplibre-gl"))
    os.remove(os.path.join(target, name))
SITE = "https://site.test"

STYLE = {"version": 8, "sources": {}, "layers": [{"id": "bg", "type": "background", "paint": {"background-color": "#ece9e2"}}]}


def h(s, n):
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % n


SITE_FILES = ["index.html", "about.html", "app.js", "about.js", "styles.css", "share.js"]


def make_site(with_facts=True):
    """A temporary copy of the site. with_facts=True swaps in made-up zoning,
    transit and density values so every filter has something to show."""
    ensure_maplibre()
    d = tempfile.mkdtemp(prefix="site-")
    for f in SITE_FILES:
        if not os.path.exists(os.path.join(REPO, f)):
            continue
        shutil.copy(os.path.join(REPO, f), d)
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


def wire(page, site_dir, geocode_fail=False):
    def site(route):
        path = route.request.url.split("site.test/", 1)[1].split("?")[0] or "index.html"
        full = os.path.join(site_dir, path)
        if not os.path.isfile(full):
            return route.fulfill(status=404, body="nope")
        route.fulfill(status=200, body=open(full, "rb").read(), content_type=mimetypes.guess_type(full)[0] or "application/octet-stream")
    page.route(f"{SITE}/**", site)
    page.route("https://unpkg.com/**", lambda r: r.fulfill(status=200, body=open(os.path.join(VENDOR, "maplibre-gl.js" if r.request.url.endswith(".js") else "maplibre-gl.css"), "rb").read(),
                                                         content_type="application/javascript" if r.request.url.endswith(".js") else "text/css"))
    page.route("https://tiles.openfreemap.org/**", lambda r: r.fulfill(status=200, body=json.dumps(STYLE), content_type="application/json"))
    page.route("https://server.arcgisonline.com/**", lambda r: r.abort())
    page.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(status=200, body="", content_type="text/css"))
    page.route("https://fonts.gstatic.com/**", lambda r: r.abort())

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
