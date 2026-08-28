#!/usr/bin/env python3
"""
Reads your Google Sheet, checks every row, and writes data/projects.json.

Run it with:   python3 build.py

Uses only the Python standard library. Nothing to install.
"""

import csv
import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# SETTING: paste your published Google Sheet CSV link between the quotes.
# In Sheets: File > Share > Publish to web > pick the sheet > choose CSV.
# Leave it empty to build from data/projects.sample.csv instead.
# ---------------------------------------------------------------------------
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTVMhbLFK8Gl1Uc3siqKq6kim0RT8JTYTmIAR5IR3D9uJzNF3qoRLPUdhwTixHpoGLQ2cZIm3aiyg7r/pub?gid=883083305&single=true&output=csv"

# The single source of truth for stages. The website reads this list out of
# data/projects.json, so changing a name or colour here changes it everywhere.
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

    for offset, row in enumerate(rows):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        line = offset + 2
        label = row.get("name") or f"row {line}"

        if not truthy(row.get("published")):
            continue

        if not row.get("name"):
            warnings.append(f"Row {line}: no name. Skipped.")
            continue

        try:
            lat = float(row.get("lat"))
            lng = float(row.get("lng"))
        except (TypeError, ValueError):
            warnings.append(f"{label}: missing or unreadable lat/lng. Skipped.")
            continue

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

    projects.sort(key=lambda p: p.get("statusUpdated") or "", reverse=True)

    os.makedirs("data", exist_ok=True)
    with open(os.path.join("data", "projects.json"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "builtAt": datetime.now(timezone.utc).isoformat(),
                "stages": STAGES,
                "projects": projects,
            },
            handle,
            indent=2,
        )

    print(f"\nWrote data/projects.json with {len(projects)} projects.")
    if warnings:
        print(f"\n{len(warnings)} thing(s) to look at:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("No problems found.")


if __name__ == "__main__":
    main()
