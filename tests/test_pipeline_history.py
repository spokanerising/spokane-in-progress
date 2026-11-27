"""Daily pipeline counts (issue #3): one row a day in data/pipeline-history.csv,
a same-day rebuild replaces that day's row, and old columns are kept."""
import csv, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import pipeline_history as ph

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

stages = ["Pre-Application", "Applied", "Approved", "Under Construction", "Complete", "Stalled"]
projects = [
    {"status": "Applied", "units": 10}, {"status": "Applied", "units": None},
    {"status": "Under Construction", "units": 96}, {"status": "Pre-Application"},
]
path = os.path.join(tempfile.mkdtemp(), "data", "pipeline-history.csv")
row = ph.record(projects, stages, day="2026-11-26", path=path)
check(row["projects"] == 4 and row["homes"] == 106 and row["projects_no_count"] == 2, row)
check(row["applied_projects"] == 2 and row["applied_homes"] == 10, row)
check(row["under_construction_homes"] == 96 and row["stalled_projects"] == 0, row)

ph.record(projects[:1], stages, day="2026-11-27", path=path)
ph.record(projects, stages, day="2026-11-27", path=path)     # same day again: replaces
rows = list(csv.DictReader(open(path)))
check([r["date"] for r in rows] == ["2026-11-26", "2026-11-27"], rows)
check(rows[1]["projects"] == "4", "the day's last count wins")

# A stage renamed later: old column kept, blank on new days.
ph.record(projects, ["Applied", "Building"], day="2026-11-28", path=path)
rows = list(csv.DictReader(open(path)))
check("stalled_projects" in rows[0] and rows[2]["stalled_projects"] == "" and rows[2]["building_projects"] == "0", rows[2])
check(len(ph.today_pacific()) == 10, "today's date")

# The repo's own log has a header and rows in date order.
real = os.path.join(os.path.dirname(HERE), "data", "pipeline-history.csv")
if os.path.exists(real):
    rr = list(csv.DictReader(open(real)))
    check(rr and [r["date"] for r in rr] == sorted(r["date"] for r in rr), "repo log in date order")
print(f"{ok} checks passed")
