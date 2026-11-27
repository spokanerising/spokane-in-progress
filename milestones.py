"""Dated milestones for each project, for the timeline on its detail page.

build.py runs `add_milestones(projects, records, by_parcel, weekly, history)`
near the end. Each project gets:

  milestones        [{"date": "2026-03-31", "label": "...", "estimated": bool}, ...]
                    oldest first. Only dates the records actually hold.
  stageSinceExact   True when statusUpdated is the day a build first saw the
                    project at its stage; False when it was back-filled from a
                    permit date (every project already on the map on the first
                    run, and any project found for the first time later).

What the city's public records give, and what they don't:
  - Pre-development conference: the date it was filed.
  - Building permit: the date it was filed. The issue date only when a
    weekly permit report covered it (exact).
  - Construction: no inspections in the public records, so the first trade
    permit (electrical, plumbing, mechanical) filed after the building permit
    stands in for it, marked estimated.
  - Finaled permits carry no date in the public layer, so completion has none.
Standard library only.
"""

import re
from datetime import datetime

FINAL = re.compile(r"^(co final|final|final inspection done|finaled|completed|closed)$", re.I)
TRADE = re.compile(r"electrical|plumbing|mechanical|limited energy", re.I)
BUILDING = ("Commercial Building New", "Commercial Change of Use", "Residential Building Permit")

# The daily build started recording stage changes on this date. A "since" date
# before it was back-filled from permit dates, so it is an estimate.
HISTORY_START = "2026-11-26"

# The milestone that marks the start of each stage. Under Construction and
# Complete have none the public records can date exactly.
STAGE_EVENT = {
    "Pre-Application": "Pre-development conference filed",
    "Applied": ("Building permit filed", "First of"),
    "Approved": "Building permit issued",
}


def _iso(us_date):
    try:
        return datetime.strptime(us_date or "", "%m/%d/%Y").date().isoformat()
    except ValueError:
        return ""


def _earliest(dates):
    dates = sorted(d for d in dates if d)
    return dates[0] if dates else ""


def milestones_for(project, records, by_parcel, weekly):
    shown = {x["id"]: x for x in project.get("permits") or []}
    ids = set(shown) | set(project.get("permitNumbers") or [])
    own = [records[i] for i in ids if i in records]

    def kind(permit_id):
        r = records.get(permit_id)
        if r and r.get("kind"):
            return r["kind"]
        t = (shown.get(permit_id) or {}).get("type", "")
        if t == "Pre-Development Conference":
            return "predev"
        return "building" if t in BUILDING else "other"

    def opened(permit_id):
        return (shown.get(permit_id) or {}).get("opened") or (records.get(permit_id) or {}).get("opened", "")

    events = []

    predev = _earliest(opened(i) for i in ids if kind(i) == "predev")
    if predev:
        events.append({"date": predev, "label": "Pre-development conference filed", "estimated": False})

    buildings = [i for i in ids if kind(i) == "building"]
    filed = _earliest(opened(i) for i in buildings)
    if filed:
        n = len(buildings)
        events.append({"date": filed, "label": "Building permit filed" if n == 1 else f"First of {n} building permits filed", "estimated": False})

    issued = _earliest(_iso((weekly.get(i) or {}).get("issue_date")) for i in buildings)
    if issued:
        events.append({"date": issued, "label": "Building permit issued", "estimated": False})

    if filed:
        parcels = {r["parcel"] for r in own if r.get("parcel")}
        if project.get("parcelId"):
            parcels.add(project["parcelId"])
        trades = [r["opened"] for parcel in parcels for r in by_parcel.get(parcel, [])
                  if TRADE.search(r.get("type", "")) and r.get("opened", "") >= filed]
        first_trade = _earliest(trades)
        if first_trade:
            events.append({"date": first_trade, "label": "First trade permit filed; construction likely under way", "estimated": True})

    events.sort(key=lambda e: e["date"])
    return events


def add_milestones(projects, records, by_parcel, weekly, history):
    for p in projects:
        try:
            p["milestones"] = milestones_for(p, records, by_parcel, weekly)
        except Exception:  # never let the timeline hold up a build
            p["milestones"] = []
        entry = history.get(p.get("id")) or {}
        since = p.get("statusUpdated") or ""
        # Only the event that defines the stage can confirm its date.
        defining = STAGE_EVENT.get(p.get("status"))
        known = {e["date"] for e in p["milestones"]
                 if not e["estimated"] and defining and e["label"].startswith(defining)}
        if entry.get("exact") and entry.get("stage") == p.get("status"):
            exact = True                      # a build saw the change happen
        elif not p.get("autoAdded") and since:
            exact = True                      # typed into the sheet
        else:
            # Back-filled: right when it is the date of a real event (the
            # permit that was filed or issued), otherwise an estimate.
            exact = since in known or since > HISTORY_START
        p["stageSinceExact"] = bool(since) and exact
        # A back-filled Under Construction date is just the last permit filed,
        # which can predate the first trade permit that points to construction.
        # Use that trade permit's date instead (still an estimate).
        if p.get("status") == "Under Construction" and not p["stageSinceExact"]:
            trade = [e["date"] for e in p["milestones"] if e["label"].startswith("First trade permit")]
            if trade:
                p["statusUpdated"] = trade[0]
    return projects
