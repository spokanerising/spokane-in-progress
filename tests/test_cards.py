"""Phase 3 of the sharing plan: a share card per project (cards.py), drawn
only when something on it changes, named by a fingerprint, old ones removed,
pages pointing at them; and the site-wide card redrawn only when its map
would change."""
import copy, json, os, re, shutil, struct, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import REPO
sys.path.insert(0, REPO)
import cards, pages

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

def jpeg_size(path):
    data = open(path, "rb").read()
    check(data[:2] == b"\xff\xd8", f"{path} is a JPEG")
    i = 2
    while i < len(data):
        marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + length
    return None

def png_size(path):
    head = open(path, "rb").read(24)
    return struct.unpack(">II", head[16:24])

data = json.load(open(os.path.join(REPO, "projects.json")))
P = data["projects"]
base = next(p for p in P if p.get("units") and p.get("neighborhoodCouncil"))

# ---- fingerprints
fp = cards.fingerprint(base)
check(fp == cards.fingerprint(copy.deepcopy(base)), "stable")
for key, value in [("name", "Other"), ("units", 999), ("status", "Complete"), ("address", "1 Elsewhere St"), ("lat", base["lat"] + 0.01)]:
    other = dict(base, **{key: value})
    check(cards.fingerprint(other) != fp, f"changes with {key}")
check(cards.fingerprint(dict(base, lastVerified="2030-01-01", milestones=[])) == fp, "ignores things not drawn")
check(re.fullmatch(r"card-[0-9a-f]{8}\.jpg", cards.card_name(base)), cards.card_name(base))

# ---- what's on the card
named = {"id": "x", "name": "8514 N Orchard Ct Duplex", "address": "8514 N Orchard Ct", "neighborhood": "Five Mile Prairie",
         "status": "Under Construction", "stageSource": "city permit records: 1 trade permit(s) issued", "units": 2, "buildingType": "Duplex"}
h = cards.card_html(named, data["stages"], {"features": []}, "")
check(">Five Mile Prairie<" in h and h.count("8514 N Orchard Ct") == 1, "address not repeated when the name is the address")
check("Under construction (estimated)" in h, "estimated stage")
h = cards.card_html(dict(named, name="Elm Court"), data["stages"], {"features": []}, "")
check("8514 N Orchard Ct · Five Mile Prairie" in h, "address shown otherwise")
h = cards.card_html({"id": "y", "name": 'A "B" & <C>', "status": "Pre-Application"}, data["stages"], {"features": []}, "")
check("&lt;C&gt;" in h and "<C>" not in h, "escaped")
check("Number of homes not yet reported" in h and ">Housing project<" in h, "missing data")
check(cards.card_alt(named) == "8514 N Orchard Ct Duplex, 2 homes, under construction (estimated), in Five Mile Prairie, shown on a map of Spokane.", cards.card_alt(named))
check(cards.name_size("x" * 56) < cards.name_size("Short"), "long names get smaller type")

# ---- a real run in a scratch copy of the site
root = tempfile.mkdtemp()
few = [p for p in P if p.get("neighborhoodCouncil")][:3]
json.dump({"stages": data["stages"], "projects": few, "builtAt": data.get("builtAt")}, open(os.path.join(root, "projects.json"), "w"))
shutil.copy(os.path.join(REPO, "boundaries.geojson"), root)
pages.write_all(few, root, "https://example.test")
check(cards.run(root, origin="https://example.test") == [], "no warnings")
for p in few:
    path = cards.card_path(p, root)
    check(os.path.isfile(path) and jpeg_size(path) == (1200, 630), f"card for {p['id']}")
    raw = open(os.path.join(root, "p", p["id"], "index.html")).read()
    check(f'content="https://example.test/p/{p["id"]}/{cards.card_name(p)}"' in raw and 'content="image/jpeg"' in raw, "page points at its card")
    check(cards.card_alt(p).replace("&", "&amp;") in raw or cards.card_alt(p) in raw, "alt text")
check(png_size(os.path.join(root, "og-card.png")) == (1200, 630), "site card drawn")
site_mtime = os.path.getmtime(os.path.join(root, "og-card.png"))
card_mtime = os.path.getmtime(cards.card_path(few[0], root))

# Nothing drawn changed: nothing redrawn (even if other fields did)
few[0]["lastVerified"] = "2031-01-01"
json.dump({"stages": data["stages"], "projects": few}, open(os.path.join(root, "projects.json"), "w"))
cards.run(root, origin="https://example.test")
check(os.path.getmtime(cards.card_path(few[0], root)) == card_mtime, "card not redrawn")
check(os.path.getmtime(os.path.join(root, "og-card.png")) == site_mtime, "site card not redrawn")

# Units change: a new card, the old one gone, the page updated, site card redrawn
old_path = cards.card_path(few[0], root)
few[0]["units"] = (few[0].get("units") or 0) + 7
json.dump({"stages": data["stages"], "projects": few}, open(os.path.join(root, "projects.json"), "w"))
cards.run(root, origin="https://example.test")
new_path = cards.card_path(few[0], root)
check(new_path != old_path and os.path.isfile(new_path) and not os.path.exists(old_path), "replaced card")
check(os.listdir(os.path.join(root, "p", few[0]["id"])) == ["index.html", os.path.basename(new_path)] or
      sorted(os.listdir(os.path.join(root, "p", few[0]["id"]))) == sorted(["index.html", os.path.basename(new_path)]), "no leftovers")
check(cards.card_name(few[0]) in open(os.path.join(root, "p", few[0]["id"], "index.html")).read(), "page follows the new card")
check(os.path.getmtime(os.path.join(root, "og-card.png")) != site_mtime, "site card redrawn when a dot changes")

# No card yet: the page uses the site card
lone = dict(few[1], id="no-card-yet")
pages.write_all(few + [lone], root, "https://example.test")
check('content="https://example.test/og-card.png"' in open(os.path.join(root, "p", "no-card-yet", "index.html")).read(), "falls back to the site card")
shutil.rmtree(root)
print(f"{ok} checks passed")
