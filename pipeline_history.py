"""
One row a day of how big the pipeline is: projects and homes at each stage.

Written to data/pipeline-history.csv by build.py after projects.json. A build
that runs more than once on the same day replaces that day's row, so the file
holds the day's last count. Past rows are never recomputed: this is a record
of what the map showed on each day, and it can't be back-filled later.

Columns: date (Pacific), projects, homes, projects_no_count (projects whose
home count isn't known, which add nothing to homes), then for every stage
<stage>_projects and <stage>_homes, e.g. under_construction_homes.
Standard library only.
"""

import csv
import os
import re
from datetime import datetime, timezone

PATH = os.path.join("data", "pipeline-history.csv")


def today_pacific():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # no time zone data: UTC is close enough
        return datetime.now(timezone.utc).date().isoformat()


def stage_key(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def units_of(project):
    units = project.get("units")
    return units if isinstance(units, int) and units > 0 else 0


def count(projects, stage_names):
    row = {
        "projects": len(projects),
        "homes": sum(units_of(p) for p in projects),
        "projects_no_count": sum(1 for p in projects if not units_of(p)),
    }
    for name in stage_names:
        here = [p for p in projects if p.get("status") == name]
        row[f"{stage_key(name)}_projects"] = len(here)
        row[f"{stage_key(name)}_homes"] = sum(units_of(p) for p in here)
    return row


def record(projects, stage_names, day=None, path=PATH):
    """Add (or replace) today's row. Returns the row written."""
    day = day or today_pacific()
    row = {"date": day, **count(projects, stage_names)}

    rows = []
    columns = list(row)
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            # Keep columns from earlier days (a stage that's since been renamed).
            for name in reader.fieldnames or []:
                if name not in columns:
                    columns.append(name)
            rows = [r for r in reader if r.get("date") != day]
    rows.append(row)
    rows.sort(key=lambda r: r["date"])

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return row
