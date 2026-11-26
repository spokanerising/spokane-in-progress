#!/usr/bin/env python3
"""
The city's own permit records, read fresh every build.

The City of Spokane republishes its Accela permit system nightly as a map
layer ("Permits extracted nightly from Accela"). This module:

  1. pulls every housing-relevant record from it: new commercial buildings,
     changes of use, residential duplex/townhouse/apartment permits, recent
     pre-development meetings, and every other permit on the same parcels;
  2. keeps them in data/city-records.json, so a record survives after it ages
     out of the city's rolling three-year window, and so a build still works
     on a day the city's server is down;
  3. groups records into projects and works out each project's stage, units,
     address, location and permit links.

build.py calls it. Standard library only, like build.py.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

SERVICE = (
    "https://services.spokanegis.org/arcgis/rest/services"
    "/Permit/Permit_WM_Dynamic2/MapServer/0/query"
)
CACHE_PATH = os.path.join("data", "city-records.json")
HISTORY_PATH = os.path.join("data", "project-history.json")

FIELDS = (
    "SpokanePermitID,AccelaPermitID1,AccelaPermitID2,AccelaPermitID3,PermitModule,"
    "PermitTypeAlias,Status,OpenDate,ParcelNumber,FullAddress,DetailShortNotes,NeighborhoodText"
)
ACA = (
    "https://aca.spokanepermits.org/CitizenAccess/Cap/CapDetail.aspx"
    "?Module={module}&TabName={module}&capID1={id1}&capID2={id2}&capID3={id3}"
    "&agencyCode=SPOKANE&IsToShowInspection="
)

STAGES = ["Pre-Application", "Applied", "Approved", "Under Construction", "Complete"]
PREDEV_MONTHS = 18

# ---------------------------------------------------------------------------
# What a record is
# ---------------------------------------------------------------------------

HOUSING_WORDS = re.compile(
    r"apart|multi[- ]?family|\bmf\b|town ?h|row ?house|\bplex|duplex|triplex|fourplex|four[- ]plex"
    r"|\d[- ]?plex|sixplex|eightplex|quadplex|\bunits?\b|\blofts?\b|\bflats\b|cottage|housing"
    r"|senior living|residences|dwelling|condo|haven|gardens",
    re.I,
)
NOT_HOUSING = re.compile(
    r"garage|carport|storage|restroom|shed\b|deck|clubhouse|club house|commons|leasing|office"
    r"|\bshop\b|dugout|canopy|\bsign\b|pool|gazebo|hangar|warehouse|refrigerat|fuel|playground"
    r"|retaining wall|podium permit|parking|legacy co|tenant improvement|\bti\b|school|church"
    r"|community (bldg|building|center)|maintenance|trash|enclosure|fence",
    re.I,
)
RESIDENTIAL_NEW = re.compile(
    r"new duplex|new townhouse|townhome|apartment building|house attached|zero lot"
    r"|attached adu|triplex|fourplex|four[- ]plex",
    re.I,
)
RESIDENTIAL_NOT = re.compile(r"addition|alteration|deck|garage|carport|accessory|awning|ramp|conversion of attached", re.I)
REUSE = re.compile(r"\b\d+\s+(new\s+)?(residential\s+|dwelling\s+)?units\b|apartment conversion|convert\w*\s.*(apartment|residential|units)|adaptive reuse", re.I)

TRADE_TYPES = re.compile(r"electrical|plumbing|mechanical|limited energy", re.I)

DEAD = re.compile(r"withdrawn|expired|void|cancel|denied|revoked|closed - |abandon", re.I)
FINAL = re.compile(r"^(co final|final|final inspection done|finaled|completed|closed)$", re.I)
ISSUED = re.compile(r"issued", re.I)
APPROVED = re.compile(r"plan review approved|ready to issue|approved", re.I)


def kind_of(record):
    """building | predev | trade | other"""
    t = record["type"]
    notes = record["notes"]
    if t in ("Commercial Building New", "Commercial Change of Use"):
        return "building"
    if t == "Residential Building Permit":
        if RESIDENTIAL_NEW.search(notes) and not RESIDENTIAL_NOT.search(notes):
            return "building"
        return "other"
    if t == "Commercial Building Remodel" and REUSE.search(notes):
        return "building"
    if t == "Pre-Development Conference":
        return "predev"
    if TRADE_TYPES.search(t):
        return "trade"
    return "other"


def is_housing(record, weekly_units=None):
    """A building or pre-development record that is about homes."""
    notes = record["notes"]
    if weekly_units is not None:
        return weekly_units >= 1
    if NOT_HOUSING.search(notes):
        return False
    if record["type"] == "Residential Building Permit":
        return True
    return bool(HOUSING_WORDS.search(notes))


def units_from_notes(record):
    notes = record["notes"]
    if NOT_HOUSING.search(notes):
        return None
    match = re.search(r"(\d+)[- ]?(?:unit|plex)", notes, re.I)
    if match and int(match.group(1)) < 1000:
        return int(match.group(1))
    for word, n in (("eightplex", 8), ("sixplex", 6), ("fourplex", 4), ("four-plex", 4),
                    ("quadplex", 4), ("triplex", 3), ("duplex", 2)):
        if word in notes.lower():
            return n
    if re.search(r"attached adu", notes, re.I):
        return 2
    if re.search(r"house attached|zero lot|new townhouse", notes, re.I):
        return 1
    return None


def stage_of(status):
    if DEAD.search(status):
        return None
    if FINAL.match(status.strip()):
        return "Complete"
    if ISSUED.search(status):
        return "Approved"
    if APPROVED.search(status):
        return "Approved"
    return "Applied"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _post(where, offset=0):
    body = urllib.parse.urlencode({
        "where": where, "outFields": FIELDS, "returnGeometry": "true", "outSR": "4326",
        "orderByFields": "OBJECTID", "resultOffset": str(offset),
        "resultRecordCount": "2000", "f": "json",
    }).encode()
    request = urllib.request.Request(
        SERVICE, data=body,
        headers={"User-Agent": "spokane-in-progress (projects.spokanerising.com)",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "permit layer error"))
    return payload.get("features") or []


def query(where):
    features, offset = [], 0
    while True:
        page = _post(where, offset)
        features.extend(page)
        if len(page) < 2000:
            return [normalise(f) for f in features]
        offset += 2000


def normalise(feature):
    a = feature.get("attributes") or {}
    g = feature.get("geometry") or {}
    opened = ""
    if a.get("OpenDate"):
        opened = datetime.fromtimestamp(a["OpenDate"] / 1000, tz=timezone.utc).date().isoformat()
    module = a.get("PermitModule") or "Building"
    aca = ""
    if a.get("AccelaPermitID1") and a.get("AccelaPermitID2") and a.get("AccelaPermitID3"):
        aca = ACA.format(module=module, id1=a["AccelaPermitID1"], id2=a["AccelaPermitID2"],
                         id3=a["AccelaPermitID3"])
    return {
        "id": (a.get("SpokanePermitID") or "").strip().upper(),
        "type": a.get("PermitTypeAlias") or "",
        "status": (a.get("Status") or "").strip(),
        "opened": opened,
        "parcel": (a.get("ParcelNumber") or "").strip(),
        "address": " ".join((a.get("FullAddress") or "").split()),
        "notes": " ".join((a.get("DetailShortNotes") or "").split()),
        "neighborhood": (a.get("NeighborhoodText") or "").strip(),
        "lat": g.get("y") if g.get("y") else None,
        "lng": g.get("x") if g.get("x") else None,
        "aca": aca,
    }


def _quoted(values):
    return ",".join("'%s'" % v.replace("'", "''") for v in values)


def fetch(sheet_permits, sheet_parcels, weekly_permits):
    """Pull today's records and merge them into the cache. Returns
    (records by id, list of warnings). On failure, the cache alone."""
    cache = load_json(CACHE_PATH, {"records": {}})
    records = cache.get("records", {})
    warnings = []
    try:
        since = (date.today() - timedelta(days=PREDEV_MONTHS * 31)).isoformat()
        found = []
        found += query("PermitTypeAlias IN ('Commercial Building New','Commercial Change of Use')")
        found += query(
            "PermitTypeAlias='Residential Building Permit' AND ("
            + " OR ".join(f"UPPER(DetailShortNotes) LIKE '%{w}%'" for w in
                          ["DUPLEX", "TOWNHO", "APARTMENT BUILDING", "HOUSE ATTACHED",
                           "ZERO LOT", "ATTACHED ADU", "TRIPLEX", "FOURPLEX", "TOWN HOME"])
            + ")"
        )
        found += query(
            "PermitTypeAlias='Commercial Building Remodel' AND ("
            "UPPER(DetailShortNotes) LIKE '%UNITS%' OR UPPER(DetailShortNotes) LIKE '%APARTMENT%' "
            "OR UPPER(DetailShortNotes) LIKE '%CONVER%')"
        )
        found += query(f"PermitTypeAlias='Pre-Development Conference' AND OpenDate > DATE '{since}'")
        ids = sorted(set(sheet_permits) | set(weekly_permits))
        for i in range(0, len(ids), 150):
            found += query(f"SpokanePermitID IN ({_quoted(ids[i:i + 150])})")

        # Everything else on the same parcels: trade permits (a sign that
        # building has started), SEPA, boundary adjustments, grading.
        parcels = set(sheet_parcels)
        for r in found:
            if r["parcel"] and kind_of(r) in ("building", "predev") or r["id"] in set(sheet_permits):
                parcels.add(r["parcel"])
        parcels.discard("")
        parcels = sorted(parcels)
        for i in range(0, len(parcels), 150):
            found += query(f"ParcelNumber IN ({_quoted(parcels[i:i + 150])})")

        for r in found:
            if r["id"]:
                records[r["id"]] = r
        cache = {"fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "records": records}
        save_json(CACHE_PATH, cache)
        print(f"Read {len(found)} records from the city's permit map; {len(records)} on file.")
    except Exception as error:
        warnings.append(
            f"The city's permit map didn't answer ({error}). Used the copy from "
            f"{cache.get('fetchedAt', 'the last good build')}; stages may be a day behind."
        )
    return records, warnings


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    """One record per line, so a day's changes read as a short diff."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        if isinstance(data.get("records"), dict):
            handle.write('{"fetchedAt": %s, "records": {\n' % json.dumps(data.get("fetchedAt", "")))
            items = sorted(data["records"].items())
            for i, (key, value) in enumerate(items):
                handle.write("%s: %s%s\n" % (json.dumps(key), json.dumps(value, sort_keys=True),
                                              "," if i < len(items) - 1 else ""))
            handle.write("}}\n")
        else:
            json.dump(data, handle, indent=1, sort_keys=True)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def nice_case(text):
    text = text or ""
    if text.upper() != text:
        return text
    text = text.title()
    text = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), text)
    return re.sub(r"\b(Ne|Nw|Se|Sw|Mf|Adu|Sfr|Llc|Ii|Iii)\b", lambda m: m.group(1).upper(), text)


def clean_address(text):
    if not text or re.search(r"new address|changing|parcel created|as the result|^\d{2}-\d{2}-\d{2}", text, re.I):
        return ""
    return nice_case(text)


GENERIC = re.compile(
    r"^(ot-fire-\d+\s*-?\s*)?(new\s+)?(duplex|townhouse|townhome|zero lot|residential|sfr|multi-?family)\b", re.I
)


def name_stem(notes):
    text = re.sub(r"^\s*OT-FIRE-\d+\s*-?\s*", "", notes or "")
    text = re.sub(r"\*\*.*$", "", text)
    text = re.sub(r"\s*[-,]?\s*(Bldg\.?|Building|Phase)\s*[\w&]+.*$", "", text, flags=re.I)
    text = re.sub(r"\s*-\s*(Owner ?/?Builder|Contractor|New \d+ Unit.*)$", "", text, flags=re.I)
    return text.strip(" -")


def builder_of(notes):
    match = re.search(r"-\s*([A-Z][A-Z0-9 &./]{3,})$", notes or "")
    return match.group(1).strip() if match else ""


def street_of(address):
    return re.sub(r"^\d+\s+", "", (address or "").upper()).strip()


def group_records(records):
    """Group building and pre-development records into projects: by shared
    parcel, by shared specific name, or (for generic townhouse and duplex
    permits) by same street and same builder."""
    groups = []
    for r in sorted(records, key=lambda r: (r["opened"], r["id"])):
        stem = name_stem(r["notes"]).lower()
        specific = stem and not GENERIC.match(stem) and len(stem) > 3
        loose = "" if specific else (street_of(r["address"]) + "|" + builder_of(r["notes"])
                                     if builder_of(r["notes"]) else "")
        home = None
        for g in groups:
            if (r["parcel"] and r["parcel"] in g["parcels"]) or (specific and stem in g["stems"]) or (
                loose and loose in g["loose"]
            ):
                home = g
                break
        if home is None:
            home = {"records": [], "parcels": set(), "stems": set(), "loose": set()}
            groups.append(home)
        home["records"].append(r)
        if r["parcel"]:
            home["parcels"].add(r["parcel"])
        if specific:
            home["stems"].add(stem)
        if loose:
            home["loose"].add(loose)
    return groups


def assess(group_records_, siblings, weekly):
    """Stage, units, cost and evidence for one project's records.

    group_records_: its building and pre-development records.
    siblings: every other record on its parcels (trades, SEPA, grading...).
    weekly: permit -> row from data/permit-units.csv.
    """
    buildings = [r for r in group_records_ if r["kind"] == "building" and r["housing"]]
    predevs = [r for r in group_records_ if r["kind"] == "predev"]
    live = [r for r in buildings if stage_of(r["status"]) is not None]

    evidence = []
    if live:
        stages = [stage_of(r["status"]) for r in live]
        if all(s == "Complete" for s in stages):
            stage = "Complete"
            evidence.append("every building permit is finaled")
        elif any(s in ("Complete", "Approved") for s in stages):
            first_open = min(r["opened"] for r in live)
            trades = [t for t in siblings if t["kind"] == "trade" and t["opened"] >= first_open
                      and (ISSUED.search(t["status"]) or FINAL.match(t["status"]))]
            if any(s == "Complete" for s in stages):
                stage = "Under Construction"
                evidence.append(f"{stages.count('Complete')} of {len(stages)} buildings finaled")
            elif trades:
                stage = "Under Construction"
                evidence.append(f"{len(trades)} trade permit(s) issued since the building permit")
            elif any(ISSUED.search(r["status"]) for r in live):
                stage = "Approved"
                evidence.append("building permit issued")
            else:
                stage = "Approved"
                evidence.append("plan review approved")
        else:
            stage = "Applied"
            evidence.append("in plan review")
    elif buildings:
        stage = None  # every building permit withdrawn or expired
        evidence.append("building permits withdrawn or expired")
    elif predevs:
        stage = "Pre-Application"
        evidence.append("pre-development meeting held")
    else:
        stage = None

    units, unit_sources = 0, set()
    for r in live or buildings:
        row = weekly.get(r["id"])
        n = None
        if row and str(row.get("units", "")).lstrip("-").isdigit():
            n = max(int(row["units"]), 0)
            unit_sources.add("city weekly permit report")
        else:
            n = units_from_notes(r)
            if n is not None:
                unit_sources.add("permit description")
        if n is None:
            units = None
            break
        units += n
    if not (live or buildings):
        units = None
        for r in predevs:
            n = units_from_notes(r)
            if n:
                units, unit_sources = n, {"permit description"}

    cost = 0
    for r in live or buildings:
        row = weekly.get(r["id"])
        if row and str(row.get("valuation", "")).isdigit():
            cost += int(row["valuation"])
    return stage, units or None, sorted(unit_sources), cost or None, evidence


def permit_list(records):
    order = {"building": 0, "predev": 1, "other": 2, "trade": 3}
    shown = [r for r in records if r["kind"] != "trade"]
    shown.sort(key=lambda r: (order[r["kind"]], r["opened"]))
    return [
        {"id": r["id"], "type": r["type"], "status": r["status"], "opened": r["opened"], "url": r["aca"]}
        for r in shown
    ]


def neighborhood_of(records):
    for r in records:
        if r["neighborhood"]:
            return re.sub(r"\s+Neighborhood$", "", r["neighborhood"]).replace("/", "-")
    return ""


def name_for(records, units, address):
    for r in records:
        if r["kind"] in ("building", "predev") and r.get("housing", True):
            stem = name_stem(r["notes"])
            if stem and not GENERIC.match(stem) and len(stem) > 3:
                return nice_case(stem)
    kinds = " ".join(r["notes"].lower() for r in records)
    kind = ("Duplex" if units == 2 and "duplex" in kinds else
            "Duplexes" if "duplex" in kinds else
            "Townhomes" if re.search(r"town|attached|zero lot", kinds) else "Multifamily")
    return f"{address} {kind}".strip() if address else kind


def today_iso():
    return date.today().isoformat()
