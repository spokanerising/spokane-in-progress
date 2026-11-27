"""edits.py: edits from the site applied on top of the build. No browser needed."""
import copy, json, os, sys, tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import edits  # noqa: E402

STAGES = ["Pre-Application", "Applied", "Approved", "Under Construction", "Complete"]


def normalise(value):
    for s in STAGES + ["Stalled"]:
        if str(value).lower() == s.lower():
            return s
    return None


def rank(stage):
    return STAGES.index(stage) if stage in STAGES else -1


BASE = [
    {"id": "city-b1bldc", "name": "Corner Flats", "address": "1 W Main", "status": "Applied",
     "statusUpdated": "2026-01-01", "stageSource": "city", "units": 44, "unitsSource": "city permit report",
     "stories": 4, "permitNumbers": ["B1BLDC", "B1PDEV"], "autoAdded": True, "lat": 47.66, "lng": -117.42,
     "imageUrl": "", "docUrl": "", "sourceUrls": [],
     "fields": [{"label": "Stage", "value": "Applied", "kind": "text"},
                {"label": "Housing units", "value": "44", "kind": "text"},
                {"label": "Permit application", "value": "https://x", "kind": "link"},
                {"label": "Source", "value": "City records", "kind": "text"}]},
    {"id": "hand-row", "name": "Hand Row", "status": "Approved", "_cityStage": "Under Construction",
     "permitNumbers": ["B2BLDC"], "fields": [], "units": None},
    {"id": "other", "name": "Other", "status": "Applied", "_cityStage": None,
     "permitNumbers": ["B3BLDC"], "fields": []},
]

checks = 0


def run(files):
    with tempfile.TemporaryDirectory() as d:
        for i, edit in enumerate(files):
            sub = os.path.join(d, "2026", "11")
            os.makedirs(sub, exist_ok=True)
            with open(os.path.join(sub, f"{i:03d}.json"), "w") as h:
                h.write(edit if isinstance(edit, str) else json.dumps(edit))
        out, warnings = edits.apply(copy.deepcopy(BASE), normalise, rank, edits_dir=d)
    return {p["id"]: p for p in out}, warnings


def check(cond, what):
    global checks
    if not cond:
        sys.exit(f"FAIL: {what}")
    checks += 1


def label(p, name):
    return next((f["value"] for f in p["fields"] if f["label"] == name), None)


# No edits: nothing changes except the internal note is removed.
out, w = run([])
check(not w, "no warnings without edits")
check("_cityStage" not in out["hand-row"], "_cityStage removed")
plain = copy.deepcopy(BASE[0])
check(out["city-b1bldc"] == plain, "untouched project is unchanged")

# Units and a new detail field, in the right place.
out, w = run([{"project": "city-b1bldc", "at": "2026-11-27T09:00:00Z",
               "set": {"units": "1,048", "sqft": 90000, "developer": "Acme"}}])
p = out["city-b1bldc"]
check(p["units"] == 1048 and label(p, "Housing units") == "1,048", "units edited")
check(p["unitsSource"] == "edited by hand on 2026-11-27", "units source note")
labels = [f["label"] for f in p["fields"]]
check(labels == ["Stage", "Housing units", "Floor area", "Developer", "Permit application", "Source"],
      f"detail order {labels}")
check(p["edited"] == ["developer", "sqft", "units"], "edited list")

# Later edit wins; unset goes back to automatic.
out, w = run([{"project": "city-b1bldc", "at": "2026-11-27T09:00:00Z", "set": {"units": 50, "stories": 6}},
              {"project": "city-b1bldc", "at": "2026-11-28T09:00:00Z", "set": {"units": 52}, "unset": ["stories"]}])
p = out["city-b1bldc"]
check(p["units"] == 52 and p["stories"] == 4, "later wins, unset restores")

# Files are applied by time, not file name.
out, w = run([{"project": "city-b1bldc", "at": "2026-11-29T00:00:00Z", "set": {"units": 60}},
              {"project": "city-b1bldc", "at": "2026-11-28T00:00:00Z", "set": {"units": 59}}])
check(out["city-b1bldc"]["units"] == 60, "ordered by time")

# Stage: your stage sticks...
out, w = run([{"project": "city-b1bldc", "at": "2026-11-27T10:00:00Z", "set": {"status": "complete"}}])
p = out["city-b1bldc"]
check(p["status"] == "Complete" and label(p, "Stage") == "Complete", "stage edited")
check(p["statusUpdated"] == "2026-11-27" and p["stageSource"].startswith("edited"), "stage date and source")
# ...but the city moves it forward, never back.
out, w = run([{"project": "hand-row", "at": "2026-11-27T10:00:00Z", "set": {"status": "Applied"}}])
check(out["hand-row"]["status"] == "Under Construction", "city moves an edited stage forward")
check(any("moved" in x or "shown as" in x for x in w), "warning when city moves it")
check("status" not in out["hand-row"].get("edited", []), "not marked edited when city wins")
out, w = run([{"project": "hand-row", "at": "2026-11-27T10:00:00Z", "set": {"status": "Stalled"}}])
check(out["hand-row"]["status"] == "Stalled", "Stalled is never moved")
out, w = run([{"project": "city-b1bldc", "at": "2026-11-27T10:00:00Z", "set": {"status": "Pre-Application"}}])
check(out["city-b1bldc"]["status"] == "Applied", "auto project: city stage still the floor")

# Hide, and un-hide with a later edit.
out, w = run([{"project": "other", "at": "2026-11-27T10:00:00Z", "set": {"hidden": True}}])
check("other" not in out, "hidden")
out, w = run([{"project": "other", "at": "2026-11-27T10:00:00Z", "set": {"hidden": True}},
              {"project": "other", "at": "2026-11-28T10:00:00Z", "unset": ["hidden"]}])
check("other" in out, "un-hidden")

# The id changed: found by permit number. No match: a warning, not a crash.
out, w = run([{"project": "city-b1pdev", "permits": ["B1PDEV"], "at": "2026-11-27T10:00:00Z", "set": {"units": 7}}])
check(out["city-b1bldc"]["units"] == 7, "found by permit number")
out, w = run([{"project": "gone", "permits": ["ZZZ"], "at": "2026-11-27T10:00:00Z", "set": {"units": 7}}])
check(any("Not applied" in x for x in w), "orphan reported")

# Photo needs permission; text is kept as typed; blanks clear.
out, w = run([{"project": "other", "at": "2026-11-27T10:00:00Z", "set": {"imageUrl": "/media/a.jpg"}}])
check(out["other"].get("imageUrl") == "" and w, "photo without permission held back")
out, w = run([{"project": "other", "at": "2026-11-27T10:00:00Z",
               "set": {"imageUrl": "/media/a.jpg", "imagePermission": "granted", "name": "NAME AS TYPED"}}])
check(out["other"]["imageUrl"] == "/media/a.jpg" and out["other"]["name"] == "NAME AS TYPED", "photo with permission")
out, w = run([{"project": "city-b1bldc", "at": "2026-11-27T10:00:00Z", "set": {"units": None, "permitUrl": ""}}])
p = out["city-b1bldc"]
check(p["units"] is None and label(p, "Housing units") is None and label(p, "Permit application") is None,
      "blank clears")

# Bad input is skipped with a warning, never crashes the build.
out, w = run(["{not json", {"project": "other", "set": {"units": "lots", "colour": "red", "status": "Soon"}},
              {"set": {}}])
check(len(w) == 5 and out["other"].get("units") is None, f"bad input warnings {w}")

# Links must be web addresses: no javascript: links reach the page.
out, w = run([{"project": "other", "at": "2026-11-27T10:00:00Z",
               "set": {"docUrl": "javascript:alert(1)", "sourceUrls": ["https://ok.example", "data:text/html,x"], "units": 3}}])
check(not out["other"].get("docUrl") and "sourceUrls" not in out["other"].get("edited", []), "unsafe links refused")
check(out["other"]["units"] == 3 and len(w) == 2, f"rest of the edit still applies {w}")

# Hidden projects are listed for the editor.
hidden = []
with tempfile.TemporaryDirectory() as d:
    os.makedirs(os.path.join(d, "x"))
    json.dump({"project": "other", "at": "2026-11-27T10:00:00Z", "set": {"hidden": True}}, open(os.path.join(d, "x", "h.json"), "w"))
    edits.apply(copy.deepcopy(BASE), normalise, rank, edits_dir=d, hidden_out=hidden)
check(hidden == [{"id": "other", "name": "Other", "at": "2026-11-27T10:00:00Z"}], f"hidden list {hidden}")

print(f"{checks} checks passed")
