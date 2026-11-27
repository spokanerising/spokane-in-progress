"""Facts about each project's site, for the map's newer filters.

build.py runs `assign(projects, records)` after boundaries.assign. Each
project can gain:

  parcels        every county parcel number in the project's building and
                 pre-development permits (plus the sheet's parcel_id)
  acres          those parcels' combined area, from the County Assessor
  homesPerAcre   units / acres, when both are known
  zone           the city zoning code at the map point, e.g. "RMF" or "CC2-DC"
  zoneBase       the code without height or overlay suffixes, e.g. "CC2"
  zoneGroup      Residential / Centers & Corridors / Downtown / ...
  zoneName       the zone's plain-English name, when the city layer has one
  transitMiles   straight-line miles to the nearest frequent-transit stop
  transitStop    that stop's name
  transitRoutes  the frequent routes serving it, e.g. ["1", "25"]

Every source fails soft: if a server can't be reached the build carries on,
projects just go without that fact until the next run, and anything already
looked up comes from the caches in data/.

Sources
  Lot size   Spokane County Assessor, Assessor/Parcels/MapServer/0
             (`acreage` by PID_NUM; falls back to the parcel's drawn area).
             Cached in data/parcel-acres.json; rechecked after 180 days.
  Zoning     The City of Spokane's GIS server. The zoning layer is found by
             name the first time (saved in data/zoning-source.json) and asked
             about each map point once (data/zoning-cache.json).
  Transit    Spokane Transit's public GTFS schedule. A stop counts as
             frequent when some route stops there, in one direction, at
             least every 15 minutes on average between 10 a.m. and 2 p.m. on
             a weekday (16+ departures). Stops in data/transit-stops.csv,
             refreshed weekly; data/transit-meta.json says when and how.

Standard library only.
"""

import csv
import io
import json
import math
import os
import re
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

HEADERS = {"User-Agent": "spokane-in-progress (projects.spokanerising.com)"}

PARCEL_QUERY = "https://gismo.spokanecounty.org/arcgis/rest/services/Assessor/Parcels/MapServer/0/query"
CITY_GIS = "https://services.spokanegis.org/arcgis/rest/services"
GTFS_URL = "https://www.spokanetransit.com/gtfs"

ACRES_PATH = os.path.join("data", "parcel-acres.json")
ZONING_SOURCE_PATH = os.path.join("data", "zoning-source.json")
ZONING_CACHE_PATH = os.path.join("data", "zoning-cache.json")
STOPS_PATH = os.path.join("data", "transit-stops.csv")
TRANSIT_META_PATH = os.path.join("data", "transit-meta.json")

PIN = re.compile(r"^\d{5}\.\d{4}$")
SQ_M_PER_ACRE = 4046.8564224
EARTH_M = 6371008.8
M_PER_MILE = 1609.344


def today():
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def get_json(url, params=None, timeout=45):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(full, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "server error"))
    return payload


def post_json(url, params, timeout=60):
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "server error"))
    return payload


def load(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def save(path, data):
    """Sorted, one entry per line, so a day's changes are a short diff."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        if isinstance(data, dict) and all(isinstance(v, (dict, type(None))) for v in data.values()) and len(data) > 3:
            handle.write("{\n")
            items = sorted(data.items())
            for i, (key, value) in enumerate(items):
                comma = "," if i < len(items) - 1 else ""
                handle.write(f"  {json.dumps(key)}: {json.dumps(value, sort_keys=True)}{comma}\n")
            handle.write("}\n")
        else:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")


def point_key(lat, lng):
    return f"{lat:.5f},{lng:.5f}"


def miles_between(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a)) / M_PER_MILE


def ring_area_m2(ring):
    """Signed area of a lon/lat ring in square metres. Projected onto a local
    plane around the ring's first point first: Spokane longitudes near -117
    would otherwise swamp the shoelace sum (see the parcel-centroid bug in
    build.py)."""
    if len(ring) < 3:
        return 0.0
    lng0, lat0 = ring[0][0], ring[0][1]
    kx = math.radians(1) * EARTH_M * math.cos(math.radians(lat0))
    ky = math.radians(1) * EARTH_M
    pts = [((x - lng0) * kx, (y - lat0) * ky) for x, y in (pt[:2] for pt in ring)]
    total = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        total += x1 * y2 - x2 * y1
    return total / 2


def rings_acres(rings):
    """Esri polygons: outer rings clockwise, holes counter-clockwise, so the
    signed sum is the area with holes taken out."""
    return abs(sum(ring_area_m2(r) for r in rings)) / SQ_M_PER_ACRE


# ---------------------------------------------------------------------------
# Parcels and lot size
# ---------------------------------------------------------------------------

def project_parcels(project, records, kind_of):
    """Parcel numbers for the project's own building and pre-development
    permits, plus the sheet's parcel_id. Trade permits are left out: an
    electrician on the lot next door shouldn't make the project bigger."""
    pins = []
    if PIN.match(project.get("parcelId") or ""):
        pins.append(project["parcelId"])
    for permit in project.get("permitNumbers") or []:
        record = records.get(permit) if records else None
        if not record or not PIN.match(record.get("parcel") or ""):
            continue
        try:
            kind = kind_of(record)
        except Exception:
            kind = ""
        if kind in ("building", "predev") and record["parcel"] not in pins:
            pins.append(record["parcel"])
    return pins


def ask_acres(pins):
    """{pin: acres or None} for up to ~100 parcel numbers."""
    quoted = ",".join("'%s'" % p.replace("'", "''") for p in pins)
    payload = post_json(PARCEL_QUERY, {
        "where": f"PID_NUM IN ({quoted})",
        "outFields": "PID_NUM,acreage",
        "returnGeometry": "true",
        "outSR": "4326",
        "geometryPrecision": "7",
        "f": "json",
    })
    found = {}
    for feature in payload.get("features") or []:
        attrs = feature.get("attributes") or {}
        pin = (attrs.get("PID_NUM") or "").strip()
        if not pin:
            continue
        acres = attrs.get("acreage")
        if not (isinstance(acres, (int, float)) and acres > 0):
            rings = (feature.get("geometry") or {}).get("rings") or []
            acres = rings_acres(rings) if rings else None
        if acres:
            found[pin] = round(found.get(pin, 0) + acres, 4)  # a parcel drawn in pieces
    return {pin: found.get(pin) for pin in pins}


def fill_acres(projects, records, kind_of, ask=ask_acres, cache=None, now=None):
    cache = load(ACRES_PATH, {}) if cache is None else cache
    now = now or today()
    stale_before = (now - timedelta(days=180)).isoformat()
    warnings = []

    for p in projects:
        p["parcels"] = project_parcels(p, records, kind_of)

    wanted = sorted({pin for p in projects for pin in p["parcels"]
                     if pin not in cache or (cache[pin] or {}).get("checked", "") < stale_before})
    changed = False
    for i in range(0, len(wanted), 80):
        batch = wanted[i:i + 80]
        try:
            answers = ask(batch)
        except Exception as error:
            warnings.append(f"Lot sizes: the county parcel service didn't answer ({error}); "
                            "homes per acre is missing for new projects until the next build.")
            break
        for pin in batch:
            cache[pin] = {"acres": answers.get(pin), "checked": now.isoformat()}
        changed = True
    if changed:
        save(ACRES_PATH, cache)

    for p in projects:
        sizes = [(cache.get(pin) or {}).get("acres") for pin in p["parcels"]]
        if p["parcels"] and all(isinstance(a, (int, float)) and a > 0 for a in sizes):
            acres = sum(sizes)
            p["acres"] = round(acres, 3)
            units = p.get("units")
            if isinstance(units, (int, float)) and units > 0 and acres >= 0.01:
                p["homesPerAcre"] = round(units / acres, 1)
    return warnings


# ---------------------------------------------------------------------------
# Zoning
# ---------------------------------------------------------------------------

ZONE_GROUPS = [
    (re.compile(r"^DT"), "Downtown"),
    (re.compile(r"^(CC|CA)\d"), "Centers & Corridors"),
    (re.compile(r"^(RA|RSF|RTF|RMF|RHD|R\d|R-)"), "Residential"),
    (re.compile(r"^(NR|NMU|CB|GC|OR|O|NC|MU)(\b|-|\d|$)"), "Commercial & mixed use"),
    (re.compile(r"^(LI|HI|I\d|I-|IP)"), "Industrial"),
]

# Plain names for common codes, used only when the city's layer doesn't
# carry its own description.
ZONE_NAMES = {
    "RA": "Residential Agriculture", "RSF": "Residential Single-Family", "RTF": "Residential Two-Family",
    "RMF": "Residential Multifamily", "RHD": "Residential High Density",
    "R1": "Residential 1", "R2": "Residential 2",
    "CC1": "Centers & Corridors Core", "CC2": "Centers & Corridors Core", "CC3": "Centers & Corridors Transition",
    "CC4": "Centers & Corridors Transition",
    "CA1": "Centers & Corridors (pedestrian)", "CA2": "Centers & Corridors (district center)",
    "CA3": "Centers & Corridors (auto-oriented)", "CA4": "Centers & Corridors (district center)",
    "DTC": "Downtown Core", "DTG": "Downtown General", "DTU": "Downtown Urban", "DTS": "Downtown South",
    "NR": "Neighborhood Retail", "NMU": "Neighborhood Mixed Use", "CB": "Community Business",
    "GC": "General Commercial", "O": "Office", "OR": "Office Retail",
    "LI": "Light Industrial", "HI": "Heavy Industrial", "PO": "Parking Only",
}


def zone_base(code):
    m = re.match(r"^([A-Z]+\d?)", (code or "").strip().upper())
    return m.group(1) if m else ""


def zone_group(code):
    base = zone_base(code)
    for pattern, label in ZONE_GROUPS:
        if pattern.match(base):
            return label
    return "Other"


SKIP_LAYER = re.compile(r"overlay|historic|proposed|airport|airfield|shoreline|label|anno|bound|change|"
                        r"index|grid|buffer|district\s*map|height|parking|sign", re.I)
CODE_FIELD = re.compile(r"^(zone|zoning|zone_?code|zoning_?code|zone_?class|zonecode|zoning_?class|zoneclass|zone_?name)$", re.I)
DESC_FIELD = re.compile(r"desc|label|long|full", re.I)


def discover_zoning(get=get_json):
    """Finds the city's zoning layer by name. Returns {url, field, descField,
    layer} or None."""
    root = get(CITY_GIS, {"f": "json"})
    services = list(root.get("services") or [])
    for folder in root.get("folders") or []:
        try:
            services += get(f"{CITY_GIS}/{folder}", {"f": "json"}).get("services") or []
        except Exception:
            continue
    services = [s for s in services if s.get("type") in ("MapServer", "FeatureServer")]

    def rank(s):
        name = s.get("name", "")
        return (0 if re.search(r"zon", name, re.I) else 1 if re.search(r"plan|landuse|public", name, re.I) else 2, name)

    for service in sorted(services, key=rank)[:25]:
        if rank(service)[0] == 2:
            break
        try:
            layers = get(f"{CITY_GIS}/{service['name']}/{service['type']}/layers", {"f": "json"}).get("layers") or []
        except Exception:
            continue
        for layer in layers:
            name = layer.get("name", "")
            if layer.get("geometryType") != "esriGeometryPolygon":
                continue
            if not re.search(r"zon", name, re.I) or SKIP_LAYER.search(name):
                continue
            fields = [f for f in layer.get("fields") or [] if f.get("type") == "esriFieldTypeString"]
            code = next((f["name"] for f in fields if CODE_FIELD.match(f["name"]) or CODE_FIELD.match(f.get("alias", ""))), None)
            if not code:
                code = next((f["name"] for f in fields if re.search(r"zon", f["name"], re.I)), None)
            if not code:
                continue
            desc = next((f["name"] for f in fields if f["name"] != code and DESC_FIELD.search(f["name"])), None)
            return {
                "url": f"{CITY_GIS}/{service['name']}/{service['type']}/{layer['id']}/query",
                "field": code,
                "descField": desc,
                "layer": f"{service['name']} / {name}",
                "found": today().isoformat(),
            }
    return None


def ask_zone(source, lat, lng, get=get_json):
    fields = ",".join(f for f in (source["field"], source.get("descField")) if f)
    payload = get(source["url"], {
        "geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
        "returnGeometry": "false", "f": "json",
    })
    for feature in payload.get("features") or []:
        attrs = feature.get("attributes") or {}
        code = (attrs.get(source["field"]) or "").strip()
        if code:
            return {"zone": code, "name": (attrs.get(source.get("descField") or "") or "").strip()}
    return {"zone": "", "name": ""}


def fill_zoning(projects, discover=discover_zoning, ask=ask_zone, source=None, cache=None):
    warnings = []
    source = load(ZONING_SOURCE_PATH, None) if source is None else source
    if not source:
        try:
            source = discover()
        except Exception as error:
            warnings.append(f"Zoning: couldn't look for the city's zoning layer ({error}); trying again next build.")
            source = None
        if source:
            save(ZONING_SOURCE_PATH, source)
            print(f"Zoning: using {source['layer']} (field {source['field']}).")
        elif not warnings:
            warnings.append("Zoning: no zoning layer found on the city's GIS server. "
                            "Put its query URL and code field in data/zoning-source.json.")
    cache = load(ZONING_CACHE_PATH, {}) if cache is None else cache
    if source and cache.get("source") != source["url"]:
        cache = {"source": source["url"], "points": {}}
    points = cache.setdefault("points", {})

    changed = failed = False
    for p in projects:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        key = point_key(lat, lng)
        found = points.get(key)
        if found is None and source and not failed:
            try:
                found = ask(source, lat, lng)
                points[key] = found
                changed = True
            except Exception as error:
                failed = True
                warnings.append(f"Zoning lookup unavailable ({error}); new projects go without until the next build.")
        if not found or not found.get("zone"):
            continue
        code = found["zone"]
        base = zone_base(code)
        p["zone"] = code
        p["zoneBase"] = base or code
        p["zoneGroup"] = zone_group(code)
        name = found.get("name") or ZONE_NAMES.get(base, "")
        if name and name.upper() != code.upper():
            p["zoneName"] = name
    if changed:
        save(ZONING_CACHE_PATH, cache)
    return warnings


# ---------------------------------------------------------------------------
# Frequent transit
# ---------------------------------------------------------------------------

WINDOW = (10 * 3600, 14 * 3600)   # 10 a.m. to 2 p.m.
MIN_DEPARTURES = 16               # 4 hours at every 15 minutes


def _seconds(hms):
    try:
        h, m, s = (int(x) for x in hms.strip().split(":"))
        return h * 3600 + m * 60 + s
    except (ValueError, AttributeError):
        return None


def _rows(archive, name):
    """csv.DictReader over a GTFS file, tolerant of a BOM and of a folder
    inside the zip."""
    match = next((n for n in archive.namelist() if n.split("/")[-1] == name), None)
    if not match:
        return iter(())
    return csv.DictReader(io.TextIOWrapper(archive.open(match), encoding="utf-8-sig"))


def service_day(archive, now):
    """A typical weekday: the next Wednesday the schedule covers. Returns
    (date, set of service_ids running that day)."""
    calendar = list(_rows(archive, "calendar.txt"))
    exceptions = list(_rows(archive, "calendar_dates.txt"))
    for offset in range(0, 60):
        day = now + timedelta(days=offset)
        if day.weekday() != 2:
            continue
        stamp = day.strftime("%Y%m%d")
        running = {
            c["service_id"] for c in calendar
            if c.get("wednesday") == "1" and c.get("start_date", "") <= stamp <= c.get("end_date", "")
        }
        for e in exceptions:
            if e.get("date") == stamp:
                if e.get("exception_type") == "1":
                    running.add(e["service_id"])
                elif e.get("exception_type") == "2":
                    running.discard(e["service_id"])
        if running:
            return day, running
    return None, set()


def frequent_stops(archive, now=None):
    """[{id, name, lat, lng, routes}] for stops with frequent midday service."""
    now = now or today()
    day, running = service_day(archive, now)
    if not running:
        raise RuntimeError("no weekday service found in the schedule")
    routes = {r["route_id"]: (r.get("route_short_name") or r.get("route_long_name") or r["route_id"]).strip()
              for r in _rows(archive, "routes.txt")}
    trips = {}
    for t in _rows(archive, "trips.txt"):
        if t.get("service_id") in running:
            trips[t["trip_id"]] = (t["route_id"], t.get("direction_id") or "0")

    counts = {}
    for st in _rows(archive, "stop_times.txt"):
        trip = trips.get(st.get("trip_id"))
        if not trip:
            continue
        t = _seconds(st.get("departure_time") or st.get("arrival_time") or "")
        if t is None or not (WINDOW[0] <= t < WINDOW[1]):
            continue
        if st.get("pickup_type") == "1":       # drop-off only
            continue
        key = (st["stop_id"], trip[0], trip[1])
        counts[key] = counts.get(key, 0) + 1

    frequent = {}
    for (stop, route, _direction), n in counts.items():
        if n >= MIN_DEPARTURES:
            frequent.setdefault(stop, set()).add(routes.get(route, route))

    stops = []
    for s in _rows(archive, "stops.txt"):
        if s.get("stop_id") in frequent:
            try:
                lat, lng = float(s["stop_lat"]), float(s["stop_lon"])
            except (KeyError, ValueError):
                continue
            stops.append({
                "id": s["stop_id"], "name": (s.get("stop_name") or "").strip(), "lat": lat, "lng": lng,
                "routes": sorted(frequent[s["stop_id"]], key=lambda r: (len(r), r)),
            })
    return day, stops


def download_gtfs(url=GTFS_URL):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if not data.startswith(b"PK"):
        raise RuntimeError("the schedule download wasn't a zip file")
    return zipfile.ZipFile(io.BytesIO(data))


def load_stops():
    try:
        with open(STOPS_PATH, encoding="utf-8") as handle:
            return [
                {"id": r["stop_id"], "name": r["stop_name"], "lat": float(r["lat"]), "lng": float(r["lng"]),
                 "routes": [x for x in r["routes"].split(";") if x]}
                for r in csv.DictReader(handle)
            ]
    except (OSError, ValueError, KeyError):
        return []


def save_stops(stops):
    os.makedirs(os.path.dirname(STOPS_PATH), exist_ok=True)
    with open(STOPS_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["stop_id", "stop_name", "lat", "lng", "routes"])
        for s in sorted(stops, key=lambda s: s["id"]):
            writer.writerow([s["id"], s["name"], f"{s['lat']:.6f}", f"{s['lng']:.6f}", ";".join(s["routes"])])


def fill_transit(projects, download=download_gtfs, now=None):
    now = now or today()
    warnings = []
    meta = load(TRANSIT_META_PATH, {})
    stops = load_stops()
    fresh = meta.get("fetched", "") >= (now - timedelta(days=7)).isoformat()
    if not stops or not fresh:
        try:
            day, found = frequent_stops(download(), now)
            if len(found) < 10:
                raise RuntimeError(f"only {len(found)} frequent stops found; kept the last good list")
            stops = found
            save_stops(stops)
            save(TRANSIT_META_PATH, {
                "fetched": now.isoformat(), "serviceDay": day.isoformat(), "source": GTFS_URL,
                "rule": "16+ departures, 10am-2pm, one route in one direction (every 15 minutes or better)",
                "stops": len(stops),
            })
            print(f"Transit: {len(stops)} frequent stops from Spokane Transit's schedule for {day.isoformat()}.")
        except Exception as error:
            warnings.append(f"Transit: couldn't refresh Spokane Transit's schedule ({error})"
                            + ("; using the saved stop list." if stops else "; distances skipped."))
    if not stops:
        return warnings
    for p in projects:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        best = min(stops, key=lambda s: miles_between(lat, lng, s["lat"], s["lng"]))
        p["transitMiles"] = round(miles_between(lat, lng, best["lat"], best["lng"]), 2)
        p["transitStop"] = best["name"]
        p["transitRoutes"] = best["routes"]
    return warnings


# ---------------------------------------------------------------------------

def assign(projects, records, kind_of):
    """Runs all three. Returns a list of warnings."""
    warnings = []
    for step in (lambda: fill_acres(projects, records, kind_of),
                 lambda: fill_zoning(projects),
                 lambda: fill_transit(projects)):
        try:
            warnings.extend(step())
        except Exception as error:  # a bug in one source never sinks the build
            warnings.append(f"Site facts: {error!r}")
    return warnings
