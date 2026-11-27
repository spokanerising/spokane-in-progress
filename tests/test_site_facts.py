import io, json, os, sys, tempfile, zipfile, shutil
from datetime import date
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import site_facts as sf
import boundaries as bd
import city_records as cr

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1

work = tempfile.mkdtemp()
os.chdir(work); os.makedirs("data")

# ---- area math: a 100m x 100m square near Spokane is 2.471 acres
lat0, lng0 = 47.66, -117.42
dlat = 100 / 111194.9
dlng = 100 / (111194.9 * __import__("math").cos(__import__("math").radians(lat0)))
cw = [[lng0, lat0], [lng0, lat0 + dlat], [lng0 + dlng, lat0 + dlat], [lng0 + dlng, lat0], [lng0, lat0]]  # clockwise
check(abs(sf.rings_acres([cw]) - 2.471) < 0.01, f"square acres {sf.rings_acres([cw])}")
hole = [[lng0 + dlng*0.25, lat0 + dlat*0.25], [lng0 + dlng*0.75, lat0 + dlat*0.25], [lng0 + dlng*0.75, lat0 + dlat*0.75], [lng0 + dlng*0.25, lat0 + dlat*0.75], [lng0 + dlng*0.25, lat0 + dlat*0.25]]
check(abs(sf.rings_acres([cw, hole]) - 2.471*0.75) < 0.01, "hole subtracted")

# ---- parcels from real records
records = json.load(open(f"{REPO}/data/city-records.json"))["records"]
projects = json.load(open(f"{REPO}/projects.json"))["projects"]
pins = [sf.project_parcels(p, records, cr.kind_of) for p in projects]
check(all(isinstance(x, list) for x in pins), "parcels list")
multi = [ (p["name"], x) for p, x in zip(projects, pins) if len(x) > 1]
print("projects with several parcels:", len(multi), multi[:4])
check(sum(1 for x in pins if x) >= 100, f"most projects have a parcel ({sum(1 for x in pins if x)})")

calls = []
def fake_acres(batch):
    calls.append(len(batch))
    return {pin: (0.25 if i % 7 else None) for i, pin in enumerate(batch)}
w = sf.fill_acres(projects, records, cr.kind_of, ask=fake_acres, cache={}, now=date(2026, 11, 26))
check(not w, w)
check(os.path.exists("data/parcel-acres.json"), "acres cache written")
dense = [p for p in projects if "homesPerAcre" in p]
check(dense and all(p["homesPerAcre"] == round(p["units"] / p["acres"], 1) for p in dense), "density math")
n_calls = len(calls)
cache = json.load(open("data/parcel-acres.json"))
sf.fill_acres(projects, records, cr.kind_of, ask=fake_acres, cache=cache, now=date(2026, 11, 27))
check(len(calls) == n_calls, "cache hit: no new county calls")
def boom(batch): raise OSError("down")
w = sf.fill_acres(projects, records, cr.kind_of, ask=boom, cache={}, now=date(2026, 11, 27))
check(len(w) == 1 and "didn't answer" in w[0], "fails soft")

# ---- zoning discovery with a fake server
def fake_get(url, params=None):
    if url.endswith("/query"):
        if "Zoning_WM_Dynamic/MapServer/2/" in url:
            return {"features": [{"attributes": {"ZONE_CODE": "DTC-100", "ZONE_DESC": "Downtown Core"}}]}
        return {"features": []}
    if url == sf.CITY_GIS:
        return {"folders": ["PublicData", "Locator", "Planning"], "services": []}
    if url.endswith("/Planning"):
        return {"services": [{"name": "Planning/PedestrianPlan", "type": "MapServer"}]}
    if "PedestrianPlan/MapServer/layers" in url:
        return {"layers": [{"id": 22, "name": "Neighborhood Retail Zone", "geometryType": "esriGeometryPolygon",
                            "fields": [{"name": "ZoneCode", "type": "esriFieldTypeString"}, {"name": "ZoneLabel", "type": "esriFieldTypeString"}]}]}
    if url.endswith("/PublicData"):
        return {"services": [{"name": "PublicData/Boundaries_WM_Dynamic", "type": "MapServer"},
                             {"name": "PublicData/Zoning_WM_Dynamic", "type": "MapServer"}]}
    if url.endswith("/Locator"):
        return {"services": [{"name": "Locator/AddressPoint", "type": "GeocodeServer"}]}
    if "Zoning_WM_Dynamic/MapServer/layers" in url:
        return {"layers": [
            {"id": 0, "name": "Zoning Labels", "geometryType": "esriGeometryPolygon", "fields": []},
            {"id": 1, "name": "Height Overlay Zoning", "geometryType": "esriGeometryPolygon",
             "fields": [{"name": "ZONE", "type": "esriFieldTypeString"}]},
            {"id": 2, "name": "Zoning", "geometryType": "esriGeometryPolygon",
             "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"},
                        {"name": "ZONE_CODE", "type": "esriFieldTypeString", "alias": "Zone"},
                        {"name": "ZONE_DESC", "type": "esriFieldTypeString"}]}]}
    if "Boundaries_WM_Dynamic/MapServer/layers" in url:
        return {"layers": [{"id": 4, "name": "Neighborhood Council", "geometryType": "esriGeometryPolygon",
                            "fields": [{"name": "Name", "type": "esriFieldTypeString"}]}]}
    raise AssertionError(url)
src = sf.discover_zoning(get=fake_get)
check(src and src["url"].endswith("Zoning_WM_Dynamic/MapServer/2/query") and src["field"] == "ZONE_CODE" and src["descField"] == "ZONE_DESC", src)

codes = ["RMF", "CC2-DC-70", "DTC-100", "RSF", "GC-70", "LI", "R2", "XYZ"]
asked = []
def fake_zone(source, lat, lng):
    asked.append((lat, lng))
    c = codes[len(asked) % len(codes)]
    return {"zone": c, "name": "" if c != "RMF" else "Residential Multifamily"}
w = sf.fill_zoning(projects, discover=lambda: src, ask=fake_zone, source=None, cache=None)
check(not w, w)
check(os.path.exists("data/zoning-source.json") and os.path.exists("data/zoning-cache.json"), "zoning files")
check(all(p.get("zoneGroup") for p in projects if p.get("zone")), "groups")
groups = {p["zoneBase"]: p["zoneGroup"] for p in projects if p.get("zone")}
print("zone groups:", groups)
check(groups.get("CC2") == "Centers & Corridors" and groups.get("DTC") == "Downtown" and groups.get("GC") == "Commercial & mixed use" and groups.get("R2") == "Residential" and groups.get("XYZ") == "Other" and groups.get("LI") == "Industrial", "group mapping")
first = len(asked)
sf.fill_zoning(projects, discover=lambda: src, ask=fake_zone)
check(len(asked) == first, "zoning cached")
os.remove("data/zoning-source.json"); os.remove("data/zoning-cache.json")
for p in projects:
    for k in ("zone", "zoneBase", "zoneGroup", "zoneName"): p.pop(k, None)
w = sf.fill_zoning(projects, discover=lambda: {"url": "x", "field": "f", "layer": "Wrong layer"}, ask=lambda s, a, b: {"zone": "", "name": ""})
check(w and "dropped it" in w[-1] and not os.path.exists("data/zoning-source.json"), w)

# ---- GTFS
def gtfs(freq_every_min=12, routes=("1", "25"), extra_slow=True):
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w")
    z.writestr("routes.txt", "route_id,route_short_name,route_long_name\nR1,1,City Line\nR25,25,Division\nR99,99,Slow\n")
    z.writestr("calendar.txt", "﻿service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nWK,1,1,1,1,1,0,0,20260901,20270131\nSAT,0,0,0,0,0,1,0,20260901,20270131\n")
    z.writestr("calendar_dates.txt", "service_id,date,exception_type\n")
    trips = ["route_id,service_id,trip_id,direction_id"]
    st = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type"]
    n = 0
    for rid, stop in (("R1", "A"), ("R25", "B")):
        t = 6 * 3600
        while t < 20 * 3600:
            n += 1
            trips.append(f"{rid},WK,T{n},0")
            hh = f"{t//3600:02d}:{t%3600//60:02d}:00"
            st.append(f"T{n},{hh},{hh},{stop},1,0")
            t += freq_every_min * 60
    t = 6 * 3600
    while t < 20 * 3600:  # stop C: 30-minute service only
        n += 1; trips.append(f"R99,WK,T{n},0"); hh = f"{t//3600:02d}:{t%3600//60:02d}:00"; st.append(f"T{n},{hh},{hh},C,1,0"); t += 1800
    t = 6 * 3600
    while t < 20 * 3600:  # stop D: frequent but Saturday only
        n += 1; trips.append(f"R1,SAT,T{n},0"); hh = f"{t//3600:02d}:{t%3600//60:02d}:00"; st.append(f"T{n},{hh},{hh},D,1,0"); t += 600
    z.writestr("trips.txt", "\n".join(trips) + "\n")
    z.writestr("stop_times.txt", "\n".join(st) + "\n")
    z.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\nA,Riverside & Post,47.6575,-117.4233\nB,Division & Indiana,47.6740,-117.4110\nC,Slow stop,47.70,-117.40\nD,Saturday stop,47.62,-117.40\n" +
               "".join(f"X{i},Extra {i},47.6{i},-117.3{i}\n" for i in range(10)))
    z.close()
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))
day, stops = sf.frequent_stops(gtfs(), date(2026, 11, 26))
check(day == date(2026, 12, 2) and day.weekday() == 2, day)
check({s["id"] for s in stops} == {"A", "B"}, stops)
check(stops[0]["routes"] in (["1"], ["25"]), stops)
day, stops = sf.frequent_stops(gtfs(freq_every_min=16), date(2026, 11, 26))
check(stops == [], "16-minute service isn't frequent")

# fill_transit: needs >=10 stops or it keeps last list. Make a feed with many frequent stops.
def many():
    buf = io.BytesIO(); z = zipfile.ZipFile(buf, "w")
    z.writestr("routes.txt", "route_id,route_short_name\nR1,1\n")
    z.writestr("calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nWK,1,1,1,1,1,0,0,20260901,20270131\n")
    trips = ["route_id,service_id,trip_id,direction_id"]; st = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence"]
    n = 0
    for t in range(10*3600, 14*3600, 600):
        n += 1; trips.append(f"R1,WK,T{n},0")
        for i in range(12):
            hh = f"{(t+60*i)//3600:02d}:{(t+60*i)%3600//60:02d}:00"; st.append(f"T{n},{hh},{hh},S{i},{i}")
    z.writestr("trips.txt", "\n".join(trips)+"\n"); z.writestr("stop_times.txt", "\n".join(st)+"\n")
    z.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\n" + "".join(f"S{i},Stop {i},{47.65+i*0.005},-117.42\n" for i in range(12)))
    z.close(); return zipfile.ZipFile(io.BytesIO(buf.getvalue()))
w = sf.fill_transit(projects, download=many, now=date(2026, 11, 26))
check(not w, w)
check(all("transitMiles" in p for p in projects if p.get("lat")), "every project has a distance")
p0 = projects[0]
check(p0["transitStop"].startswith("Stop") and p0["transitRoutes"] == ["1"], p0["transitStop"])
def down(): raise OSError("nope")
w = sf.fill_transit(projects, download=down, now=date(2026, 12, 20))
check(len(w) == 1 and "saved stop list" in w[0], w)

# ---- boundaries outlines
sq = [[-117.5, 47.6], [-117.5, 47.7], [-117.4, 47.7], [-117.4, 47.6], [-117.5, 47.6]]  # clockwise (outer)
inner = [[-117.48, 47.62], [-117.42, 47.62], [-117.42, 47.68], [-117.48, 47.68], [-117.48, 47.62]]
g = bd.rings_to_geometry([sq, inner])
check(g["type"] == "Polygon" and len(g["coordinates"]) == 2, g["type"])
g2 = bd.rings_to_geometry([sq, [[x + 0.2, y] for x, y in sq]])
check(g2["type"] == "MultiPolygon", g2["type"])
def fake_shapes(layer, field):
    if layer == 4: return [{"attributes": {"Name": "Riverside"}, "geometry": {"rings": [sq]}}, {"attributes": {"Name": "Logan"}, "geometry": {"rings": [sq]}}]
    return [{"attributes": {"District": 1}, "geometry": {"rings": [sq]}}]
check(bd.write_outlines(ask=fake_shapes, path="b.geojson") == [], "outlines written")
fc = json.load(open("b.geojson"))
check(len(fc["features"]) == 3 and fc["features"][0]["properties"] == {"kind": "district", "name": 1}, fc["features"][0]["properties"])
def explode(layer, field): raise OSError("down")
check(bd.write_outlines(ask=explode, path="b.geojson") == [], "fresh file not refetched")
check(len(bd.write_outlines(ask=explode, path="b.geojson", max_age_days=-1)) == 1, "fails soft")
check(json.load(open("b.geojson"))["features"], "old file kept")

shutil.rmtree(work)
print(f"{ok} checks passed")
