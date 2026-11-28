"""designations.py: point-in-polygon tags from the layer files (issue #5)."""
import json, os, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import designations as dz

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1

def square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]

def fc(*features):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": props, "geometry": geom} for props, geom in features]}

def poly(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}

work = tempfile.mkdtemp()
layers = os.path.join(work, "layers")
os.makedirs(layers)
def write(name, data):
    with open(os.path.join(layers, name), "w") as h:
        json.dump(data, h)

# A district with a hole (a park), split MFTE areas that overlap, one OZ tract,
# a multipolygon QCT, and two tracts.
write("historic-districts.geojson", fc(({"name": "Browne's Addition "},
      poly(square(-117.45, 47.65, -117.43, 47.67), square(-117.445, 47.655, -117.44, 47.66)))))
write("mfte.geojson", fc(({"area": "AHEA", "name": "Affordable Housing Emphasis Area"}, poly(square(-117.6, 47.5, -117.2, 47.8))),
                         ({"area": "STIA", "name": "Spokane Targeted Investment Area"}, poly(square(-117.45, 47.65, -117.40, 47.70)))))
write("oz2.geojson", fc(({"geoid": "53063002500"}, poly(square(-117.42, 47.65, -117.40, 47.67)))))
write("qct.geojson", fc(({"geoid": "53063003500", "year": 2026}, {"type": "MultiPolygon", "coordinates": [
      [square(-117.39, 47.60, -117.38, 47.61)], [square(-117.45, 47.65, -117.44, 47.66)]]})))
write("tracts.geojson", fc(({"geoid": "53063002500", "name": "25"}, poly(square(-117.42, 47.65, -117.40, 47.67))),
                           ({"geoid": "53063003500", "name": "35"}, poly(square(-117.46, 47.64, -117.42, 47.68)))))

projects = [
    {"id": "in-district", "lat": 47.668, "lng": -117.448},     # district, STIA, QCT? no, tract 35
    {"id": "in-hole", "lat": 47.657, "lng": -117.442},         # park hole: not in district; QCT part 2
    {"id": "oz", "lat": 47.66, "lng": -117.41},                # OZ + STIA + tract 25
    {"id": "ahea-only", "lat": 47.605, "lng": -117.385},       # AHEA, QCT part 1, outside tracts file
    {"id": "outside", "lat": 47.9, "lng": -117.0},
    {"id": "no-point"},
]
warnings = dz.assign(projects, layer_dir=layers)
by = {p["id"]: p for p in projects}
check(warnings == [], warnings)
check(by["in-district"]["historicDistrict"] == "Browne's Addition", "district name, trimmed")
check(by["in-hole"]["historicDistrict"] == "", "a hole isn't inside")
check(by["in-district"]["mfteArea"] == "STIA" and by["oz"]["mfteArea"] == "STIA", "STIA wins the overlap")
check(by["ahea-only"]["mfteArea"] == "AHEA", "AHEA alone")
check(by["outside"]["mfteArea"] == "" and by["outside"]["historicDistrict"] == "", "outside everything")
check(by["oz"]["oz2"] is True and by["in-district"]["oz2"] is False, "OZ 2.0")
check(by["ahea-only"]["qct"] and by["in-hole"]["qct"] and not by["oz"]["qct"], "multipolygon QCT")
check(by["oz"]["tract"] == "53063002500" and by["in-district"]["tract"] == "53063003500", "tract GEOIDs")
check(by["ahea-only"]["tract"] == "", "outside the tracts file")
check(set(by["no-point"]) == {"id"}, "no map point, no fields")

# Missing files leave fields off; a broken file warns and leaves them off.
os.remove(os.path.join(layers, "qct.geojson"))
with open(os.path.join(layers, "oz2.geojson"), "w") as h:
    h.write("{not json")
fresh = [{"id": "x", "lat": 47.66, "lng": -117.41}]
warnings = dz.assign(fresh, layer_dir=layers)
check("qct" not in fresh[0] and "oz2" not in fresh[0], "missing/broken layers set nothing")
check(len(warnings) == 1 and "oz2.geojson" in warnings[0], warnings)
check(fresh[0]["mfteArea"] == "STIA", "other layers still apply")

# No layers folder at all (today's repo before the first monthly fetch).
empty = [{"id": "y", "lat": 47.66, "lng": -117.41}]
check(dz.assign(empty, layer_dir=os.path.join(work, "nope")) == [] and set(empty[0]) == {"id", "lat", "lng"},
      "no layers folder is fine")

print(f"{ok} checks passed")
