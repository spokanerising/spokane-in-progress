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
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import city_records as cr
import display_tidy

# ---------------------------------------------------------------------------
# SETTING: paste your published Google Sheet CSV link between the quotes.
# In Sheets: File > Share > Publish to web > pick the sheet > choose CSV.
# Leave it empty to build from data/projects.sample.csv instead.
# ---------------------------------------------------------------------------
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTVMhbLFK8Gl1Uc3siqKq6kim0RT8JTYTmIAR5IR3D9uJzNF3qoRLPUdhwTixHpoGLQ2cZIm3aiyg7r/pub?gid=883083305&single=true&output=csv"

# The single source of truth for stages. The website reads this list out of
# projects.json, so changing a name or colour here changes it everywhere.
STAGES = [
    {"name": "Pre-Application",    "color": "#ea957a"},  # pre-application conference held
    {"name": "Applied",            "color": "#d66a48"},  # permit application filed
    {"name": "Approved",           "color": "#b6451f"},
    {"name": "Under Construction", "color": "#8a2f10"},
    {"name": "Complete",           "color": "#592211"},
    {"name": "Stalled",            "color": "#8f8c86"},
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


PERMIT_SERVICE = (
    "https://services.spokanegis.org/arcgis/rest/services"
    "/Permit/Permit_WM_Dynamic2/MapServer/0/query"
)


def lookup_permit_point(permit):
    """Fallback when the county doesn't know a parcel (new lots, boundary
    adjustments): the city's own permit map places every permit at a point.
    Returns (lat, lng, address) or None."""
    query = urllib.parse.urlencode(
        {
            "where": "SpokanePermitID='%s'" % permit.replace("'", "''"),
            "outFields": "SpokanePermitID,FullAddress",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        }
    )
    request = urllib.request.Request(
        PERMIT_SERVICE + "?" + query,
        headers={"User-Agent": "spokane-in-progress (projects.spokanerising.com)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "permit service error"))
    for feature in payload.get("features") or []:
        point = feature.get("geometry") or {}
        if "x" in point and "y" in point and point["x"] and point["y"]:
            return point["y"], point["x"], (feature.get("attributes") or {}).get("FullAddress") or ""
    return None


def locate_by_permits(permits, geocache):
    """Try each permit number on the city's permit map. Returns
    ((lat, lng, address, permit) or None, cache_changed)."""
    for permit in permits:
        key = "permit:" + permit.upper()
        if key in geocache:
            hit = geocache[key]
            return (hit["lat"], hit["lng"], hit["address"], permit), False
        try:
            found = lookup_permit_point(permit.upper())
        except Exception:
            continue
        if found:
            lat, lng, address = found
            geocache[key] = {"lat": lat, "lng": lng, "address": address}
            return (lat, lng, address, permit), True
    return None, False


def house_number(text):
    """Leading street number, for sanity-checking a parcel against an address."""
    first = str(text or "").strip().split(" ")[0]
    return first if first.isdigit() else ""


# ---------------------------------------------------------------------------
# Unit counts and job values from the city's weekly permit reports.
#
# permit_reports.py reads those PDFs and saves data/permit-units.csv. Here,
# any project whose units or est_cost cell is blank gets them filled from the
# permits listed in its permit_numbers cell. Anything you type by hand always
# wins; if the city's number disagrees with yours, the build says so.
# ---------------------------------------------------------------------------

PERMIT_UNITS_PATH = os.path.join("data", "permit-units.csv")
NOT_ON_SITE_PATH = os.path.join("data", "housing-permits-not-on-site.csv")


def load_city_permits():
    try:
        with open(PERMIT_UNITS_PATH, encoding="utf-8", newline="") as handle:
            return {row["permit"].upper(): row for row in csv.DictReader(handle)}
    except OSError:
        return {}


def is_building_permit(permit):
    return permit.endswith("BLDC") or permit.endswith("BLDR")


def write_not_on_site(city, sheet_permits):
    """Issued permits with 2+ units that no row in the sheet mentions yet."""
    missing = [
        row for permit, row in city.items()
        if (to_int(row.get("units")) or 0) >= 2 and permit not in sheet_permits
    ]

    def when(row):
        try:
            return datetime.strptime(row.get("issue_date", ""), "%m/%d/%Y")
        except ValueError:
            return datetime.min

    missing.sort(key=when, reverse=True)
    columns = ["issue_date", "permit", "units", "valuation", "address",
               "brief_description", "detailed_description", "owner", "parcel",
               "status", "report_url"]
    os.makedirs(os.path.dirname(NOT_ON_SITE_PATH), exist_ok=True)
    with open(NOT_ON_SITE_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(missing)
    return len(missing)


# ---------------------------------------------------------------------------
# Projects published straight from the city's permit reports.
#
# Every issued permit with 2+ new units that no sheet row mentions goes on the
# site automatically. Permits are grouped into one project when they share a
# parcel or a project name ("Bethany Apartments - Bldg. A" and "- Bldg. B").
#
# To take one over: add a sheet row listing its permit number(s). Your row
#   replaces the automatic one on the next build.
# To hide one: add a sheet row with its permit number and published = FALSE.
# ---------------------------------------------------------------------------

AUTO_MIN_UNITS = 2
CITY_REPORT_URL = (
    "https://static.spokanecity.org/documents/business/statistics/"
    "daily-activity-report/{year}/{name}"
)
GENERIC_NAME = re.compile(
    r"^(new\s+)?(duplex|townhouse|townhome|sfr|triplex|fourplex|multi-?family)\b", re.I
)


def us_to_iso(us_date):
    try:
        return datetime.strptime(us_date, "%m/%d/%Y").date().isoformat()
    except (TypeError, ValueError):
        return ""


def tidy_name(brief):
    text = re.sub(r"^\s*OT-FIRE-\d+\s*-?\s*", "", brief or "")   # wildfire rebuild tag
    text = re.sub(r"\*\*.*$", "", text)                          # "** Will get new address"
    text = re.sub(r"\s*-\s*(Owner Builder|Apartment building.*)$", "", text, flags=re.I)
    return text.strip(" -")


def group_name(brief):
    """'Bethany Apartments - Bldg. A' and '... - Bldg. B' share 'bethany apartments'."""
    text = tidy_name(brief)
    text = re.sub(r"\s*[-,]?\s*(Bldg\.?|Building)\s*\S+$", "", text, flags=re.I)
    return text.lower().strip()


def tidy_description(text):
    """Keep the plain description; drop the '** All trade permits...' boilerplate."""
    text = re.sub(r"^\s*OT-FIRE-\d+\s*-?\s*", "", text or "")
    text = text.split("*")[0]
    text = re.split(r"\bAddressing\b", text, flags=re.I)[0]
    return text.strip(" -")


def nice_case(text):
    """'3215 E 27TH' -> '3215 E 27th', matching how the sheet writes addresses."""
    text = (text or "").title()
    text = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), text)
    return re.sub(r"\b(Ne|Nw|Se|Sw)\b", lambda m: m.group(1).upper(), text)


def stage_for(status):
    status = (status or "").lower()
    if status.startswith("final") or "co final" in status or status == "closed":
        return "Complete"
    return "Approved"


def city_report_url(report_file):
    name = os.path.basename(report_file or "")
    match = re.search(r"(\d{4})-\d{2}-\d{2}\.pdf$", name)
    if not match:
        return ""
    return CITY_REPORT_URL.format(year=match.group(1), name=name)


# ---------------------------------------------------------------------------
# The city's live permit records (city_records.py).
#
# Every build reads the city's permit map. For sheet rows that brings the
# stage forward (never back, never over Stalled) and lists every permit with a
# link to its record. Every other active housing project in the city's records
# is published on its own. A sheet row listing a permit takes that project
# over; a row with the permit and published = FALSE hides it.
# ---------------------------------------------------------------------------

PROCESS_TYPES = re.compile(
    r"SEPA|Boundary Line|Plat|Private Development|Grading|Design Review|Land Use|Variance"
    r"|Conditional Use|Rezone|Project Review|Unit Lot",
    re.I,
)
MULTI_SIGNAL = re.compile(
    r"apart|multi|plex|town ?h|\bunits\b|flats|lofts|cottage|housing|residences|haven|gardens|duplexes",
    re.I,
)


MONTHLY_PATH = os.path.join("data", "monthly-units.csv")


def load_monthly():
    """stem or full permit ID -> row of data/monthly-units.csv."""
    index = {}
    try:
        with open(MONTHLY_PATH, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                for permit in row["permits"].split(";"):
                    if permit:
                        index.setdefault(permit, []).append(row)
    except OSError:
        pass
    return index


def _numbers(text):
    return set(re.findall(r"\b\d{2,5}\b", text or ""))


def _words(text):
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower())
            if w not in {"apartments", "apartment", "multi", "family", "multifamily", "building",
                         "phase", "project", "townhomes", "housing", "mixed", "units", "with"}}


def monthly_match(records, monthly):
    """A unit count from the monthly report for this project, but only when
    the report's address or name agrees with the permit records too: the
    report's own tables have typos in their permit numbers."""
    found = {}
    for r in records:
        for key in (r["id"], r["id"][:8]):
            for row in monthly.get(key, []):
                found[row["key"]] = row
    best = None
    for row in found.values():
        addresses = " ".join(r["address"] for r in records)
        notes = " ".join(r["notes"] for r in records)
        if (_numbers(row["address"]) & _numbers(addresses)) or (_words(row["title"]) & _words(notes)):
            if best is None or row["as_of"] > best["as_of"]:
                best = row
    return best


def stage_rank(stage):
    return cr.STAGES.index(stage) if stage in cr.STAGES else -1


def annotate(records, weekly, monthly=None):
    for r in records.values():
        r["kind"] = cr.kind_of(r)
        r["monthly"] = bool(monthly) and r["kind"] in ("building", "predev", "other") and bool(
            monthly_match([r], monthly))
        if r["monthly"] and r["kind"] == "other" and "Change of Use" in r["type"]:
            r["kind"] = "building"
        row = weekly.get(r["id"])
        units = None
        if row and str(row.get("units", "")).lstrip("-").isdigit():
            units = int(row["units"])
            if r["kind"] == "other" and units >= 2:
                r["kind"] = "building"   # e.g. a residential permit worded unusually
        r["housing"] = r["kind"] in ("building", "predev") and (r["monthly"] or cr.is_housing(r, units))


def by_parcel_index(records):
    index = {}
    for r in records.values():
        if r["parcel"]:
            index.setdefault(r["parcel"], []).append(r)
    return index


def records_for(permits, parcels, records, by_parcel):
    """A project's own records (its permits, plus housing building and
    pre-development records on its parcels) and everything else on those
    parcels."""
    own = {p: records[p] for p in permits if p in records}
    parcels = set(parcels) | {r["parcel"] for r in own.values() if r["parcel"]}
    for parcel in parcels:
        for r in by_parcel.get(parcel, []):
            if r["housing"]:
                own.setdefault(r["id"], r)
    siblings = [r for parcel in parcels for r in by_parcel.get(parcel, []) if r["id"] not in own]
    return list(own.values()), siblings


def shown_permits(own, siblings, listed):
    shown = cr.permit_list(own + [s for s in siblings if s["kind"] == "other" and PROCESS_TYPES.search(s["type"])])
    have = {p["id"] for p in shown}
    for permit in listed:
        if permit not in have:
            shown.append({"id": permit, "type": "", "status": "", "opened": "", "url": ""})
    return shown


def main_permit_url(permits):
    for p in permits:
        if p["url"] and re.search(r"Building New|Change of Use|Residential|Remodel", p["type"]):
            return p["url"]
    for p in permits:
        if p["url"]:
            return p["url"]
    return ""


def since_for(history, pid, stage, fallback):
    """The date a project reached its stage: first seen by a build, or the
    best date the records give for projects already there on the first run."""
    entry = history.get(pid)
    if entry and entry.get("stage") == stage:
        return entry.get("since", fallback)
    since = cr.today_iso() if entry else fallback
    history[pid] = {"stage": stage, "since": since}
    return since


def city_projects(records, by_parcel, weekly, claimed_ids, claimed_parcels,
                  history, previously_shown, geocache, monthly=None, monthly_used=None):
    """Every active housing project in the city's records that no sheet row
    covers. Returns (projects, warnings, geocache_changed)."""
    warnings = []
    changed = False
    since_predev = (datetime.now(timezone.utc).date().replace(day=1).toordinal()
                    - cr.PREDEV_MONTHS * 30)

    candidates = []
    for r in records.values():
        if not r["housing"] or r["id"] in claimed_ids or r["parcel"] in claimed_parcels:
            continue
        if r["kind"] == "predev" and not r.get("monthly") and (not r["opened"] or
                                       datetime.fromisoformat(r["opened"]).toordinal() < since_predev):
            continue
        candidates.append(r)

    # Permits the weekly reports know about but the permit map is missing.
    for permit, row in weekly.items():
        if permit in records or permit in claimed_ids or row.get("parcel") in claimed_parcels:
            continue
        if (to_int(row.get("units")) or 0) < 2:
            continue
        candidates.append({
            "id": permit, "type": "Commercial Building New" if permit.endswith("BLDC") else "Residential Building Permit",
            "status": row.get("status") or "Issued", "opened": us_to_iso(row.get("issue_date")),
            "parcel": row.get("parcel", ""), "address": row.get("address", ""),
            "notes": row.get("brief_description", ""), "neighborhood": "", "lat": None, "lng": None,
            "aca": "", "kind": "building", "housing": True,
        })

    projects = []
    for group in cr.group_records(candidates):
        own = group["records"]
        siblings = [r for parcel in group["parcels"] for r in by_parcel.get(parcel, [])
                    if r["id"] not in {o["id"] for o in own}]
        stage, units, unit_sources, cost, evidence = cr.assess(own, siblings, weekly)
        if stage is None:
            continue
        row = monthly_match(own, monthly) if monthly else None
        if row and monthly_used is not None:
            monthly_used.add(row["key"])
        if units is None and row:
            if row:
                units = int(row["units"])
                unit_sources = [f"city monthly permit report (as of {row['as_of']})"]
        buildings = [r for r in own if r["kind"] == "building"]
        if units is not None and units < 2:
            continue
        if units is None and not (len(buildings) > 1 or any(MULTI_SIGNAL.search(r["notes"]) for r in own)):
            continue
        first = sorted(own, key=lambda r: (r["opened"], r["id"]))[0]
        pid = "city-" + first["id"].lower()
        shown_before = pid in history or any(r["id"] in previously_shown for r in own)
        if stage == "Complete" and not shown_before:
            continue

        lat = lng = None
        for r in sorted(own, key=lambda r: r["kind"] != "building"):
            if r["lat"] and r["lng"]:
                lat, lng = r["lat"], r["lng"]
                break
        if lat is None:
            for pin in sorted(group["parcels"]):
                if pin in geocache:
                    lat, lng = geocache[pin]["lat"], geocache[pin]["lng"]
                    break
                try:
                    found = lookup_parcel(pin)
                except Exception:
                    break
                if found:
                    lat, lng = found[0], found[1]
                    geocache[pin] = {"lat": lat, "lng": lng, "address": found[2]}
                    changed = True
                    break
        if lat is None:
            hit, hit_changed = locate_by_permits([r["id"] for r in own], geocache)
            changed = changed or hit_changed
            if hit:
                lat, lng = hit[0], hit[1]
        if lat is None:
            warnings.append(f"City: {first['notes'] or first['id']} ({first['id']}) has no map location. Skipped.")
            continue

        addresses = []
        for r in sorted(own, key=lambda r: r["kind"] != "building"):
            a = cr.clean_address(r["address"]) or cr.clean_address(weekly.get(r["id"], {}).get("address", ""))
            if a and a not in addresses:
                addresses.append(a)
        if not addresses:
            # The permit's own address field held a note; trade permits on
            # the same parcel usually carry the real one.
            for r in sorted(siblings, key=lambda r: r["opened"]):
                a = cr.clean_address(r["address"])
                if a:
                    addresses.append(a)
                    break
        address = " & ".join(addresses[:2]) + (f" and {len(addresses) - 2} more" if len(addresses) > 2 else "")
        name = cr.name_for(own, units, addresses[0] if addresses else "")
        if row and row.get("title") and len(row["title"]) > 3:
            name = row["title"]          # the city's own name for the project

        descriptions = []
        for r in buildings:
            text = tidy_description(weekly.get(r["id"], {}).get("detailed_description", ""))
            if text and text not in descriptions:
                descriptions.append(text)
        description = " / ".join(descriptions)
        stories = [int(n) for n in re.findall(r"(\d+)[- ]stor(?:y|ies)", description, re.I)]

        permits = shown_permits(own, siblings, [])
        dates = sorted(r["opened"] for r in own if r["opened"])
        issued = [us_to_iso(weekly[r["id"]].get("issue_date")) for r in own if r["id"] in weekly]
        fallback = (max(issued) if stage == "Approved" and issued else dates[-1] if dates else "")
        since = since_for(history, pid, stage, fallback)
        sources = []
        for r in own:
            url = city_report_url(weekly.get(r["id"], {}).get("report_url"))
            if url and url not in sources:
                sources.append(url)

        fields = [
            f for f in [
                field("Stage", stage),
                field("Housing units", f"{units:,}" if units else ""),
                field("Stories", str(max(stories)) if stories else ""),
                field("Estimated cost", f"${cost:,}" if cost else ""),
                field("Permit application", main_permit_url(permits), kind="link"),
                field("Source", "City of Spokane permit records"
                      + (" and weekly permit report" if sources else "")),
            ] if f
        ]
        projects.append({
            "id": pid,
            "name": name,
            "address": address,
            "neighborhood": cr.neighborhood_of(own),
            "parcelId": first.get("parcel", ""),
            "lat": lat,
            "lng": lng,
            "status": stage,
            "statusUpdated": since,
            "stageSource": "city permit records: " + "; ".join(evidence),
            "lastVerified": cr.today_iso(),
            "projectType": "Housing" if (units or 0) >= 10 else ("Middle housing" if units else ""),
            "units": units,
            "unitsSource": ", ".join(unit_sources),
            "stories": max(stories) if stories else None,
            "description": description,
            "permitNumbers": [p["id"] for p in permits],
            "permits": permits,
            "drbFile": "",
            "imageUrl": "",
            "imageCredit": "",
            "docUrl": "",
            "docLabel": "",
            "sourceUrls": sources,
            "autoAdded": True,
            "fields": fields,
        })
    return projects, warnings, changed


def address_key(text):
    """'2607 S Ray St' -> '2607 S RAY'. Empty when there's no house number."""
    match = re.match(r"^\s*(\d+)(?:-\d+)?\s+([NSEW])\.?\s+([A-Za-z0-9]+)", text or "")
    return f"{match.group(1)} {match.group(2).upper()} {match.group(3).upper()}" if match else ""


MONTHLY_STAGE = [
    (re.compile(r"pdev|mfte|future|proposed", re.I), "Pre-Application"),
    (re.compile(r"plan review", re.I), "Applied"),
    (re.compile(r"largest projects|issued", re.I), "Approved"),
]


def monthly_only_projects(monthly, used, records, projects, history):
    """Projects the monthly report lists that neither the permit map nor the
    sheet covers, placed by the city's address locator."""
    warnings, out = [], []
    rows = {}
    for entries in monthly.values():
        for row in entries:
            rows[row["key"]] = row
    shown_ids = {p for project in projects for p in project.get("permitNumbers", [])}
    taken = set()
    for project in projects:
        for part in re.split(r"\s*&\s*|\s+and\s+", project.get("address", "")):
            if address_key(part):
                taken.add(address_key(part))
    for key in used:
        if key in rows and address_key(rows[key]["address"]):
            taken.add(address_key(rows[key]["address"]))
    cutoff = (datetime.now(timezone.utc).date().toordinal() - 270)
    for key, row in sorted(rows.items(), key=lambda kv: -int(kv[1]["units"])):
        permits = row["permits"].split(";")
        if key in used or any(p in records or any(s.startswith(p) for s in shown_ids) for p in permits):
            continue
        if int(row["units"]) < 2 or not row.get("as_of"):
            continue
        if datetime.fromisoformat(row["as_of"]).toordinal() < cutoff:
            continue
        akey = address_key(row["address"])
        if not akey:
            warnings.append(f"Monthly: {row['title']} ({row['units']} units) has no street address. Not mapped.")
            continue
        if akey in taken:
            continue
        found = cr.geocode(row["address"])
        if not found:
            warnings.append(f"Monthly: couldn't place {row['title']} at \"{row['address']}\". Not mapped.")
            continue
        lat, lng, matched = found
        stage = next((st for rx, st in MONTHLY_STAGE if rx.search(row["table"])), "Applied")
        if stage == "Applied" and str(row.get("approved")).lower() == "true":
            stage = "Approved"
        units = int(row["units"])
        pid = "monthly-" + key.lower()
        since = since_for(history, pid, stage, row["as_of"])
        fields = [f for f in [
            field("Stage", stage),
            field("Housing units", f"{units:,}"),
            field("Estimated cost", f"${int(row['valuation']):,}" if str(row.get("valuation", "")).isdigit() else ""),
            field("Source", f"City of Spokane monthly permit report, as of {row['as_of']}"),
        ] if f]
        out.append({
            "id": pid, "name": row["title"], "address": cr.nice_case(matched.split(",")[0]),
            "neighborhood": "", "parcelId": "", "lat": lat, "lng": lng,
            "status": stage, "statusUpdated": since,
            "stageSource": f"city monthly permit report ({row['table']}, as of {row['as_of']})",
            "lastVerified": row["as_of"],
            "projectType": "Housing" if units >= 10 else "Middle housing",
            "units": units, "unitsSource": f"city monthly permit report (as of {row['as_of']})",
            "stories": None, "description": "",
            "permitNumbers": [p for p in permits if len(p) > 8] or permits[:1],
            "permits": [{"id": p, "type": "", "status": "", "opened": "", "url": ""}
                        for p in ([p for p in permits if len(p) > 8] or permits[:1])],
            "drbFile": "", "imageUrl": "", "imageCredit": "", "docUrl": "", "docLabel": "",
            "sourceUrls": [], "autoAdded": True, "fields": fields,
        })
        taken.add(akey)
    return out, warnings


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

    city = load_city_permits()
    if city:
        print(f"Read {len(city)} permits from the city's weekly reports.")

    # Every permit number in the sheet, published or not, and who uses it.
    permit_owners = {}
    for raw in rows:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        name = row.get("name", "")
        for permit in semicolon_list(row.get("permit_numbers")):
            permit_owners.setdefault(permit.upper(), []).append(name or "(unnamed row)")
    for permit, names in permit_owners.items():
        if len(set(names)) > 1:
            warnings.append(
                f'Permit {permit} is listed on more than one project: {", ".join(sorted(set(names)))}. '
                f"Usually a copy-paste slip."
            )

    # Today's city permit records, and what the last build published.
    sheet_rows = [{(k or "").strip(): (v or "").strip() for k, v in raw.items()} for raw in rows]
    sheet_parcels = {r.get("parcel_id") for r in sheet_rows if r.get("parcel_id")}
    monthly = load_monthly()
    records, record_warnings = cr.fetch(set(permit_owners), sheet_parcels, set(city), set(monthly))
    warnings.extend(record_warnings)
    annotate(records, city, monthly)
    by_parcel = by_parcel_index(records)
    history = cr.load_json(cr.HISTORY_PATH, {})
    monthly_used = set()
    previous = cr.load_json("projects.json", {}).get("projects", [])
    previously_shown = {p for project in previous for p in project.get("permitNumbers", [])}
    claimed_parcels = set(sheet_parcels)
    for permit in permit_owners:
        if permit in records and records[permit]["parcel"]:
            claimed_parcels.add(records[permit]["parcel"])

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
            permits = semicolon_list(row.get("permit_numbers"))
            if not pin and not permits:
                warnings.append(
                    f"{label}: no lat/lng, and no parcel_id or permit number to look them up with. Skipped."
                )
                continue
            if not pin:
                hit, cache_hit = locate_by_permits(permits, geocache)
                cache_dirty = cache_dirty or cache_hit
                if not hit:
                    warnings.append(
                        f"{label}: no parcel_id, and the city's permit map doesn't have "
                        f"{', '.join(permits)}. Fill lat/lng in by hand. Skipped."
                    )
                    continue
                lat, lng = hit[0], hit[1]
            elif pin in geocache:
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
                    # New lots and boundary adjustments can be missing from the
                    # county layer; the city's permit map still places the permit.
                    hit, cache_hit = locate_by_permits(permits, geocache)
                    if not hit:
                        on_parcel = [r for r in by_parcel.get(pin, []) if r["lat"] and r["lng"]]
                        if on_parcel:
                            hit = (on_parcel[0]["lat"], on_parcel[0]["lng"], on_parcel[0]["address"],
                                   on_parcel[0]["id"])
                    cache_dirty = cache_dirty or cache_hit
                    if not hit:
                        warnings.append(
                            f'{label}: parcel "{pin}" is not in the county parcel layer, and the '
                            f"city's permit map doesn't have its permit numbers either. "
                            f"Check the number, or fill lat/lng in by hand. Skipped."
                        )
                        continue
                    found = (hit[0], hit[1], hit[2])
                    warnings.append(
                        f'{label}: parcel "{pin}" isn\'t in the county parcel layer (often a new or '
                        f"adjusted lot), so it was placed from permit {hit[3]} on the city's permit map."
                    )
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

        listed = [p.upper() for p in semicolon_list(row.get("permit_numbers"))]
        own, siblings = records_for(listed, [row.get("parcel_id")] if row.get("parcel_id") else [],
                                    records, by_parcel)
        city_stage, _, _, _, evidence = cr.assess(own, siblings, city) if own else (None, 0, 0, 0, [])
        stage_source = "sheet"
        if city_stage and stage != "Stalled" and stage_rank(city_stage) > stage_rank(stage):
            warnings.append(
                f"{label}: stage moved from {stage} to {city_stage} by the city's permit records "
                f"({'; '.join(evidence)}). Update the sheet to match when you can."
            )
            stage = city_stage
            stage_source = "city permit records: " + "; ".join(evidence)
        permits_shown = shown_permits(own, siblings, listed)
        matched_m = monthly_match(own, monthly) if own else None
        if matched_m:
            monthly_used.add(matched_m["key"])

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

        # Fill blanks from the city's weekly permit reports.
        units_source = "sheet" if units is not None else ""
        listed = [p.upper() for p in semicolon_list(row.get("permit_numbers"))]
        found = [city[p] for p in listed if p in city]
        if found:
            # New units only: a demolition on the same project reports -1.
            city_units = sum(max(to_int(r.get("units")) or 0, 0) for r in found)
            city_cost = sum(
                to_int(r.get("valuation")) or 0
                for r in found if is_building_permit(r["permit"].upper())
            )
            pending = [
                p for p in listed if is_building_permit(p) and p not in city
            ]
            partial = (
                f" Building permit(s) {', '.join(pending)} not issued yet, "
                f"so this may grow." if pending else ""
            )
            if units is None and city_units:
                units = city_units
                units_source = "city permit report"
                warnings.append(
                    f"{label}: housing units set to {units:,} from the city's permit reports.{partial}"
                )
            elif units is not None and city_units and units != city_units:
                warnings.append(
                    f"{label}: the sheet says {units:,} units; the city's permit reports add up "
                    f"to {city_units:,} for {', '.join(r['permit'] for r in found)}.{partial} "
                    f"Kept the sheet's number."
                )
            if cost is None and city_cost:
                cost = city_cost
                warnings.append(
                    f"{label}: estimated cost set to ${cost:,} from the city's permit reports.{partial}"
                )

        if units is None and own:
            row_m = monthly_match(own, monthly)
            if row_m:
                units = int(row_m["units"])
                units_source = f"city monthly permit report (as of {row_m['as_of']})"
                warnings.append(f"{label}: housing units set to {units:,} from the city's monthly "
                                f"permit report ({row_m['title']}, as of {row_m['as_of']}).")

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
                field("Permit application", row.get("permit_url") or main_permit_url(permits_shown), kind="link"),
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
                "statusUpdated": (since_for(history, project_id, stage, row.get("status_updated", ""))
                                  if stage_source != "sheet" else row.get("status_updated", "")),
                "stageSource": stage_source,
                "lastVerified": row.get("last_verified", ""),
                "projectType": row.get("project_type", ""),
                "units": units,
                "unitsSource": units_source,
                "stories": stories,
                "description": row.get("description", ""),
                "permitNumbers": [p["id"] for p in permits_shown],
                "permits": permits_shown,
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

    if city:
        write_not_on_site(city, set(permit_owners))
    auto, auto_warnings, auto_cache = city_projects(
        records, by_parcel, city, set(permit_owners), claimed_parcels, history,
        previously_shown, geocache, monthly, monthly_used,
    )
    warnings.extend(auto_warnings)
    if auto_cache:
        save_geocache(geocache)
    taken = {p["id"] for p in projects}
    auto = [p for p in auto if p["id"] not in taken]
    projects.extend(auto)
    extra, extra_warnings = monthly_only_projects(monthly, monthly_used, records, projects, history)
    warnings.extend(extra_warnings)
    projects.extend(extra)
    if extra:
        print(f"Published {len(extra)} project(s) known only from the city's monthly report.")
    cr.save_json(cr.HISTORY_PATH, history)
    if auto:
        counts = {}
        for p in auto:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        print(f"Published {len(auto)} project(s) from the city's permit records: "
              + ", ".join(f"{n} {s}" for s, n in counts.items()))

    # Last pass: tidy raw city text (abbreviations, shouting, stray notes in
    # addresses). Sheet-typed names and descriptions are left alone.
    display_tidy.polish(projects)

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
