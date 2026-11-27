"""Official neighborhood council and City Council district for each project.

build.py runs `assign(projects)` after the other last-pass steps. For each
project's map point it asks the city's Boundaries layer which neighborhood
council and council district the point falls in:

  PublicData/Boundaries_WM_Dynamic/MapServer/4  Neighborhood Council (Name)
  PublicData/Boundaries_WM_Dynamic/MapServer/3  City Council District (District)

Answers are kept in data/boundary-cache.json, keyed by the point rounded to
5 decimals (about a metre), so each point is asked about once. Moving a
project's point changes its key, so it is looked up again. If the server
can't be reached, a project simply goes without until the next build; nothing
else in the build is held up.

Each project gets:
  neighborhoodCouncil  e.g. "Emerson/Garfield" ("" outside every council)
  councilDistrict      1, 2 or 3 (None outside the city)

Display: auto-added projects show the official name as their neighborhood, so
the list and the filter agree. A neighborhood typed in the sheet is kept for
display (it may be more specific, like "Kendall Yards"); the filter still uses
the official council. Standard library only.
"""

import json
import os
import urllib.parse
import urllib.request

LAYER = "https://services.spokanegis.org/arcgis/rest/services/PublicData/Boundaries_WM_Dynamic/MapServer/{layer}/query"
CACHE_PATH = os.path.join("data", "boundary-cache.json")
HEADERS = {"User-Agent": "spokane-in-progress (projects.spokanerising.com)"}


def _key(lat, lng):
    return f"{lat:.5f},{lng:.5f}"


def _ask(layer, field, lat, lng):
    params = urllib.parse.urlencode({
        "geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outFields": field,
        "returnGeometry": "false", "f": "json",
    })
    request = urllib.request.Request(LAYER.format(layer=layer) + "?" + params, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "boundary layer error"))
    values = [f["attributes"].get(field) for f in payload.get("features") or []]
    return values[0] if values else None


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        handle.write("{\n")
        items = sorted(cache.items())
        for i, (key, value) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            handle.write(f"  {json.dumps(key)}: {json.dumps(value, sort_keys=True)}{comma}\n")
        handle.write("}\n")


# ---- outlines for the map --------------------------------------------------
#
# When someone filters to a neighborhood or district, the map draws its edge.
# The shapes are fetched from the same layers, lightly simplified (about 5 m),
# and written to boundaries.geojson in the site root. They change rarely, so
# the file is refreshed every 30 days; if the server is down the old file stays.

OUTLINES_PATH = "boundaries.geojson"
OUTLINE_LAYERS = [(4, "Name", "hood"), (3, "District", "district")]


def _signed_area(ring):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / 2


def _inside(point, ring):
    x, y = point
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def rings_to_geometry(rings):
    """Esri rings (outer clockwise, holes counter-clockwise) to a GeoJSON
    Polygon or MultiPolygon."""
    rings = [[(round(x, 5), round(y, 5)) for x, y, *_ in r] for r in rings if len(r) >= 4]
    outers = [[r] for r in rings if _signed_area(r) < 0]
    holes = [r for r in rings if _signed_area(r) >= 0]
    if not outers:  # winding not as expected: treat every ring as an outer
        outers, holes = [[r] for r in rings], []
    for hole in holes:
        home = next((o for o in outers if _inside(hole[0], o[0])), None)
        if home:
            home.append(hole)
    polys = [[[list(pt) for pt in ring] for ring in poly] for poly in outers]
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def _ask_shapes(layer, field):
    params = urllib.parse.urlencode({
        "where": "1=1", "outFields": field, "returnGeometry": "true", "outSR": "4326",
        "maxAllowableOffset": "0.00005", "geometryPrecision": "5", "f": "json",
    })
    request = urllib.request.Request(LAYER.format(layer=layer) + "?" + params, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "boundary layer error"))
    return payload.get("features") or []


def write_outlines(ask=_ask_shapes, path=OUTLINES_PATH, max_age_days=30, now=None):
    """Writes boundaries.geojson. Returns a list of warnings."""
    import time
    now = now or time.time()
    try:
        if now - os.path.getmtime(path) < max_age_days * 86400:
            with open(path, encoding="utf-8") as handle:
                if json.load(handle).get("features"):
                    return []
    except (OSError, ValueError):
        pass
    features = []
    try:
        for layer, field, kind in OUTLINE_LAYERS:
            for f in ask(layer, field):
                name = (f.get("attributes") or {}).get(field)
                rings = (f.get("geometry") or {}).get("rings") or []
                if name in (None, "") or not rings:
                    continue
                features.append({
                    "type": "Feature",
                    "properties": {"kind": kind, "name": str(name) if kind == "hood" else int(name)},
                    "geometry": rings_to_geometry(rings),
                })
    except Exception as error:
        return [f"Neighborhood outlines unavailable ({error}); the map keeps the last copy."]
    if not features:
        return ["Neighborhood outlines: the boundary layers returned no shapes."]
    features.sort(key=lambda f: (f["properties"]["kind"], str(f["properties"]["name"])))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"type": "FeatureCollection", "features": [\n')
        for i, feature in enumerate(features):
            handle.write(json.dumps(feature, separators=(",", ":")) + ("," if i < len(features) - 1 else "") + "\n")
        handle.write("]}\n")
    return []


def assign(projects, cache=None, ask=_ask):
    """Fills neighborhoodCouncil and councilDistrict. Returns a list of warnings."""
    cache = load_cache() if cache is None else cache
    warnings, changed, failed = [], False, False
    for p in projects:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        key = _key(lat, lng)
        found = cache.get(key)
        if found is None and not failed:
            try:
                found = {
                    "neighborhood": ask(4, "Name", lat, lng) or "",
                    "district": ask(3, "District", lat, lng),
                }
                cache[key] = found
                changed = True
            except Exception as error:  # network, server, bad JSON: try again tomorrow
                failed = True
                warnings.append(f"Neighborhood lookup unavailable ({error}); new projects go without until the next build.")
        if not found:
            continue
        p["neighborhoodCouncil"] = found.get("neighborhood") or ""
        p["councilDistrict"] = found.get("district")
        if p.get("autoAdded") and found.get("neighborhood"):
            p["neighborhood"] = found["neighborhood"]
        elif not p.get("neighborhood") and found.get("neighborhood"):
            p["neighborhood"] = found["neighborhood"]
        if not found.get("neighborhood"):
            warnings.append(f'{p.get("name")}: map point is outside every neighborhood council; check its location.')
    if changed:
        save_cache(cache)
    return warnings
