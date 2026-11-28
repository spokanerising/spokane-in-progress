"""One-off discovery for the map layers (issue #5).

Runs on the GitHub runner (Claude's sandbox can't reach these servers) and
writes what it finds to data/layers-discovery.json, which the workflow commits
back to the branch. Nothing here ships to the site; this file and its workflow
are deleted before the layers PR merges.

What it looks for:
  * the city's GIS catalog: every layer whose name suggests historic
    districts, MFTE / targeted investment areas, centers and corridors,
    city limits, or zoning, with fields, feature counts and sample values
  * ArcGIS Online items for the same, in case the city hosts them there
  * how big the zoning layer is once simplified
  * the Census API with the CENSUS_API_KEY secret: newest ACS 5-year year,
    every variable the layers need, 2020 and 2010 population
  * tract shapes (TIGERweb) and the 2010 -> 2020 tract relationship file
  * the OZ 2.0 designation list (CDFI Fund), HUD's QCTs, and the 1938 HOLC
    polygons for Spokane

The API key is never written to the output or the log.
"""

import gzip
import io
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

HEADERS = {"User-Agent": "spokane-in-progress (projects.spokanerising.com)"}
KEY = os.environ.get("CENSUS_API_KEY", "").strip()
OUT = os.path.join("data", "layers-discovery.json")

# Around the city, in lng/lat, for spatial queries.
SPOKANE_BOX = (-117.58, 47.57, -117.28, 47.76)
STATE, COUNTY = "53", "063"

CITY_ROOT = "https://services.spokanegis.org/arcgis/rest/services"
INTERESTING = re.compile(
    r"histor|landmark|register|preserv|mfte|tax\s*exempt|exemption|target|incentive|invest|"
    r"emphasis|stia|ahea|nmtc|opportunit|center|corridor|comp(rehensive)?\s*plan|land\s*use|"
    r"city\s*limit|municipal|zoning|qct|census|tract|redlin|holc",
    re.I,
)


def clean(text):
    """Strip the API key out of anything that might be logged."""
    text = str(text)
    if KEY:
        text = text.replace(KEY, "<key>")
    return text


def fetch(url, params=None, timeout=60, raw=False):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    if raw:
        return body
    return json.loads(body.decode("utf-8"))


def attempt(label, fn, *args, **kwargs):
    started = time.time()
    try:
        value = fn(*args, **kwargs)
        print(f"ok   {label} ({time.time() - started:.1f}s)")
        return value
    except Exception as e:  # noqa: BLE001 - discovery records every failure
        print(f"FAIL {label}: {clean(e)}")
        return {"error": clean(f"{type(e).__name__}: {e}"), "trace": clean(traceback.format_exc(limit=2))}


# ---- city GIS ---------------------------------------------------------------

def service_list(root):
    top = fetch(root, {"f": "json"})
    services = list(top.get("services") or [])
    for folder in top.get("folders") or []:
        try:
            sub = fetch(f"{root}/{folder}", {"f": "json"})
            services.extend(sub.get("services") or [])
        except Exception as e:  # noqa: BLE001
            print(f"  folder {folder}: {e}")
    return [s for s in services if s.get("type") in ("MapServer", "FeatureServer")]


def layer_detail(url):
    info = fetch(url, {"f": "json"})
    detail = {
        "url": url,
        "name": info.get("name"),
        "geometryType": info.get("geometryType"),
        "fields": [f.get("name") for f in info.get("fields") or []],
        "maxRecordCount": info.get("maxRecordCount"),
        "description": (info.get("description") or "")[:300],
        "copyright": (info.get("copyrightText") or "")[:200],
    }
    if info.get("type") in ("Feature Layer", None) and info.get("geometryType"):
        try:
            detail["count"] = fetch(url + "/query", {"where": "1=1", "returnCountOnly": "true", "f": "json"}).get("count")
        except Exception as e:  # noqa: BLE001
            detail["count"] = f"error: {e}"
        try:
            sample = fetch(url + "/query", {"where": "1=1", "outFields": "*", "returnGeometry": "false",
                                            "resultRecordCount": "60", "f": "json"})
            rows = [f.get("attributes") or {} for f in sample.get("features") or []]
            values = {}
            for row in rows:
                for k, v in row.items():
                    if isinstance(v, str) and v.strip():
                        values.setdefault(k, set()).add(v.strip()[:80])
            detail["sampleValues"] = {k: sorted(v)[:25] for k, v in values.items() if len(v) <= 60}
        except Exception as e:  # noqa: BLE001
            detail["sampleValues"] = f"error: {e}"
    return detail


def city_catalog():
    found = {"allLayers": [], "matches": []}
    for service in service_list(CITY_ROOT):
        name, kind = service["name"], service["type"]
        url = f"{CITY_ROOT}/{name}/{kind}"
        try:
            info = fetch(url, {"f": "json"})
        except Exception as e:  # noqa: BLE001
            found["allLayers"].append({"service": name, "error": str(e)})
            continue
        for layer in (info.get("layers") or []) + (info.get("tables") or []):
            entry = {"service": f"{name}/{kind}", "id": layer.get("id"), "name": layer.get("name"),
                     "geometryType": layer.get("geometryType")}
            found["allLayers"].append(entry)
            if INTERESTING.search(f"{layer.get('name', '')}") and layer.get("subLayerIds") is None:
                try:
                    entry_detail = layer_detail(f"{url}/{layer['id']}")
                except Exception as e:  # noqa: BLE001
                    entry_detail = {"error": str(e)}
                found["matches"].append({**entry, **entry_detail})
    return found


def agol_search():
    out = {}
    for q in ("Spokane historic district", "Spokane local historic district", "Spokane MFTE",
              "Spokane multi-family tax exemption", "Spokane targeted investment area",
              "Spokane affordable housing emphasis area", "Spokane centers and corridors",
              "Spokane city limits"):
        try:
            hits = fetch("https://www.arcgis.com/sharing/rest/search",
                         {"q": q, "f": "json", "num": "15", "sortField": "modified", "sortOrder": "desc"})
            out[q] = [{"title": r.get("title"), "type": r.get("type"), "owner": r.get("owner"),
                       "url": r.get("url"), "id": r.get("id"),
                       "modified": r.get("modified")} for r in hits.get("results") or []]
        except Exception as e:  # noqa: BLE001
            out[q] = f"error: {e}"
    return out


def zoning_size():
    url = f"{CITY_ROOT}/PublicData/Planning_WM_Dynamic/MapServer/33/query"
    count = fetch(url, {"where": "1=1", "returnCountOnly": "true", "f": "json"}).get("count")
    features, offset, codes = [], 0, {}
    while True:
        page = fetch(url, {"where": "1=1", "outFields": "ZoneCode", "returnGeometry": "true", "outSR": "4326",
                           "geometryPrecision": "6", "maxAllowableOffset": "0.00003",
                           "resultOffset": str(offset), "resultRecordCount": "1000", "f": "geojson"}, timeout=120)
        batch = page.get("features") or []
        features.extend(batch)
        for f in batch:
            code = (f.get("properties") or {}).get("ZoneCode")
            codes[code] = codes.get(code, 0) + 1
        more = page.get("exceededTransferLimit") or (page.get("properties") or {}).get("exceededTransferLimit")
        if not batch or not (more or len(batch) == 1000) or offset > 50000:
            break
        offset += len(batch)
    text = json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    vertices = sum(len(ring) for f in features for poly in _polys(f.get("geometry")) for ring in poly)
    return {"count": count, "fetched": len(features), "bytes": len(text),
            "gzipBytes": len(gzip.compress(text.encode())), "vertices": vertices, "codes": codes}


def _polys(geometry):
    if not geometry:
        return []
    if geometry.get("type") == "Polygon":
        return [geometry["coordinates"]]
    if geometry.get("type") == "MultiPolygon":
        return geometry["coordinates"]
    return []


# ---- Census -----------------------------------------------------------------

ACS_VARS = (
    ["B25003_001E", "B25003_002E", "B25003_003E", "B25064_001E", "B19013_001E", "B17001_001E", "B17001_002E",
     "B25035_001E", "B25034_001E", "B25034_010E", "B25034_011E"]
    + [f"B25070_{i:03d}E" for i in (1, 7, 8, 9, 10, 11)]
)


def census(path, get, geo="tract:*"):
    params = {"get": ",".join(get), "for": geo, "in": f"state:{STATE} county:{COUNTY}"}
    if KEY:
        params["key"] = KEY
    try:
        rows = fetch(f"https://api.census.gov/data/{path}", params, timeout=90)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code}: {clean(body)}") from None
    return rows


def census_checks():
    out = {"keyPresent": bool(KEY)}
    latest = None
    for year in range(2026, 2019, -1):
        try:
            rows = census(f"{year}/acs/acs5", ["NAME", "B25003_001E"])
            latest = year
            out["acsLatestYear"] = year
            out["acsTracts"] = len(rows) - 1
            break
        except Exception as e:  # noqa: BLE001
            out.setdefault("acsYearsTried", {})[year] = clean(e)[:160]
    if latest:
        moe = [v[:-1] + "M" for v in ACS_VARS]
        rows = census(f"{latest}/acs/acs5", ACS_VARS + moe)
        header, data = rows[0], rows[1:]
        out["acsColumns"] = header
        out["acsSample"] = data[:3]
        out["acsNullCounts"] = {h: sum(1 for r in data if r[i] in (None, "", "-666666666", "-999999999",
                                                                    "-888888888", "-222222222"))
                                for i, h in enumerate(header) if h.endswith("E")}
    rows = census("2020/dec/pl", ["P1_001N"])
    out["dec2020Tracts"] = len(rows) - 1
    out["dec2020Sample"] = rows[1:3]
    try:
        rows = census("2010/dec/sf1", ["P001001"])
        out["dec2010Tracts"] = len(rows) - 1
    except Exception as e:  # noqa: BLE001
        out["dec2010"] = clean(e)
    return out


def tract_shapes():
    out = {}
    root = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
    listing = fetch(root, {"f": "json"})
    out["services"] = [s.get("name") for s in listing.get("services") or []]
    for svc in ("TIGERweb/Tracts_Blocks", "TIGERweb/tigerWMS_Census2020"):
        try:
            info = fetch(f"https://tigerweb.geo.census.gov/arcgis/rest/services/{svc}/MapServer", {"f": "json"})
            layers = [{"id": l.get("id"), "name": l.get("name")} for l in info.get("layers") or []]
            out[svc] = layers
            tract_layer = next((l for l in layers if re.fullmatch(r"(2020 )?Census Tracts", l["name"] or "")), None)
            if tract_layer:
                url = f"https://tigerweb.geo.census.gov/arcgis/rest/services/{svc}/MapServer/{tract_layer['id']}"
                fields = [f.get("name") for f in fetch(url, {"f": "json"}).get("fields") or []]
                page = fetch(url + "/query", {"where": f"STATE='{STATE}' AND COUNTY='{COUNTY}'", "outFields": "GEOID,NAME,AREALAND",
                                              "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "6",
                                              "maxAllowableOffset": "0.00003", "f": "geojson"}, timeout=120)
                text = json.dumps(page, separators=(",", ":"))
                out[svc + " tracts"] = {"layer": tract_layer, "fields": fields, "features": len(page.get("features") or []),
                                         "bytes": len(text), "gzipBytes": len(gzip.compress(text.encode())),
                                         "sampleProps": [f.get("properties") for f in (page.get("features") or [])[:3]]}
        except Exception as e:  # noqa: BLE001
            out[svc] = f"error: {e}"
    rel = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_st53.txt"
    try:
        body = fetch(rel, raw=True, timeout=90).decode("utf-8", "replace")
        lines = body.splitlines()
        out["relationship"] = {"url": rel, "lines": len(lines), "header": lines[0][:400],
                               "spokaneRows": sum(1 for l in lines if f"|{STATE}{COUNTY}" in l)}
    except Exception as e:  # noqa: BLE001
        out["relationship"] = f"error: {e}"
    return out


# ---- designations -----------------------------------------------------------

def oz2():
    import openpyxl
    url = "https://www.cdfifund.gov/system/files/2026-11/final_oz2_designations.xlsx"
    body = fetch(url, raw=True, timeout=120)
    book = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    out = {"url": url, "bytes": len(body), "sheets": book.sheetnames}
    for sheet in book.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        out[sheet.title] = {"rows": len(rows), "top": [[str(c) for c in r] for r in rows[:6]]}
        hits = [[str(c) for c in r] for r in rows if any(str(c or "").startswith(STATE + COUNTY) for c in r)]
        out[sheet.title]["spokaneCounty"] = hits
    return out


def envelope_query(url, extra=None):
    params = {"geometry": ",".join(map(str, SPOKANE_BOX)), "geometryType": "esriGeometryEnvelope", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false", "f": "json"}
    params.update(extra or {})
    payload = fetch(url + "/query", params, timeout=90)
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return [f.get("attributes") for f in payload.get("features") or []]


def qct():
    out = {}
    for name in ("QUALIFIED_CENSUS_TRACTS_2027", "QUALIFIED_CENSUS_TRACTS_2026", "QUALIFIED_CENSUS_TRACTS"):
        url = f"https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/{name}/FeatureServer/0"
        try:
            info = fetch(url, {"f": "json"})
            if info.get("error"):
                out[name] = info["error"]
                continue
            out[name] = {"description": (info.get("description") or "")[:300],
                         "fields": [f.get("name") for f in info.get("fields") or []],
                         "spokane": envelope_query(url)}
        except Exception as e:  # noqa: BLE001
            out[name] = f"error: {e}"
    return out


def holc():
    out = {}
    for label, url in (
        ("mappinginequality", "https://services8.arcgis.com/4eSmkZn4Z1xN6dXf/ArcGIS/rest/services/mappinginequality/FeatureServer/0"),
        ("wa-doh", "https://services8.arcgis.com/rGGrs6HCnw87OFOT/ArcGIS/rest/services/HistoricalRedliningHOLC/FeatureServer"),
    ):
        try:
            info = fetch(url, {"f": "json"})
            if "layers" in info:
                out[label] = {"layers": [{"id": l.get("id"), "name": l.get("name")} for l in info["layers"]]}
                if info["layers"]:
                    url = f"{url}/{info['layers'][0]['id']}"
                    info = fetch(url, {"f": "json"})
            attrs = envelope_query(url)
            out.setdefault(label, {}).update({
                "url": url, "fields": [f.get("name") for f in info.get("fields") or []],
                "copyright": (info.get("copyrightText") or "")[:200], "features": len(attrs), "sample": attrs[:4]})
        except Exception as e:  # noqa: BLE001
            out[label] = f"error: {e}"
    for url in ("https://dsl.richmond.edu/panorama/redlining/static/citiesData/WASpokane1938/geojson.json",
                "https://dsl.richmond.edu/panorama/redlining/static/mappinginequality.json"):
        try:
            request = urllib.request.Request(url, headers=HEADERS, method="HEAD")
            with urllib.request.urlopen(request, timeout=30) as r:
                out[url] = {"status": r.status, "length": r.headers.get("Content-Length"),
                            "type": r.headers.get("Content-Type")}
        except Exception as e:  # noqa: BLE001
            out[url] = f"error: {e}"
    return out


def main():
    results = {"ranAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    results["city"] = attempt("city GIS catalog", city_catalog)
    results["arcgisOnline"] = attempt("ArcGIS Online search", agol_search)
    results["zoning"] = attempt("zoning size", zoning_size)
    results["census"] = attempt("Census API", census_checks)
    results["tracts"] = attempt("tract shapes", tract_shapes)
    results["oz2"] = attempt("OZ 2.0 list", oz2)
    results["qct"] = attempt("HUD QCTs", qct)
    results["holc"] = attempt("HOLC 1938", holc)
    os.makedirs("data", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(clean(json.dumps(results, indent=1, sort_keys=True, default=sorted)))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
