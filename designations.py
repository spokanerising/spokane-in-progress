"""Which designated areas each project sits in (issue #5).

build.py runs `assign(projects)` after site_facts. It reads the layer files
that layers.py writes once a month into layers/ and checks each project's map
point against them:

  layers/historic-districts.geojson  properties: name
  layers/mfte.geojson                properties: area ("STIA" or "AHEA"), name
  layers/oz2.geojson                 properties: geoid
  layers/qct.geojson                 properties: geoid, year
  layers/tracts.geojson              properties: geoid, name, plus the Census measures

Each project gets:
  historicDistrict  e.g. "Browne's Addition" ("" when outside every district)
  mfteArea          "STIA", "AHEA" or "" (the Targeted Investment Area wins
                    where both apply, since it allows more exemption terms)
  oz2               True inside an Opportunity Zone 2.0 tract
  qct               True inside a HUD Qualified Census Tract
  tract             2020 tract GEOID, e.g. "53063002500" ("" outside the tracts file)

A missing or unreadable layer file is skipped with a warning, and the fields
it would set are left off rather than guessed, so the site shows nothing for
them instead of a wrong "no". Standard library only; plain ray casting on
lng/lat, which is accurate at the scale of a city.
"""

import json
import os

LAYER_DIR = "layers"


def _rings(geometry):
    """[(outer, [holes...]), ...] for a Polygon or MultiPolygon."""
    if not geometry:
        return []
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    polys = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
    return [(p[0], p[1:]) for p in polys if p]


def _in_ring(lng, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class Shapes:
    """Features from one GeoJSON file, with bounding boxes for a fast first check."""

    def __init__(self, features):
        self.items = []
        for f in features or []:
            parts = _rings(f.get("geometry"))
            if not parts:
                continue
            xs = [pt[0] for outer, _ in parts for pt in outer]
            ys = [pt[1] for outer, _ in parts for pt in outer]
            self.items.append(((min(xs), min(ys), max(xs), max(ys)), parts, f.get("properties") or {}))

    def __len__(self):
        return len(self.items)

    def hits(self, lat, lng):
        """Properties of every feature containing the point."""
        out = []
        for (x0, y0, x1, y1), parts, props in self.items:
            if not (x0 <= lng <= x1 and y0 <= lat <= y1):
                continue
            for outer, holes in parts:
                if _in_ring(lng, lat, outer) and not any(_in_ring(lng, lat, h) for h in holes):
                    out.append(props)
                    break
        return out


def load(name, layer_dir=LAYER_DIR):
    with open(os.path.join(layer_dir, name), encoding="utf-8") as handle:
        return Shapes(json.load(handle).get("features"))


def _point(p):
    lat, lng = p.get("lat"), p.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return lat, lng
    return None


def assign(projects, layer_dir=LAYER_DIR):
    """Sets the fields above on each project. Returns a list of warnings."""
    warnings = []
    steps = {
        "historic-districts.geojson": lambda hits: {
            "historicDistrict": (hits[0].get("name") or "").strip() if hits else ""},
        "mfte.geojson": lambda hits: {
            "mfteArea": "STIA" if any(h.get("area") == "STIA" for h in hits)
            else "AHEA" if any(h.get("area") == "AHEA" for h in hits) else ""},
        "oz2.geojson": lambda hits: {"oz2": bool(hits)},
        "qct.geojson": lambda hits: {"qct": bool(hits)},
        "tracts.geojson": lambda hits: {"tract": (hits[0].get("geoid") or "") if hits else ""},
    }
    for name, fields in steps.items():
        if not os.path.exists(os.path.join(layer_dir, name)):
            continue  # not fetched yet; the map simply doesn't offer this layer
        try:
            shapes = load(name, layer_dir)
        except (OSError, ValueError) as error:
            warnings.append(f"Designations: couldn't read {name} ({error}); left off this build.")
            continue
        for p in projects:
            point = _point(p)
            if point:
                p.update(fields(shapes.hits(*point)))
    return warnings
