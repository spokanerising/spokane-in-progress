"""Unit counts read from permit descriptions: counts multiply, and wording
that says "several buildings" without a number gives no count rather than a
low one."""
import os, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import city_records as cr

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1

BUILDING = [
    ("two sixplexes", 12), ("Two Sixplexes - Bldg A & B", 12), ("2 fourplexes", 8),
    ("Two 4-plexes", 8), ("three duplexes", 6), ("(2) 6-plex buildings", 12),
    ("12 new duplexes", 24), ("two triplexes on separate lots", 6),
    ("a fourplex on each of 3 lots", 12), ("fourplex on two lots", 8),
    ("one sixplex on each lot", None),
    ("24 unit apartment", 24), ("sixplex", 6), ("8-plex", 8), ("New Duplex", 2),
    ("10th Ave. Fourplexes", 4),                 # one building per permit
    ("Lot 3 duplex", 2), ("#2 duplex", 2), ("Bldg 2 Fourplex", 4),
    ("Ryan Buth - 4315 4 Plex", 4), ("3140 DUPLEX", 2),
    ("New Townhouse - 1 of 2 Attached SFR", 1), ("Detached 6 unit Garage", None),
]
PREDEV = [
    ("1611 W 9th Sixplexes", None), ("Pacific Ave Duplexes", None),
    ("Two Sixplexes", 12), ("Hamblen Condos", None), ("Mission Fourplex", 4),
]
for notes, want in BUILDING:
    got = cr.units_from_notes({"notes": notes, "type": "Residential Building Permit"})
    check(got == want, f"{notes!r}: {got}, expected {want}")
for notes, want in PREDEV:
    got = cr.units_from_notes({"notes": notes, "type": "Pre-Development Conference"})
    check(got == want, f"pre-dev {notes!r}: {got}, expected {want}")
print(f"{ok} checks passed")
