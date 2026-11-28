"""Map layers (issue #5): fetches, simplifies and writes layers/*.geojson.

Runs once a month on the GitHub runner (.github/workflows/layers.yml), apart
from the daily build: these shapes change rarely, and the Census figures once
a year. Unlike build.py this script may use one library, shapely, for the
geometry work (merging zoning into families, merging the transit circles,
simplifying). build.py stays standard-library only; it just reads the files
this writes (see designations.py).

  python3 layers.py            every layer
  python3 layers.py tracts oz2 only these

Each layer is fetched on its own. If a fetch fails, the old file is kept and
the error goes into layers/meta.json, so one broken server never blanks the
map. A new file must also pass a sanity check (enough features, inside the
Spokane area) before it replaces the old one.

Files (all GeoJSON, lng/lat, coordinates rounded to 5 decimals, about 1 m):

  city-limits.geojson         the City of Spokane boundary
  historic-districts.geojson  local historic districts (Spokane Register)   name
  mfte.geojson                MFTE target areas      area (STIA|AHEA), name, terms
  centers.geojson             Comp Plan centers and corridors          name, kind
  zoning.geojson              zoning merged into families                 family
  tracts.geojson              2020 tracts touching the city, with Census measures
  oz2.geojson                 Opportunity Zone 2.0 tracts (from Jan. 1, 2027)  geoid
  qct.geojson                 HUD Qualified Census Tracts                 geoid, year
  holc.geojson                1938 HOLC grades (map only)          grade, label
  transit.geojson             frequent routes (lines) and the 1/4-mile area
  meta.json                   source, vintage, credit and fetch date for each,
                              and the Census class breaks

The Census API key comes from the CENSUS_API_KEY environment variable (a
GitHub secret). It's never written to a file or printed.
"""

import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime, timezone

import site_facts

try:
    from shapely.geometry import LineString, Point, mapping, shape
    from shapely.ops import transform, unary_union
except ImportError:  # the pure-Python helpers below still work (and are tested) without it
    shape = None

OUT_DIR = "layers"
META_PATH = os.path.join(OUT_DIR, "meta.json")
HEADERS = {"User-Agent": "spokane-in-progress (projects.spokanerising.com)"}
KEY = os.environ.get("CENSUS_API_KEY", "").strip()
STATE, COUNTY = "53", "063"

CITY = "https://services.spokanegis.org/arcgis/rest/services"
LAYERS = {
    "city": f"{CITY}/PublicData/Boundaries_WM_Dynamic/MapServer/1",
    "historic": f"{CITY}/PublicData/Economic_WM_Dynamic/MapServer/8",
    "mfte": f"{CITY}/PublicData/Economic_WM_Dynamic/MapServer/2",
    "centers": f"{CITY}/PublicData/Planning_WM_Dynamic/MapServer/13",
    "zoning": f"{CITY}/PublicData/Planning_WM_Dynamic/MapServer/33",
}
TIGER_TRACTS = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/10"
TRACT_REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_st53.txt"
OZ2_LIST = "https://www.cdfifund.gov/system/files/2026-11/final_oz2_designations.xlsx"
QCT = "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/{name}/FeatureServer/0"
HOLC = "https://dsl.richmond.edu/panorama/redlining/static/citiesData/WASpokane1938/geojson.json"
HOLC_FALLBACK = "https://services8.arcgis.com/4eSmkZn4Z1xN6dXf/ArcGIS/rest/services/mappinginequality/FeatureServer/0"

# Spokane County, with a margin, lng/lat: every layer must fall inside it.
# (Tracts that cross the city edge reach well into the county.)
AREA = (-117.90, 47.20, -116.95, 48.10)
MILE = 1609.344


# ---- fetching ---------------------------------------------------------------

def clean(text):
    text = str(text)
    return text.replace(KEY, "<key>") if KEY else text


def fetch(url, params=None, timeout=90, raw=False, tries=3):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            return body if raw else json.loads(body.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == tries - 1 or (isinstance(error, urllib.error.HTTPError) and error.code < 500):
                raise RuntimeError(clean(error)) from None
            time.sleep(3 * (attempt + 1))


def arcgis_features(layer_url, where="1=1", fields="*", page=1000):
    """Every feature of an ArcGIS layer as GeoJSON features, lng/lat."""
    features, offset = [], 0
    while True:
        payload = fetch(layer_url + "/query", {
            "where": where, "outFields": fields, "returnGeometry": "true", "outSR": "4326",
            "geometryPrecision": "6", "resultOffset": str(offset), "resultRecordCount": str(page), "f": "geojson"})
        if payload.get("error"):
            raise RuntimeError(f"{layer_url}: {payload['error']}")
        batch = payload.get("features") or []
        features.extend(batch)
        more = payload.get("exceededTransferLimit") or (payload.get("properties") or {}).get("exceededTransferLimit")
        if not batch or not (more or len(batch) == page) or offset > 100000:
            return features
        offset += len(batch)


def census(path, variables):
    params = {"get": ",".join(variables), "for": "tract:*", "in": f"state:{STATE} county:{COUNTY}"}
    if KEY:
        params["key"] = KEY
    rows = fetch(f"https://api.census.gov/data/{path}", params, timeout=120)
    header = rows[0]
    return {f"{r[header.index('state')]}{r[header.index('county')]}{r[header.index('tract')]}": dict(zip(header, r))
            for r in rows[1:]}


# ---- geometry -----------------------------------------------------------------

# A local flat projection (metres) around Spokane, plenty accurate across one
# city, for buffering and simplifying in real distances.
LAT0 = 47.66
M_PER_DEG_LAT = 111194.9
M_PER_DEG_LNG = M_PER_DEG_LAT * math.cos(math.radians(LAT0))


def to_m(x, y, z=None):
    return x * M_PER_DEG_LNG, y * M_PER_DEG_LAT


def to_deg(x, y, z=None):
    return x / M_PER_DEG_LNG, y / M_PER_DEG_LAT


def simplified(geom, metres):
    """Simplify in metres, fix any self-touching rings, back to lng/lat."""
    g = transform(to_m, geom).buffer(0)
    g = g.simplify(metres, preserve_topology=True)
    return transform(to_deg, g)


def round_coords(obj, places=5):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, places) for v in obj[:2]]
        return [round_coords(o, places) for o in obj]
    return obj


def feature(geom, props):
    g = mapping(geom)
    return {"type": "Feature", "properties": props,
            "geometry": {"type": g["type"], "coordinates": round_coords(g["coordinates"])}}


# ---- the layers ---------------------------------------------------------------

def city_limits():
    rows = arcgis_features(LAYERS["city"], where="NAME='Spokane'", fields="NAME")
    geom = unary_union([shape(f["geometry"]) for f in rows])
    return [feature(simplified(geom, 5), {"name": "City of Spokane"})], {
        "title": "City limits", "source": "City of Spokane GIS", "sourceUrl": LAYERS["city"]}


def historic_districts():
    out = []
    for f in arcgis_features(LAYERS["historic"], fields="Name,LocalRegistry"):
        p = f.get("properties") or {}
        if (p.get("LocalRegistry") or "").strip().lower() != "yes":
            continue
        out.append(feature(simplified(shape(f["geometry"]), 3), {"name": (p.get("Name") or "").strip()}))
    return sorted(out, key=lambda f: f["properties"]["name"]), {
        "title": "Local historic districts", "source": "City of Spokane GIS (Spokane Register of Historic Places)",
        "sourceUrl": LAYERS["historic"], "minFeatures": 5}


def mfte_term(duration):
    """'8, 12, & 20yr' -> ('STIA', '8, 12 or 20 years'); '12 & 20yr' -> ('AHEA', '12 or 20 years')."""
    numbers = [int(n) for n in "".join(c if c.isdigit() else " " for c in duration or "").split()]
    if not numbers:
        return None, ""
    words = ", ".join(str(n) for n in numbers[:-1]) + (" or " if len(numbers) > 1 else "") + f"{numbers[-1]} years"
    return ("STIA" if 8 in numbers else "AHEA"), words


MFTE_NAMES = {"STIA": "Spokane Targeted Investment Area", "AHEA": "Affordable Housing Emphasis Area"}


def mfte():
    out = []
    for f in arcgis_features(LAYERS["mfte"], fields="EligibleDuration,ResolutionNumber"):
        p = f.get("properties") or {}
        area, terms = mfte_term(p.get("EligibleDuration"))
        if not area:
            raise RuntimeError(f"unrecognized MFTE term {p.get('EligibleDuration')!r}")
        out.append(feature(simplified(shape(f["geometry"]), 5),
                           {"area": area, "name": MFTE_NAMES[area], "terms": terms,
                            "resolution": (p.get("ResolutionNumber") or "").strip()}))
    if sorted(f["properties"]["area"] for f in out) != ["AHEA", "STIA"]:
        raise RuntimeError(f"expected one STIA and one AHEA shape, got {[f['properties']['area'] for f in out]}")
    return sorted(out, key=lambda f: f["properties"]["area"], reverse=True), {
        "title": "MFTE target areas", "source": "City of Spokane GIS (SMC 8.15)", "sourceUrl": LAYERS["mfte"]}


def centers():
    out = []
    for f in arcgis_features(LAYERS["centers"], fields="Name,Description"):
        p = f.get("properties") or {}
        out.append(feature(simplified(shape(f["geometry"]), 5),
                           {"name": (p.get("Name") or "").strip(), "kind": (p.get("Description") or "").strip()}))
    return sorted(out, key=lambda f: (f["properties"]["kind"], f["properties"]["name"])), {
        "title": "Centers and corridors", "source": "City of Spokane GIS (Comprehensive Plan)",
        "sourceUrl": LAYERS["centers"], "minFeatures": 10}


def zoning():
    groups = {}
    for f in arcgis_features(LAYERS["zoning"], fields="ZoneCode"):
        family = site_facts.zone_group((f.get("properties") or {}).get("ZoneCode"))
        groups.setdefault(family, []).append(shape(f["geometry"]))
    out = [feature(simplified(unary_union(parts), 5), {"family": family})
           for family, parts in sorted(groups.items())]
    return out, {"title": "Zoning", "source": "City of Spokane GIS", "sourceUrl": LAYERS["zoning"], "minFeatures": 4}


# -- Census ---------------------------------------------------------------------

SENTINELS = {"-666666666", "-999999999", "-888888888", "-222222222", "-333333333", "-555555555", None, ""}


def num(row, key):
    v = row.get(key)
    if v in SENTINELS:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if v < 0 else v


def ratio(x, mx, y, my):
    """ACS proportion and its margin (Census handbook formula); None if y is 0."""
    if x is None or y in (None, 0):
        return None, None
    p = x / y
    if mx is None or my is None:
        return p, None
    radicand = mx ** 2 - (p ** 2) * (my ** 2)
    if radicand < 0:  # the handbook's fallback: use the ratio formula
        radicand = mx ** 2 + (p ** 2) * (my ** 2)
    return p, math.sqrt(radicand) / y


def summed(row, keys):
    vals = [num(row, k + "E") for k in keys]
    moes = [num(row, k + "M") for k in keys]
    if any(v is None for v in vals):
        return None, None
    return sum(vals), (math.sqrt(sum(m ** 2 for m in moes)) if all(m is not None for m in moes) else None)


def reliable(estimate, moe):
    """Coefficient of variation at or under 30% (the usual cutoff)."""
    if estimate in (None, 0) or moe is None:
        return estimate is not None and moe is None
    return (moe / 1.645) / abs(estimate) <= 0.30


ACS_VARS = ["B25003_001", "B25003_003", "B25064_001", "B19013_001", "B17001_001", "B17001_002",
            "B25035_001", "B25034_001", "B25034_011"] + [f"B25070_{i:03d}" for i in (1, 7, 8, 9, 10, 11)]


def acs_measures(row):
    """The ACS measures for one tract: {name: (estimate, moe)}."""
    e = lambda k: num(row, k + "E")  # noqa: E731
    m = lambda k: num(row, k + "M")  # noqa: E731
    out = {}
    out["renterShare"] = ratio(e("B25003_003"), m("B25003_003"), e("B25003_001"), m("B25003_001"))
    out["medianRent"] = (e("B25064_001"), m("B25064_001"))
    burdened, burdened_moe = summed(row, [f"B25070_{i:03d}" for i in (7, 8, 9, 10)])
    # Renters whose rent share can't be computed (no cash rent, no income) are left out of the base.
    base, base_moe = None, None
    if e("B25070_001") is not None and e("B25070_011") is not None:
        base = e("B25070_001") - e("B25070_011")
        if m("B25070_001") is not None and m("B25070_011") is not None:
            base_moe = math.sqrt(m("B25070_001") ** 2 + m("B25070_011") ** 2)
    out["rentBurden"] = ratio(burdened, burdened_moe, base, base_moe)
    out["medianIncome"] = (e("B19013_001"), m("B19013_001"))
    out["poverty"] = ratio(e("B17001_002"), m("B17001_002"), e("B17001_001"), m("B17001_001"))
    out["pre1940"] = ratio(e("B25034_011"), m("B25034_011"), e("B25034_001"), m("B25034_001"))
    out["medianYearBuilt"] = (e("B25035_001"), m("B25035_001"))
    return out


def pop2010_on_2020(relationship_text, pop2010):
    """2010 tract populations moved onto 2020 tracts by share of land area.

    pop2010: {geoid10: people}. Returns {geoid20: people}. Area weighting
    assumes people are spread evenly within each 2010 tract; most Spokane
    tracts were split cleanly or not at all, so the error is small, and the
    About page says so."""
    lines = [l for l in relationship_text.lstrip("﻿").splitlines() if l.strip()]
    header = lines[0].split("|")
    i20, i10 = header.index("GEOID_TRACT_20"), header.index("GEOID_TRACT_10")
    iarea10, ipart = header.index("AREALAND_TRACT_10"), header.index("AREALAND_PART")
    out = {}
    for line in lines[1:]:
        cols = line.split("|")
        g20, g10 = cols[i20], cols[i10]
        if not g10.startswith(STATE + COUNTY) or g10 not in pop2010:
            continue
        area10, part = float(cols[iarea10] or 0), float(cols[ipart] or 0)
        if area10 <= 0:
            continue
        out[g20] = out.get(g20, 0) + pop2010[g10] * part / area10
    return out


def quantile_breaks(values, classes=5):
    """Four inner breaks splitting the values into five equal-count classes."""
    vals = sorted(v for v in values if v is not None)
    if len(vals) < classes:
        return []
    breaks = []
    for k in range(1, classes):
        pos = k * (len(vals) - 1) / classes
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(vals) - 1)
        breaks.append(vals[lo] + (vals[hi] - vals[lo]) * (pos - lo))
    return breaks


MEASURES = {
    # name: (label, unit, decimals, scale)
    "renterShare": ("Homes rented, not owned", "share", 0, "sequential"),
    "medianRent": ("Median gross rent", "dollars", 0, "sequential"),
    "rentBurden": ("Renters paying 30%+ of income on rent", "share", 0, "sequential"),
    "medianIncome": ("Median household income", "dollars", 0, "sequential"),
    "poverty": ("People below the poverty line", "share", 0, "sequential"),
    "popChange": ("Population change, 2010–2020", "change", 0, "diverging"),
    "density": ("People per square mile, 2020", "count", 0, "sequential"),
    "pre1940": ("Homes built before 1940", "share", 0, "sequential"),
    "medianYearBuilt": ("Median year built", "year", 0, "sequential"),
}


def county_tracts():
    rows = arcgis_features(TIGER_TRACTS, where=f"STATE='{STATE}' AND COUNTY='{COUNTY}'",
                           fields="GEOID,NAME,AREALAND")
    if len(rows) < 100:
        raise RuntimeError(f"only {len(rows)} tracts came back")
    return {(f["properties"]["GEOID"]): f for f in rows}


def tracts():
    county = county_tracts()
    city = unary_union([shape(f["geometry"]) for f in arcgis_features(LAYERS["city"], where="NAME='Spokane'",
                                                                        fields="NAME")])
    # Tracts that really share ground with the city, not ones that only touch its edge.
    city_m = transform(to_m, city).buffer(-30)
    chosen = {g: f for g, f in county.items() if transform(to_m, shape(f["geometry"])).intersects(city_m)}

    year = None
    for y in range(date.today().year, date.today().year - 4, -1):
        try:
            acs = census(f"{y}/acs/acs5", [v + "E" for v in ACS_VARS] + [v + "M" for v in ACS_VARS])
            year = y
            break
        except RuntimeError as error:
            if "404" not in str(error):
                raise
    if not year:
        raise RuntimeError("no ACS 5-year release found")
    dec20 = census("2020/dec/pl", ["P1_001N"])
    dec10 = census("2010/dec/sf1", ["P001001"])
    pop10 = pop2010_on_2020(fetch(TRACT_REL, raw=True, timeout=120).decode("utf-8", "replace"),
                            {g: float(r["P001001"]) for g, r in dec10.items()})

    out, values = [], {k: [] for k in MEASURES}
    for geoid, f in sorted(chosen.items()):
        props = {"geoid": geoid, "name": f["properties"]["NAME"].replace("Census Tract", "Census tract")}
        m = acs_measures(acs.get(geoid, {}))
        pop20 = num(dec20.get(geoid, {}), "P1_001N")
        land_sq_mi = (f["properties"].get("AREALAND") or 0) / (MILE ** 2)
        m["density"] = ((pop20 / land_sq_mi) if pop20 is not None and land_sq_mi > 0.05 else None, None)
        before = pop10.get(geoid)
        m["popChange"] = (((pop20 - before) / before) if pop20 is not None and before and before > 50 else None, None)
        for key, (estimate, moe) in m.items():
            props[key] = None if estimate is None else round(estimate, 4)
            if moe is not None:
                props[key + "Moe"] = round(moe, 4)
            if estimate is not None and not reliable(estimate, moe):
                props.setdefault("lowReliability", []).append(key)
            values[key].append(estimate)
        out.append(feature(simplified(shape(f["geometry"]), 8), props))

    breaks = {k: [round(b, 4) for b in quantile_breaks(v)] for k, v in values.items()}
    measures = {k: {"label": label, "unit": unit, "scale": scale, "breaks": breaks[k],
                    "tracts": sum(1 for v in values[k] if v is not None)}
                for k, (label, unit, _dec, scale) in MEASURES.items()}
    return out, {"title": "Census tracts", "minFeatures": 50,
                 "source": f"U.S. Census Bureau, American Community Survey {year - 4}–{year} 5-year estimates; "
                           "2010 and 2020 Census",
                 "sourceUrl": "https://data.census.gov/", "vintage": f"ACS {year - 4}–{year}",
                 "acsYear": year, "measures": measures}


def tract_shapes_for(geoids):
    county = county_tracts()
    missing = sorted(set(geoids) - set(county))
    if missing:
        raise RuntimeError(f"tracts not found in TIGERweb: {missing}")
    return [feature(simplified(shape(county[g]["geometry"]), 8), {"geoid": g}) for g in sorted(geoids)]


def oz2_geoids(xlsx_bytes):
    import openpyxl
    book = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    found = set()
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            for cell in row:
                text = str(cell or "").strip()
                if len(text) == 11 and text.isdigit() and text.startswith(STATE + COUNTY):
                    found.add(text)
    return found


def oz2():
    geoids = oz2_geoids(fetch(OZ2_LIST, raw=True, timeout=180))
    if not geoids:
        raise RuntimeError("no Spokane County tracts in the OZ 2.0 list")
    return tract_shapes_for(geoids), {
        "title": "Opportunity Zones (from Jan. 1, 2027)", "effective": "2027-01-01",
        "source": "U.S. Treasury / CDFI Fund, Opportunity Zone 2.0 designations (Nov. 2026)",
        "sourceUrl": OZ2_LIST, "vintage": "OZ 2.0, effective Jan. 1, 2027 through Dec. 31, 2036", "minFeatures": 1}


def qct():
    """The newest year HUD has published: next year's list if it's out, else this year's."""
    this_year = date.today().year
    for year in (this_year + 1, this_year, this_year - 1):
        url = QCT.format(name=f"QUALIFIED_CENSUS_TRACTS_{year}")
        try:
            info = fetch(url, {"f": "json"})
        except RuntimeError:
            continue
        if info.get("error") or not info.get("fields"):
            continue
        rows = arcgis_features(url, where=f"STATE='{STATE}' AND COUNTY='{COUNTY}'", fields="GEOID")
        if not rows:
            continue
        out = [feature(simplified(shape(f["geometry"]), 8), {"geoid": f["properties"]["GEOID"], "year": year})
               for f in rows]
        return sorted(out, key=lambda f: f["properties"]["geoid"]), {
            "title": f"HUD Qualified Census Tracts ({year})", "year": year,
            "source": f"U.S. Department of Housing and Urban Development, {year} Qualified Census Tracts",
            "sourceUrl": url, "vintage": str(year), "minFeatures": 5}
    raise RuntimeError("no HUD QCT layer found for the last three years")


HOLC_CATEGORY = {"A": "Best", "B": "Still desirable", "C": "Declining", "D": "Hazardous"}


def holc():
    try:
        raw = fetch(HOLC)
        rows = raw.get("features") or []
        source_url = HOLC
    except RuntimeError:
        rows = arcgis_features(HOLC_FALLBACK, where="city='Spokane' AND state='WA'", fields="grade,label")
        source_url = HOLC_FALLBACK
    out = []
    for f in rows:
        p = f.get("properties") or {}
        grade = (p.get("grade") or p.get("holc_grade") or "").strip().upper()[:1]
        if grade not in HOLC_CATEGORY or not f.get("geometry"):
            continue
        out.append(feature(simplified(shape(f["geometry"]), 3), {
            "grade": grade, "label": (p.get("label") or p.get("holc_id") or "").strip(),
            "category": HOLC_CATEGORY[grade]}))
    return sorted(out, key=lambda f: (f["properties"]["grade"], f["properties"]["label"])), {
        "title": "1938 HOLC grades", "minFeatures": 30,
        "source": "Mapping Inequality, Digital Scholarship Lab, University of Richmond (CC BY-NC)",
        "sourceUrl": source_url, "vintage": "1938"}


def transit():
    """Frequent routes as lines, and the 1/4-mile area around frequent stops.

    Uses the same rule and stops as the transit filter (site_facts), so the
    shaded area matches "within 1/4 mile of frequent transit"."""
    archive, problem = None, None
    for attempt in range(3):
        try:
            request = urllib.request.Request(site_facts.GTFS_URL, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=120) as response:
                body, kind, final = response.read(), response.headers.get("Content-Type"), response.geturl()
            if not body.startswith(b"PK"):
                snippet = body[:160].decode("utf-8", "replace").replace("\n", " ")
                raise RuntimeError(f"not a zip ({kind}, {len(body)} bytes, from {final}): {snippet}")
            archive = zipfile.ZipFile(io.BytesIO(body))
            break
        except Exception as error:  # noqa: BLE001 - STA's site sometimes answers with a web page
            problem = error
            time.sleep(10 * (attempt + 1))
    if archive is None:
        # No schedule today. With no transit file yet, draw just the 1/4-mile
        # area from the stops the daily build already keeps (the same ones the
        # transit filter uses); otherwise keep last month's file, routes and all.
        stops = site_facts.load_stops()
        if os.path.exists(os.path.join(OUT_DIR, "transit.geojson")) or len(stops) < 10:
            raise RuntimeError(f"schedule download failed ({problem}); kept the last good file")
        circles = [transform(to_m, Point(s["lng"], s["lat"])).buffer(MILE / 4, quad_segs=12) for s in stops]
        area = transform(to_deg, unary_union(circles).simplify(5))
        return [feature(area, {"part": "area"})], {
            "title": "Frequent transit", "source": "Spokane Transit Authority schedule (GTFS); "
            "15-minute-or-better midday service", "sourceUrl": site_facts.GTFS_URL,
            "stops": len(stops), "routes": [], "note": f"routes not drawn: {problem}"}
    day, stops = site_facts.frequent_stops(archive)
    if len(stops) < 10:
        raise RuntimeError(f"only {len(stops)} frequent stops")
    names = {r["route_id"]: (r.get("route_short_name") or r.get("route_long_name") or r["route_id"]).strip()
             for r in site_facts._rows(archive, "routes.txt")}
    frequent = {n for s in stops for n in s["routes"]}
    _day, running = site_facts.service_day(archive, date.today())
    shape_counts = {}
    for t in site_facts._rows(archive, "trips.txt"):
        name = names.get(t["route_id"])
        if name in frequent and t.get("service_id") in running and t.get("shape_id"):
            shape_counts.setdefault((name, t.get("direction_id") or "0"), Counter())[t["shape_id"]] += 1
    wanted = {c.most_common(1)[0][0]: route for (route, _d), c in shape_counts.items()}
    points = {}
    for r in site_facts._rows(archive, "shapes.txt"):
        if r["shape_id"] in wanted:
            points.setdefault(r["shape_id"], []).append(
                (int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))
    lines = {}
    for sid, pts in points.items():
        pts.sort()
        lines.setdefault(wanted[sid], []).append(LineString([(x, y) for _s, x, y in pts]))
    out = [feature(simplified(unary_union(parts), 5), {"part": "route", "route": route})
           for route, parts in sorted(lines.items())]
    circles = [transform(to_m, Point(s["lng"], s["lat"])).buffer(MILE / 4, quad_segs=12) for s in stops]
    area = transform(to_deg, unary_union(circles).simplify(5))
    out.insert(0, feature(area, {"part": "area"}))
    return out, {"title": "Frequent transit", "minFeatures": 3,
                 "source": "Spokane Transit Authority schedule (GTFS); 15-minute-or-better midday service",
                 "sourceUrl": site_facts.GTFS_URL, "vintage": day.isoformat(), "stops": len(stops),
                 "routes": sorted(lines)}


BUILDERS = {
    "city-limits": city_limits, "historic-districts": historic_districts, "mfte": mfte, "centers": centers,
    "zoning": zoning, "tracts": tracts, "oz2": oz2, "qct": qct, "holc": holc, "transit": transit,
}


# ---- writing ------------------------------------------------------------------

def inside_area(features):
    for f in features:
        coords = f["geometry"]["coordinates"]
        flat = coords
        while flat and isinstance(flat[0], list) and flat[0] and isinstance(flat[0][0], list):
            flat = [pt for part in flat for pt in part]
        for x, y in flat:
            if not (AREA[0] <= x <= AREA[2] and AREA[1] <= y <= AREA[3]):
                return False
    return True


def write_layer(name, features, info, meta):
    if len(features) < info.pop("minFeatures", 1):
        raise RuntimeError(f"only {len(features)} features; kept the last good file")
    if not inside_area(features):
        raise RuntimeError("shapes fall outside the Spokane area; kept the last good file")
    text = json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"), sort_keys=True)
    path = os.path.join(OUT_DIR, f"{name}.geojson")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    meta[name] = {**info, "file": f"{name}.geojson", "features": len(features), "bytes": len(text),
                  "fetched": date.today().isoformat()}


def main(names):
    if shape is None:
        sys.exit("layers.py needs shapely: pip install shapely openpyxl")
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        with open(META_PATH, encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        meta = {}
    failed = []
    for name in names or BUILDERS:
        started = time.time()
        try:
            features, info = BUILDERS[name]()
            write_layer(name, features, info, meta)
            meta[name].pop("error", None)
            print(f"ok   {name}: {len(features)} features, {meta[name]['bytes'] / 1024:.0f} KB "
                  f"({time.time() - started:.0f}s)")
        except Exception as error:  # noqa: BLE001 - one layer never sinks the others
            failed.append(name)
            entry = meta.setdefault(name, {})
            entry["error"] = clean(f"{type(error).__name__}: {error}")[:400]
            entry["errorOn"] = date.today().isoformat()
            print(f"FAIL {name}: {entry['error']}")
    meta["_updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(META_PATH, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=1, sort_keys=True)
        handle.write("\n")
    # A failed layer keeps its old file, so the run still succeeds; the error
    # is in meta.json and the log. Fail the run only if nothing worked.
    return 1 if failed and len(failed) == len(names or BUILDERS) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
