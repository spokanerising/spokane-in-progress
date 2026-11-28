"""layers.py: the pure-Python parts (Census math, MFTE terms, class breaks,
2010 -> 2020 tract populations). The fetching and geometry run on the GitHub
runner and are checked there by the sanity checks in write_layer()."""
import math, os, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import layers as ly

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1

# MFTE terms straight from the city's EligibleDuration values.
check(ly.mfte_term("8, 12, & 20yr") == ("STIA", "8, 12 or 20 years"), ly.mfte_term("8, 12, & 20yr"))
check(ly.mfte_term("12 & 20yr") == ("AHEA", "12 or 20 years"), ly.mfte_term("12 & 20yr"))
check(ly.mfte_term("") == (None, ""), "blank term")

# Proportion margins (Census handbook): 950 of 1430 renters, MOEs 192 / 189.
p, moe = ly.ratio(950, 192, 1430, 189)
check(abs(p - 0.6643) < 0.001, p)
expected = math.sqrt(192 ** 2 - p ** 2 * 189 ** 2) / 1430
check(abs(moe - expected) < 1e-9, moe)
# Negative radicand falls back to the ratio formula.
p2, moe2 = ly.ratio(10, 5, 10, 20)
check(p2 == 1 and abs(moe2 - math.sqrt(25 + 400) / 10) < 1e-9, (p2, moe2))
check(ly.ratio(5, 1, 0, 1) == (None, None), "zero base")

check(ly.reliable(100, 10) and not ly.reliable(100, 60), "CV cutoff at 30%")
check(ly.reliable(1938, None), "no margin (decennial) counts as reliable")

# The real first row from the discovery run (tract 2.01), in the API's shape.
names = (["B25003_001E", "B25003_002E", "B25003_003E", "B25064_001E", "B19013_001E", "B17001_001E", "B17001_002E",
          "B25035_001E", "B25034_001E", "B25034_010E", "B25034_011E", "B25070_001E", "B25070_007E", "B25070_008E",
          "B25070_009E", "B25070_010E", "B25070_011E", "B25003_001M", "B25003_002M", "B25003_003M", "B25064_001M",
          "B19013_001M", "B17001_001M", "B17001_002M", "B25035_001M", "B25034_001M", "B25034_010M", "B25034_011M",
          "B25070_001M", "B25070_007M", "B25070_008M", "B25070_009M", "B25070_010M", "B25070_011M"])
vals = ["1430", "950", "480", "1393", "48676", "3436", "503", "1938", "1458", "150", "759", "480", "41", "28", "35",
        "121", "7", "189", "192", "125", "294", "13155", "518", "248", "-333333333", "181", "76", "180", "125", "45",
        "35", "41", "71", "11"]
m = ly.acs_measures(dict(zip(names, vals)))
check(abs(m["renterShare"][0] - 480 / 1430) < 1e-9, m["renterShare"])     # B25003_003 is renters
check(m["medianRent"] == (1393, 294), m["medianRent"])
check(abs(m["rentBurden"][0] - (41 + 28 + 35 + 121) / (480 - 7)) < 1e-9, m["rentBurden"])
check(abs(m["pre1940"][0] - 759 / 1458) < 1e-9, m["pre1940"])
check(m["medianYearBuilt"] == (1938, None), "a -333333333 margin is no margin")
check(abs(m["poverty"][0] - 503 / 3436) < 1e-9, m["poverty"])
none = ly.acs_measures({"B25064_001E": "-666666666"})
check(none["medianRent"] == (None, None) and none["renterShare"] == (None, None), none)

# Five equal-count classes.
b = ly.quantile_breaks(list(range(1, 101)))
check(len(b) == 4 and abs(b[0] - 20.8) < 1e-9 and abs(b[-1] - 80.2) < 1e-9, b)
check(ly.quantile_breaks([1, None, 2]) == [], "too few values")

# A 2010 tract split in two 2020 tracts by land area, and one unchanged.
rel = "﻿" + "\n".join([
    "OID_TRACT_20|GEOID_TRACT_20|NAMELSAD_TRACT_20|AREALAND_TRACT_20|AREAWATER_TRACT_20|MTFCC_TRACT_20|FUNCSTAT_TRACT_20|"
    "OID_TRACT_10|GEOID_TRACT_10|NAMELSAD_TRACT_10|AREALAND_TRACT_10|AREAWATER_TRACT_10|MTFCC_TRACT_10|FUNCSTAT_TRACT_10|"
    "AREALAND_PART|AREAWATER_PART",
    "1|53063000201|x|300|0|G|S|9|53063000200|x|1000|0|G|S|300|0",
    "2|53063000202|x|700|0|G|S|9|53063000200|x|1000|0|G|S|700|0",
    "3|53063000300|x|500|0|G|S|8|53063000300|x|500|0|G|S|500|0",
    "4|53033000100|x|500|0|G|S|7|53033000100|x|500|0|G|S|500|0",  # King County, ignored
])
moved = ly.pop2010_on_2020(rel, {"53063000200": 4000, "53063000300": 2500})
check(abs(moved["53063000201"] - 1200) < 1e-9 and abs(moved["53063000202"] - 2800) < 1e-9, moved)
check(moved["53063000300"] == 2500 and "53033000100" not in moved, moved)

# Coordinate rounding keeps lng/lat only.
check(ly.round_coords([[-117.4123456, 47.6543219, 3.0]]) == [[-117.41235, 47.65432]], "rounding")
check(ly.inside_area([{"geometry": {"coordinates": [[[-117.4, 47.6], [-117.3, 47.7]]]}}]), "inside")
check(not ly.inside_area([{"geometry": {"coordinates": [[[-122.3, 47.6]]]}}]), "Seattle is outside")

print(f"{ok} checks passed")
