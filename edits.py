"""Your edits, applied on top of everything else the build knows.

The build rebuilds projects.json from scratch every day, so an edit made
directly to projects.json would be gone the next morning. Instead every Save
on the site writes one small file to data/edits/, and build.py calls apply()
after the hand-curated projects and the city's records are assembled.

An edit file:

  {
    "project": "city-b2404005bldc",      the project's id
    "permits": ["B2404005BLDC"],          backup, in case the id changes
    "at": "2026-11-27T09:12:44Z",         when it was made
    "by": "spokanerising@gmail.com",
    "set":   {"units": 48, "status": "Approved"},
    "was":   {"units": 44, "status": "Applied"},   for the history; not used here
    "unset": [],                          back to the automatic value
    "note":  "Confirmed with the developer"
  }

Rules:
- Files are applied oldest first; for each field the latest edit wins.
- Edits are permanent: nothing the build finds later overrides them, with one
  exception. The city's records can still move a stage FORWARD from the one
  you set (never back, and never off Stalled). That's the same rule the
  hand-curated projects have always had.
- "unset" drops your edit for a field, so it goes back to the automatic value.
- "hidden": true takes the project off the site; "hidden": false (or unset)
  puts it back.
- A blank value ("" or null) means "show nothing", even if the city has one.
- If the id no longer exists (a project's id comes from its earliest permit,
  and grouping can change), the edit finds the project by permit number. If
  nothing matches, it's listed in the build's warnings rather than dropped
  silently.
"""
import glob
import json
import os

EDITS_DIR = os.path.join("data", "edits")

# Field name in an edit -> how to read it.
KINDS = {
    "name": "text", "address": "text", "description": "text",
    "projectType": "text", "developer": "text", "architect": "text",
    "imageCredit": "text", "docLabel": "text",
    "statusUpdated": "date", "lastVerified": "date",
    "status": "stage",
    "units": "int", "stories": "int", "sqft": "int", "parking": "int", "estCost": "int",
    "permitUrl": "text", "imageUrl": "text", "docUrl": "text",
    "sourceUrls": "list",
    "lat": "float", "lng": "float",
    "imagePermission": "permission",
    "hidden": "bool",
}

# Fields that also appear in the detail list on the project page, in its order.
DETAIL = [
    ("status", "Stage", "text", lambda v: v),
    ("projectType", "Type", "text", lambda v: v),
    ("units", "Housing units", "text", lambda v: f"{v:,}"),
    ("sqft", "Floor area", "text", lambda v: f"{v:,} sq ft"),
    ("stories", "Stories", "text", lambda v: str(v)),
    ("parking", "Parking stalls", "text", lambda v: f"{v:,}"),
    ("estCost", "Estimated cost", "text", lambda v: f"${v:,}"),
    ("developer", "Developer", "text", lambda v: v),
    ("architect", "Architect", "text", lambda v: v),
    ("permitUrl", "Permit application", "link", lambda v: v),
]
DETAIL_ORDER = [label for _, label, _, _ in DETAIL] + ["Source"]

# Same rule as image_permission in the sheet: only these show the picture.
PERMISSION_OK = {"granted", "public-record"}
PERMISSIONS = PERMISSION_OK | {"not-sure", ""}

# Spokane, roughly (as in build.py).
BOUNDS = dict(min_lat=47.60, max_lat=47.76, min_lng=-117.58, max_lng=-117.28)


# Links must be web addresses or paths on this site, never javascript: and the like.
URL_KEYS = {"permitUrl", "imageUrl", "docUrl", "sourceUrls"}
SAFE_URL = ("https://", "http://", "/")


class Bad(ValueError):
    pass


def check_url(value):
    if value and not str(value).lower().startswith(SAFE_URL):
        raise Bad(f'"{value}" isn\'t a web address (it should start with https://)')
    return value


def read_value(key, value, normalise_stage):
    """The edit's value in the form projects.json uses. None means blank."""
    kind = KINDS[key]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        raise Bad("should be true or false")
    if value is None or (isinstance(value, str) and not value.strip()):
        if kind == "stage":
            raise Bad("can't be blank")
        return [] if kind == "list" else None
    if kind in ("text", "date"):
        if not isinstance(value, (str, int, float)):
            raise Bad("should be text")
        return str(value).strip()
    if kind == "stage":
        stage = normalise_stage(value)
        if stage is None:
            raise Bad(f'"{value}" is not one of the six stages')
        return stage
    if kind == "int":
        text = str(value).replace(",", "").replace("$", "").strip()
        try:
            number = float(text)
        except ValueError:
            raise Bad(f'"{value}" is not a number')
        if number < 0:
            raise Bad("can't be negative")
        return int(number)
    if kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise Bad(f'"{value}" is not a number')
    if kind == "list":
        items = value if isinstance(value, list) else str(value).split(";")
        return [str(v).strip() for v in items if str(v).strip()]
    if kind == "permission":
        if value not in PERMISSIONS:
            raise Bad(f'should be one of: {", ".join(sorted(PERMISSION_OK | {"not-sure"}))}')
        return value


def load(edits_dir=EDITS_DIR):
    """Every edit file, oldest first. Returns (edits, warnings)."""
    warnings, found = [], []
    for path in glob.glob(os.path.join(edits_dir, "**", "*.json"), recursive=True):
        short = os.path.relpath(path, edits_dir)
        try:
            with open(path, encoding="utf-8") as handle:
                edit = json.load(handle)
        except (OSError, ValueError) as error:
            warnings.append(f"Edit {short}: couldn't be read ({error}). Skipped.")
            continue
        if not isinstance(edit, dict) or not isinstance(edit.get("project"), str):
            warnings.append(f'Edit {short}: has no "project". Skipped.')
            continue
        if not isinstance(edit.get("set", {}), dict) or not isinstance(edit.get("unset", []), list):
            warnings.append(f'Edit {short}: "set" or "unset" is the wrong shape. Skipped.')
            continue
        edit["_file"] = short
        found.append(edit)
    found.sort(key=lambda e: (str(e.get("at") or ""), e["_file"]))
    return found, warnings


def find(edit, by_id, projects):
    """The project an edit is for: by id, else by its permit numbers."""
    if edit["project"] in by_id:
        return by_id[edit["project"]], None
    permits = {str(p).upper() for p in edit.get("permits") or []}
    if not permits:
        return None, "no project has that id, and the edit lists no permit numbers"
    scored = []
    for p in projects:
        overlap = len(permits & {n.upper() for n in p.get("permitNumbers") or []})
        if overlap:
            scored.append((overlap, p))
    if not scored:
        return None, "no project has that id or any of its permit numbers"
    scored.sort(key=lambda s: -s[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        names = ", ".join(s[1]["id"] for s in scored[:3])
        return None, f"its permit numbers match more than one project ({names})"
    return scored[0][1], None


def set_detail(project, key, value):
    """Puts the edited value into the project page's detail list."""
    spec = next((d for d in DETAIL if d[0] == key), None)
    if not spec:
        return
    _, label, kind, show = spec
    fields = [f for f in project.get("fields") or [] if f.get("label") != label]
    if value not in (None, "", []):
        new = {"label": label, "value": show(value), "kind": kind}
        rank = DETAIL_ORDER.index(label)
        at = len(fields)
        for i, f in enumerate(fields):
            if f.get("label") in DETAIL_ORDER and DETAIL_ORDER.index(f["label"]) > rank:
                at = i
                break
        fields.insert(at, new)
    project["fields"] = fields


def apply_to(project, values, dates, stage_rank, was=None):
    """Applies one project's folded edits. Returns warnings. was: field -> what
    the site showed just before the latest edit of that field."""
    was = was or {}
    warnings = []
    label = values.get("name") or project.get("name") or project["id"]
    city_stage = project.get("_cityStage", project.get("status"))
    edited = []
    stamp = max(dates.values()) if dates else ""
    day = stamp[:10]
    note = f"edited by hand on {day}" if day else "edited by hand"

    for key, value in values.items():
        if key in ("hidden", "imagePermission"):
            continue
        if key == "status":
            # The city can move it forward from your stage, never back or off Stalled.
            if value != "Stalled" and city_stage and stage_rank(city_stage) > stage_rank(value):
                if project.get("status") != city_stage:
                    project["status"] = city_stage
                    project["stageSource"] = "city permit records (moved forward from your edit)"
                set_detail(project, "status", project["status"])
                warnings.append(
                    f"{label}: you set the stage to {value}; the city's permit records show "
                    f"{city_stage}, so it's shown as {city_stage}."
                )
                continue
            if value != project.get("status"):
                project["statusUpdated"] = values.get("statusUpdated") or dates["status"][:10]
            project["status"] = value
            project["stageSource"] = note
            set_detail(project, "status", value)
        elif key == "units":
            auto = project.get("units")
            # Only against the city's numbers: on a hand-curated project the
            # "automatic" value is just the project file, which is yours too.
            from_city = project.get("unitsSource") not in (None, "", "sheet")
            # Said once, not every day: when you saved the edit you saw the
            # city's number (it's the edit's "was"). Only a change in the city's
            # number since then is news.
            seen = was.get("units")
            if (from_city and value is not None and isinstance(auto, int) and auto > 0 and auto != value
                    and auto != seen):
                then = f" (it said {seen:,} when you edited)" if isinstance(seen, int) and seen != value else ""
                warnings.append(
                    f"{label}: you set {value:,} units; {project.get('unitsSource') or 'the automatic value'} "
                    f"now says {auto:,}{then}. Yours is shown."
                )
            project["units"] = value
            project["unitsSource"] = note if value is not None else ""
            set_detail(project, key, value)
        elif key in ("stories", "projectType"):
            project[key] = value if key == "stories" else (value or "")
            set_detail(project, key, value)
        elif key in ("sqft", "parking", "estCost", "developer", "architect", "permitUrl"):
            set_detail(project, key, value)
        elif key in ("lat", "lng"):
            project[key] = value
        elif key == "imageUrl":
            permission = values.get("imagePermission", "")
            if value and permission not in PERMISSION_OK:
                warnings.append(
                    f'{label}: the edited photo\'s permission is "{permission or "blank"}". '
                    f"Saved, but left off the site until it's granted or a public record."
                )
                project["imageUrl"] = ""
            else:
                project["imageUrl"] = value or ""
        elif key == "docUrl":
            project["docUrl"] = value or ""
        elif key == "sourceUrls":
            project["sourceUrls"] = value
        else:
            project[key] = value if value is not None else ""
        edited.append(key)

    # PDF thumbnails follow the photo permission, as before.
    if values.get("imagePermission") in PERMISSION_OK and (values.get("docUrl") or values.get("imageUrl")):
        project["_docThumbOk"] = True

    lat, lng = project.get("lat"), project.get("lng")
    if ("lat" in values or "lng" in values) and isinstance(lat, float) and isinstance(lng, float):
        if not (BOUNDS["min_lat"] <= lat <= BOUNDS["max_lat"] and BOUNDS["min_lng"] <= lng <= BOUNDS["max_lng"]):
            warnings.append(f"{label}: the edited location falls outside Spokane.")

    if edited:
        project["edited"] = sorted(edited)
        project["editedAt"] = stamp
    return warnings


_UNSET = object()  # "no earlier edit of this field" (None is a real value)

# Edits for "candidate-<key>" aren't for a project: "hidden": true there means
# "skip this permit" in the editor's list of housing permits not on the map.
CANDIDATE = "candidate-"


def apply(projects, normalise_stage, stage_rank, edits_dir=EDITS_DIR, hidden_out=None, history_out=None,
          skipped_out=None):
    """Returns (projects with edits applied and hidden ones removed, warnings).
    Always removes the build's internal _cityStage note. Hidden projects are
    added to hidden_out (a list) as {id, name, at}, for the editor's
    "Hidden from the map" list. Every applied edit is added to history_out (a
    dict: project id -> list, oldest first) for the editor's History tab."""
    found, warnings = load(edits_dir)
    by_id = {p["id"]: p for p in projects}
    values, dates, wases = {}, {}, {}  # project id -> field -> value / time / shown before

    skips = {}
    for edit in found:
        if edit["project"].startswith(CANDIDATE):
            key = edit["project"][len(CANDIDATE):]
            if edit.get("set", {}).get("hidden") is True:
                skips[key] = True
            if "hidden" in edit.get("unset", []):
                skips.pop(key, None)
            continue
        project, problem = find(edit, by_id, projects)
        if problem:
            warnings.append(f'Edit {edit["_file"]} for "{edit["project"]}": {problem}. Not applied.')
            continue
        pid = project["id"]
        v, d, before = values.setdefault(pid, {}), dates.setdefault(pid, {}), wases.setdefault(pid, {})
        if history_out is not None:
            history_out.setdefault(pid, []).append({
                "at": edit.get("at", ""), "file": edit["_file"], "set": edit.get("set", {}),
                "was": edit.get("was", {}), "unset": edit.get("unset", []), "note": edit.get("note", ""),
            })
        for key, raw in edit.get("set", {}).items():
            if key not in KINDS:
                warnings.append(f'Edit {edit["_file"]}: "{key}" isn\'t a field that can be edited. Skipped.')
                continue
            try:
                earlier = v[key] if key in v else _UNSET
                v[key] = read_value(key, raw, normalise_stage)
                if key in URL_KEYS:
                    for url in (v[key] if isinstance(v[key], list) else [v[key]]):
                        check_url(url)
                d[key] = str(edit.get("at") or "")
                shown = (edit.get("was") or {}).get(key)
                # Editing your own edit again: what the site showed before was
                # your earlier value, so keep what it showed before that.
                if not (earlier is not _UNSET and shown == earlier and key in before):
                    before[key] = shown
            except Bad as error:
                v.pop(key, None)
                warnings.append(f'Edit {edit["_file"]}: {key} {error}. Skipped.')
        for key in edit.get("unset", []):
            v.pop(key, None)
            d.pop(key, None)
            before.pop(key, None)

    kept, hidden = [], 0
    for p in projects:
        mine = values.get(p["id"])
        if mine:
            if mine.get("hidden") is True:
                hidden += 1
                if hidden_out is not None:
                    hidden_out.append({"id": p["id"], "name": p.get("name") or p["id"],
                                       "at": dates[p["id"]].get("hidden", ""),
                                       "permits": p.get("permitNumbers") or []})
                continue
            warnings.extend(apply_to(p, mine, dates[p["id"]], stage_rank, wases.get(p["id"])))
        p.pop("_cityStage", None)
        kept.append(p)
    if skipped_out is not None:
        skipped_out.update(skips)
    applied = sum(1 for pid, v in values.items() if v)
    if found:
        print(f"Applied {len(found)} edit file(s) to {applied} project(s); {hidden} hidden.")
    return kept, warnings
