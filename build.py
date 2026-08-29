#!/usr/bin/env python3
"""
Reads your Google Sheet, checks every row, and writes projects.json.

Run it with:   python3 build.py

Uses only the Python standard library. Nothing to install.
"""

import csv
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# SETTING: paste your published Google Sheet CSV link between the quotes.
# In Sheets: File > Share > Publish to web > pick the sheet > choose CSV.
# Leave it empty to build from data/projects.sample.csv instead.
# ---------------------------------------------------------------------------
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTVMhbLFK8Gl1Uc3siqKq6kim0RT8JTYTmIAR5IR3D9uJzNF3qoRLPUdhwTixHpoGLQ2cZIm3aiyg7r/pub?gid=883083305&single=true&output=csv"

# The single source of truth for stages. The website reads this list out of
# projects.json, so changing a name or colour here changes it everywhere.
STAGES = [
    {"name": "Pre-Application",    "color": "#c9a227"},  # pre-application conference held
    {"name": "Applied",            "color": "#bd7a24"},  # permit application filed
    {"name": "Approved",           "color": "#14666b"},
    {"name": "Under Construction", "color": "#a2472f"},
    {"name": "Complete",           "color": "#4a5d52"},
    {"name": "Stalled",            "color": "#868c90"},
]

STAGE_NAMES = [stage["name"] for stage in STAGES]

# Older or slightly-off spellings in the sheet get quietly corrected.
STAGE_ALIASES = {
    "exploration": "Pre-Application",
    "pre application": "Pre-Application",
    "preapplication": "Pre-Application",
    "pre-app": "Pre-Application",
    "proposed": "Pre-Application",
    "in review": "Applied",
    "application filed": "Applied",
    "under review": "Applied",
    "construction": "Under Construction",
    "completed": "Complete",
    "on hold": "Stalled",
}


def normalise_stage(value):
    """Return the canonical stage name, or None if we do not recognise it."""
    text = str(value or "").strip()
    for name in STAGE_NAMES:
        if text.lower() == name.lower():
            return name
    return STAGE_ALIASES.get(text.lower())

# Spokane city limits, roughly. Anything outside gets flagged.
BOUNDS = dict(min_lat=47.60, max_lat=47.76, min_lng=-117.58, max_lng=-117.28)

def truthy(value):
    return str(value).strip().lower() in {"true", "yes", "y", "1", "x"}


def semicolon_list(value):
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def to_int(value):
    text = str(value or "").replace(",", "").replace("$", "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Coordinates.
#
# Typing lat/lng by hand is the worst part of adding a project, so leave both
# blank and this fills them in from parcel_id. Address geocoders were tried and
# rejected: a street-centreline geocoder put "850 E Spokane Falls Blvd" 1.6km
# away on 850 W, silently. The county parcel layer is authoritative instead --
# it either finds your parcel number or tells you it did not.
#
# Anything you type by hand always wins. Results are cached in
# data/geocache.json, committed alongside projects.json, so repeat builds are
# stable and the county gets one request per new parcel.
# ---------------------------------------------------------------------------

PARCEL_SERVICE = (
    "https://gismo.spokanecounty.org/arcgis/rest/services"
    "/Assessor/Parcels/MapServer/0/query"
)
GEOCACHE_PATH = os.path.join("data", "geocache.json")


def load_geocache():
    try:
        with open(GEOCACHE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_geocache(cache):
    os.makedirs(os.path.dirname(GEOCACHE_PATH), exist_ok=True)
    with open(GEOCACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, sort_keys=True)


def ring_area(ring):
    """Signed area, computed about a local origin to avoid cancellation."""
    ox, oy = ring[0]
    total = 0.0
    for i in range(len(ring)):
        x0, y0 = ring[i - 1][0] - ox, ring[i - 1][1] - oy
        x1, y1 = ring[i][0] - ox, ring[i][1] - oy
        total += x0 * y1 - x1 * y0
    return total / 2.0


def ring_centroid(ring):
    """Area-weighted centroid, about a local origin.

    The translation is not optional. Spokane longitudes sit near -117.36 while
    a city parcel spans about 0.0003 degrees, so running this on raw
    coordinates loses the significant digits and can put the answer outside
    the parcel's own bounding box.
    """
    ox, oy = ring[0]
    area = cx = cy = 0.0
    for i in range(len(ring)):
        x0, y0 = ring[i - 1][0] - ox, ring[i - 1][1] - oy
        x1, y1 = ring[i][0] - ox, ring[i][1] - oy
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area /= 2.0
    if abs(area) < 1e-15:  # slivers, duplicate points, degenerate rings
        return (
            sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring),
        )
    return cx / (6 * area) + ox, cy / (6 * area) + oy


def point_in_ring(x, y, ring):
    inside = False
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[i - 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
    return inside


def interior_point(rings):
    """A (lat, lng) guaranteed to sit inside the parcel.

    The outer boundary is the ring with the largest area; smaller rings are
    holes or detached slivers. A centroid is normally inside it, but on a
    U- or L-shaped parcel it can land in the notch, so fall back to the middle
    of the widest interior span across the centroid's latitude.
    """
    outer = max(rings, key=lambda r: abs(ring_area(r)))
    x, y = ring_centroid(outer)
    if point_in_ring(x, y, outer):
        return y, x

    crossings = []
    for i in range(len(outer)):
        xi, yi = outer[i]
        xj, yj = outer[i - 1]
        if (yi > y) != (yj > y):
            crossings.append(xi + (y - yi) * (xj - xi) / (yj - yi))
    crossings.sort()
    if len(crossings) >= 2:
        widest = max(
            (crossings[i + 1] - crossings[i], (crossings[i] + crossings[i + 1]) / 2)
            for i in range(0, len(crossings) - 1, 2)
        )
        return y, widest[1]
    return y, x


def lookup_parcel(pin):
    """Ask the county for a parcel boundary. Returns (lat, lng, address)."""
    query = urllib.parse.urlencode(
        {
            "where": "PID_NUM='%s'" % pin.replace("'", "''"),
            "outFields": "PID_NUM,site_address",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        }
    )
    request = urllib.request.Request(
        PARCEL_SERVICE + "?" + query,
        headers={"User-Agent": "spokane-in-progress (projects.spokanerising.com)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "parcel service error"))
    features = payload.get("features") or []
    if not features:
        return None
    rings = (features[0].get("geometry") or {}).get("rings") or []
    if not rings:
        return None
    lat, lng = interior_point(rings)
    return lat, lng, (features[0].get("attributes") or {}).get("site_address", "")


def house_number(text):
    """Leading street number, for sanity-checking a parcel against an address."""
    first = str(text or "").strip().split(" ")[0]
    return first if first.isdigit() else ""


def load_rows():
    if SHEET_CSV_URL:
        print("Reading the Google Sheet...")
        try:
            with urllib.request.urlopen(SHEET_CSV_URL, timeout=30) as response:
                text = response.read().decode("utf-8")
        except Exception as error:
            sys.exit(f"The sheet did not load: {error}\nCheck that it is published to the web as CSV.")
    else:
        fallback = os.path.join("data", "projects.sample.csv")
        if not os.path.exists(fallback):
            sys.exit("No sheet link set and data/projects.sample.csv is missing.")
        print("No sheet link set yet - building from data/projects.sample.csv.")
        with open(fallback, encoding="utf-8") as handle:
            text = handle.read()

    return list(csv.DictReader(io.StringIO(text)))


def field(label, value, kind="text"):
    """Fields with no value are left out entirely, not rendered as blanks."""
    if value in (None, "", []):
        return None
    return {"label": label, "value": value, "kind": kind}


def main():
    rows = load_rows()
    warnings = []
    projects = []
    seen_ids = set()
    geocache = load_geocache()
    cache_dirty = False

    for offset, row in enumerate(rows):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        line = offset + 2
        label = row.get("name") or f"row {line}"

        if not truthy(row.get("published")):
            continue

        if not row.get("name"):
            warnings.append(f"Row {line}: no name. Skipped.")
            continue

        # Hand-typed coordinates always win. Otherwise derive them from the
        # parcel number, which is a lookup rather than a guess.
        try:
            lat = float(row.get("lat"))
            lng = float(row.get("lng"))
        except (TypeError, ValueError):
            lat = lng = None

        if lat is None:
            pin = row.get("parcel_id", "")
            if not pin:
                warnings.append(
                    f"{label}: no lat/lng, and no parcel_id to look them up with. Skipped."
                )
                continue
            if pin in geocache:
                lat = geocache[pin]["lat"]
                lng = geocache[pin]["lng"]
            else:
                try:
                    found = lookup_parcel(pin)
                except Exception as error:
                    warnings.append(
                        f'{label}: could not reach the county parcel service for '
                        f'"{pin}" ({error}). Skipped this time; it will retry next build.'
                    )
                    continue
                if not found:
                    warnings.append(
                        f'{label}: parcel "{pin}" is not in the county parcel layer. '
                        f"Check the number, or fill lat/lng in by hand. Skipped."
                    )
                    continue
                lat, lng, matched = found
                geocache[pin] = {"lat": lat, "lng": lng, "address": matched}
                cache_dirty = True
                warnings.append(
                    f'{label}: located from parcel {pin} ({matched or "no address on file"}). '
                    f"Worth a glance on the map the first time."
                )
                sheet_number = house_number(row.get("address"))
                parcel_number = house_number(matched)
                if sheet_number and parcel_number and sheet_number != parcel_number:
                    warnings.append(
                        f'{label}: the sheet says "{row.get("address")}" but parcel {pin} '
                        f'is "{matched}". One of them is wrong.'
                    )

        if not (BOUNDS["min_lat"] <= lat <= BOUNDS["max_lat"]) or not (
            BOUNDS["min_lng"] <= lng <= BOUNDS["max_lng"]
        ):
            warnings.append(f"{label}: coordinates fall outside Spokane. Check for a swapped lat/lng.")

        raw_stage = row.get("status", "")
        stage = normalise_stage(raw_stage)
        if stage is None:
            stage = "Stalled"
            warnings.append(
                f'{label}: stage "{raw_stage}" is not one of the six allowed values '
                f'({", ".join(STAGE_NAMES)}). Shown as Stalled until you fix it.'
            )
        elif stage != raw_stage:
            warnings.append(f'{label}: stage "{raw_stage}" read as "{stage}". Tidy the sheet when you get a chance.')

        project_id = row.get("id") or "".join(
            c if c.isalnum() else "-" for c in row["name"].lower()
        ).strip("-")
        if project_id in seen_ids:
            warnings.append(f'{label}: duplicate id "{project_id}".')
        seen_ids.add(project_id)

        # Images need permission on file. Documents are linked, not rehosted.
        image_ok = row.get("image_permission") in {"granted", "public-record"}
        if row.get("image_url") and not image_ok:
            warnings.append(
                f'{label}: has an image but image_permission is '
                f'"{row.get("image_permission") or "blank"}". Image left off the site.'
            )

        units = to_int(row.get("units"))
        sqft = to_int(row.get("sqft"))
        stories = to_int(row.get("stories"))
        parking = to_int(row.get("parking"))
        cost = to_int(row.get("est_cost"))

        fields = [
            f
            for f in [
                field("Stage", stage),
                field("Type", row.get("project_type")),
                field("Housing units", f"{units:,}" if units is not None else ""),
                field("Floor area", f"{sqft:,} sq ft" if sqft is not None else ""),
                field("Stories", str(stories) if stories is not None else ""),
                field("Parking stalls", f"{parking:,}" if parking is not None else ""),
                field("Estimated cost", f"${cost:,}" if cost is not None else ""),
                field("Developer", row.get("developer")),
                field("Architect", row.get("architect")),
                field("Permit application", row.get("permit_url"), kind="link"),
            ]
            if f
        ]

        projects.append(
            {
                "id": project_id,
                "name": row["name"],
                "address": row.get("address", ""),
                "neighborhood": row.get("neighborhood", ""),
                "parcelId": row.get("parcel_id", ""),
                "lat": lat,
                "lng": lng,
                "status": stage,
                "statusUpdated": row.get("status_updated", ""),
                "lastVerified": row.get("last_verified", ""),
                "projectType": row.get("project_type", ""),
                "units": units,
                "stories": stories,
                "description": row.get("description", ""),
                "permitNumbers": semicolon_list(row.get("permit_numbers")),
                "drbFile": row.get("drb_file", ""),
                "imageUrl": row.get("image_url", "") if image_ok else "",
                "imageCredit": row.get("image_credit", ""),
                "docUrl": row.get("doc_url", ""),
                "docLabel": row.get("doc_label") or "Project documents (PDF)",
                "sourceUrls": semicolon_list(row.get("source_urls")),
                "fields": fields,
            }
        )

    if cache_dirty:
        save_geocache(geocache)

    projects.sort(key=lambda p: p.get("statusUpdated") or "", reverse=True)

    # Written to the project root, not into data/, so that every deployment
    # method serves it. Some upload flows drop subfolders.
    with open("projects.json", "w", encoding="utf-8") as handle:
        json.dump(
            {
                "builtAt": datetime.now(timezone.utc).isoformat(),
                "stages": STAGES,
                "projects": projects,
            },
            handle,
            indent=2,
        )

    print(f"\nWrote projects.json with {len(projects)} projects.")
    if warnings:
        print(f"\n{len(warnings)} thing(s) to look at:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("No problems found.")


if __name__ == "__main__":
    main()
