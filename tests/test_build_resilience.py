"""The build when a city service is slow or down (issue #41): projects the
monthly report adds are placed once and remembered, a project that was on the
map keeps its last known location instead of dropping off, and a project that
leaves the map is said out loud. No network: the city's locator is faked."""
import os, sys
from datetime import date
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import build

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1

TODAY = date.today().isoformat()
MONTHLY = {"x": [{"key": "B26M9001PDEV", "title": "Test Flats", "address": "100 W Test Ave", "units": "24",
                  "permits": "B26M9001PDEV", "as_of": TODAY, "table": "Pre-development", "valuation": ""}]}
calls = []
def locator(answer):
    def geocode(address):
        calls.append(address)
        return answer
    return geocode

def run(answer, geocache, previous):
    build.cr.geocode = locator(answer)
    return build.monthly_only_projects(MONTHLY, set(), {}, [], {}, geocache, previous)

# The locator answers: the project is placed, and the place is remembered.
cache = {}
out, warnings, changed = run((47.66, -117.42, "100 W TEST AVE, SPOKANE"), cache, {})
check(len(out) == 1 and out[0]["lat"] == 47.66 and changed, f"placed {out} {warnings}")
check(cache.get("address:100 W TEST AVE", {}).get("lat") == 47.66, f"remembered {cache}")

# Next build, the locator is down: the remembered place is used, without asking.
calls.clear()
out, warnings, changed = run(None, cache, {})
check(len(out) == 1 and out[0]["lat"] == 47.66 and not calls and not changed and not warnings,
      f"cache used, locator not asked {calls} {warnings}")

# No cache, locator down, but it was on the map last build: kept where it was.
prev = {"monthly-b26m9001pdev": {"id": "monthly-b26m9001pdev", "lat": 47.65, "lng": -117.41,
                                 "address": "100 W Test Ave", "status": "Pre-Application"}}
out, warnings, changed = run(None, {}, prev)
check(len(out) == 1 and (out[0]["lat"], out[0]["lng"]) == (47.65, -117.41), f"last known kept {out}")
check(any("kept its last known location" in w for w in warnings), f"said so {warnings}")

# Never on the map and the locator can't place it: left off, as before.
out, warnings, changed = run(None, {}, {})
check(out == [] and any("couldn't place Test Flats" in w for w in warnings), f"not mapped {warnings}")

# Leaving the map is noted, unless it was hidden on purpose; a big drop is flagged.
prev = {f"p{i}": {"id": f"p{i}", "name": f"Project {i}", "status": "Applied"} for i in range(6)}
notes = build.left_the_map(prev, [{"id": "p0"}, {"id": "p1"}], [{"id": "p2"}])
check(sum(n.startswith("No longer on the map") for n in notes) == 3 and "Project 2" not in " ".join(notes),
      f"gone noted, hidden not {notes}")
check(not any("left the map in this build" in n for n in notes), f"three isn't a big drop {notes}")
notes = build.left_the_map(prev, [], [])
check(notes[0].startswith("6 projects left the map"), f"big drop flagged {notes}")
check(build.left_the_map(prev, list(prev.values()), []) == [], "nothing gone, nothing said")

print(f"{ok} checks passed")
