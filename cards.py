"""Share images: one 1200 x 630 card per project, shown when its page
(p/<id>/) is shared.

    python3 cards.py                      # draw any card that's missing or out of date
    python3 cards.py --only ID [ID ...]   # draw just these (samples), into cards-samples/
    python3 cards.py --all                # redraw every card

Each card is an HTML page drawn in headless Chrome with the site's own
typefaces (the same way tools/make_site_card.py draws the site card):
the project's name, homes, stage and building type, where it is, the stage
track, and a small map of the city with the project's neighborhood shaded
and its dot.

A card's file name carries a short fingerprint of everything drawn on it
(p/<id>/card-3fa9c1d2.jpg). A card is redrawn only when that changes, which
keeps the daily commit small, and the new name makes Bluesky, Facebook and
the rest fetch the new image instead of a stale saved copy. Old cards are
removed when a new one replaces them. After drawing, the project pages are
rewritten (pages.py) to point at their cards, and the site-wide card
(og-card.png) is redrawn if any project's dot on it moved or changed.

Needs: pip install playwright && python -m playwright install chromium
"""
import argparse, glob, hashlib, html, json, math, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from make_site_card import font_faces  # noqa: E402

W, H = 1200, 630
VERSION = "2"   # bump when the design changes, so every card is redrawn
SAMPLES = os.path.join(ROOT, "cards-samples")

STAGE_WORDS = {
    "Pre-Application": "Proposed",
    "Applied": "In permit review",
    "Approved": "Approved",
    "Under Construction": "Under construction",
    "Complete": "Complete",
    "Stalled": "Stalled",
}


def stage_inferred(p):
    return p.get("status") == "Under Construction" and "trade permit" in (p.get("stageSource") or "").lower()


def drawn(p):
    """Everything that appears on the card. Its fingerprint names the file."""
    return {
        "v": VERSION, "name": p.get("name") or "", "address": p.get("address") or "",
        "hood": p.get("neighborhood") or p.get("neighborhoodCouncil") or "",
        "council": p.get("neighborhoodCouncil") or "",
        "units": p.get("units") if isinstance(p.get("units"), int) and p["units"] > 0 else None,
        "type": p.get("buildingType") if p.get("buildingType") not in (None, "", "Not yet known") else "",
        "status": p.get("status") or "", "est": stage_inferred(p),
        "at": [round(p["lat"], 4), round(p["lng"], 4)] if isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float)) else None,
    }


def fingerprint(p):
    return hashlib.sha1(json.dumps(drawn(p), sort_keys=True).encode()).hexdigest()[:8]


def card_name(p):
    return f"card-{fingerprint(p)}.jpg"


def card_path(p, root=ROOT):
    return os.path.join(root, "p", p["id"], card_name(p))


def card_alt(p):
    """Words for people who can't see the card."""
    d = drawn(p)
    bits = [d["name"]]
    if d["units"]:
        bits.append(f'{d["units"]:,} {"home" if d["units"] == 1 else "homes"}')
    stage = STAGE_WORDS.get(d["status"], d["status"]).lower()
    bits.append(f"{stage}{' (estimated)' if d['est'] else ''}")
    if d["hood"]:
        bits.append(f"in {d['hood']}")
    return ", ".join(bits) + ", shown on a map of Spokane."


# ---------------------------------------------------------------------------

def locator(d, outlines, stages, box_w, box_h):
    """The city (council districts), the project's neighborhood council
    shaded, and the project's dot."""
    def polys(f):
        g = f["geometry"]
        return [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    districts = [f for f in outlines.get("features", []) if f["properties"].get("kind") == "district"]
    hood = [f for f in outlines.get("features", []) if f["properties"].get("kind") == "hood" and f["properties"].get("name") == d["council"]]
    rings = [ring for f in districts for poly in polys(f) for ring in poly]
    pts = [pt for ring in rings for pt in ring]
    if not pts:
        return ""
    lng0, lng1 = min(p[0] for p in pts), max(p[0] for p in pts)
    lat0, lat1 = min(p[1] for p in pts), max(p[1] for p in pts)
    kx = math.cos(math.radians((lat0 + lat1) / 2))
    pad = 6   # room for the outline's stroke at the box edges
    scale = min((box_w - 2 * pad) / ((lng1 - lng0) * kx), (box_h - 2 * pad) / (lat1 - lat0))
    ox = (box_w - (lng1 - lng0) * kx * scale) / 2
    oy = (box_h - (lat1 - lat0) * scale) / 2
    xy = lambda lng, lat: (ox + (lng - lng0) * kx * scale, oy + (lat1 - lat) * scale)
    path = lambda ring: "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (xy(*pt[:2]) for pt in ring)) + "Z"
    color = {s["name"]: s["color"] for s in stages}.get(d["status"], "#8f8c86")
    # Just the city's outer edge: the districts drawn twice, first with a
    # wide edge, then filled (with a thin same-color edge) on top, which
    # hides every inside border and any hairline gaps between districts.
    outline = "".join(path(r) for r in rings)
    out = [f'<path d="{outline}" fill="#f2eee5" stroke="#b9b2a5" stroke-width="4" stroke-linejoin="round"/>',
           f'<path d="{outline}" fill="#f2eee5" stroke="#f2eee5" stroke-width="2" stroke-linejoin="round"/>']
    for f in hood:
        for poly in polys(f):
            out.append(f'<path d="{" ".join(path(r) for r in poly)}" fill="#d6cfc1" fill-rule="evenodd" stroke="#3a3936" stroke-width="1.5" stroke-linejoin="round"/>')
    if d["at"]:
        x, y = xy(d["at"][1], d["at"][0])
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="none" stroke="#121212" stroke-width="1.8"/>')
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{color}" stroke="#fff" stroke-width="2"/>')
    return f'<svg width="{box_w}" height="{box_h}" viewBox="0 0 {box_w} {box_h}">{"".join(out)}</svg>'


def track(d, stages):
    """The detail panel's five-step stage track."""
    names = [s["name"] for s in stages][:5]
    color = {s["name"]: s["color"] for s in stages}.get(d["status"], "#8f8c86")
    at = names.index(d["status"]) if d["status"] in names else -1
    segs = "".join(f'<i style="background:{color if i <= at else "#e6e1d6"}"></i>' for i in range(len(names)))
    return f'<div class="track">{segs}</div>'


def name_size(name):
    """Big for short names, smaller as they get longer, so every name fits
    in three lines."""
    n = len(name)
    return 76 if n <= 22 else 66 if n <= 34 else 56 if n <= 46 else 48


def card_html(p, stages, outlines, fonts_css):
    d = drawn(p)
    e = lambda s: html.escape(str(s))
    color = {s["name"]: s["color"] for s in stages}.get(d["status"], "#8f8c86")
    stage = STAGE_WORDS.get(d["status"], d["status"])
    if d["est"]:
        stage += " (estimated)"
    # Projects the city added are often named after their address
    # ("8514 N Orchard Ct Duplex"); don't say it twice.
    named_for_address = d["address"] and d["name"].lower().startswith(d["address"].split(" & ")[0].lower())
    where = " · ".join(x for x in [None if named_for_address else d["address"], d["hood"]] if x)
    homes = (f'<span class="num">{d["units"]:,}</span><span class="unit">{"home" if d["units"] == 1 else "homes"}</span>'
             if d["units"] else '<span class="unit unit--none">Number of homes not yet reported</span>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{fonts_css}
* {{ margin: 0; box-sizing: border-box; }}
body {{ width: {W}px; height: {H}px; background: #faf8f3; color: #121212; overflow: hidden; font-family: 'Libre Franklin'; }}
.card {{ position: relative; width: {W}px; height: {H}px; }}
.left {{ position: absolute; left: 72px; top: 58px; width: 640px; bottom: 100px; display: flex; flex-direction: column; }}
.kicker {{ font: 600 16px 'Libre Franklin'; letter-spacing: 0.09em; text-transform: uppercase; color: #6b6964; }}
h1 {{ margin-top: 18px; font: 600 {name_size(d["name"])}px/1.02 'Newsreader'; letter-spacing: -0.3px;
      display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
.where {{ margin-top: 16px; font: 500 22px/1.3 'Libre Franklin'; color: #3a3936;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.facts {{ margin-top: auto; }}
.homes {{ display: flex; align-items: baseline; gap: 12px; }}
.num {{ font: 600 84px/0.9 'Newsreader'; }}
.unit {{ font: 500 30px 'Newsreader'; color: #3a3936; }}
.unit--none {{ font: 500 26px 'Newsreader'; color: #6b6964; }}
.stage {{ display: flex; align-items: center; gap: 12px; margin-top: 18px; font: 600 22px 'Libre Franklin'; }}
.stage b {{ width: 16px; height: 16px; border-radius: 50%; background: {color}; flex: none; }}
.stage span {{ font-weight: 500; color: #6b6964; }}
.track {{ display: flex; gap: 4px; width: 420px; height: 10px; margin-top: 14px; }}
.track i {{ flex: 1; display: block; }}
.map {{ position: absolute; right: 60px; top: 60px; }}
.rule {{ position: absolute; left: 72px; right: 72px; bottom: 76px; height: 1px; background: #121212; }}
.foot {{ position: absolute; left: 72px; right: 72px; bottom: 36px; display: flex; justify-content: space-between; align-items: baseline; }}
.brand {{ font: 600 24px 'Newsreader'; }}
.brand em {{ font-weight: 500; font-style: italic; }}
.url {{ font: 600 16px 'Libre Franklin'; letter-spacing: 0.09em; text-transform: uppercase; color: #3a3936; }}
</style></head><body><div class="card">
<div class="left">
  <p class="kicker">{e(d["type"] or "Housing project")}</p>
  <h1>{e(d["name"])}</h1>
  <p class="where">{e(where)}</p>
  <div class="facts">
    <div class="homes">{homes}</div>
    <p class="stage"><b></b>{e(stage)}</p>
    {track(d, stages)}
  </div>
</div>
<div class="map">{locator(d, outlines, stages, 400, 430)}</div>
<div class="rule"></div>
<div class="foot"><span class="brand">Spokane <em>in Progress</em></span><span class="url">projects.spokanerising.com</span></div>
</div></body></html>"""


def render(projects, stages, outlines, targets):
    """targets: [(project, output path)]. Draws them with one browser."""
    from playwright.sync_api import sync_playwright
    fonts_css = font_faces()
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for p, out in targets:
            pg.set_content(card_html(p, stages, outlines, fonts_css))
            pg.evaluate("document.fonts.ready")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            pg.screenshot(path=out, type="jpeg", quality=90)
        b.close()


def site_card_inputs(projects, stages):
    """What the site-wide card draws: every project's dot and the stage bar."""
    dots = sorted([p.get("id"), p.get("status"), p.get("units") or 0,
                   round(p["lat"], 4) if isinstance(p.get("lat"), (int, float)) else None,
                   round(p["lng"], 4) if isinstance(p.get("lng"), (int, float)) else None] for p in projects)
    return hashlib.sha1(json.dumps([VERSION, stages, dots]).encode()).hexdigest()[:12]


def run(root=ROOT, redraw_all=False, site_card=True, origin=None):
    """Draws missing or changed cards, removes replaced ones, rewrites the
    pages to point at them, and redraws the site card if it changed."""
    data = json.load(open(os.path.join(root, "projects.json"), encoding="utf-8"))
    projects, stages = data["projects"], data["stages"]
    try:
        outlines = json.load(open(os.path.join(root, "boundaries.geojson"), encoding="utf-8"))
    except (OSError, ValueError):
        outlines = {"features": []}

    todo = [(p, card_path(p, root)) for p in projects
            if os.path.isdir(os.path.join(root, "p", p["id"])) and (redraw_all or not os.path.exists(card_path(p, root)))]
    if todo:
        render(projects, stages, outlines, todo)
    removed = 0
    for p in projects:
        keep = card_name(p)
        for old in glob.glob(os.path.join(root, "p", p["id"], "card-*")):
            if os.path.basename(old) != keep:
                os.remove(old)
                removed += 1
    print(f"Cards: {len(todo)} drawn, {removed} old removed, {len(projects) - len(todo)} unchanged.")

    import pages
    warnings = pages.write_all(projects, root, origin or pages.ORIGIN)

    if site_card:
        mark = os.path.join(root, "data", "site-card.json")
        want = site_card_inputs(projects, stages)
        try:
            have = json.load(open(mark)).get("inputs")
        except (OSError, ValueError):
            have = None
        if have != want or not os.path.exists(os.path.join(root, "og-card.png")):
            import make_site_card
            make_site_card.ROOT, make_site_card.OUT = root, os.path.join(root, "og-card.png")
            make_site_card.main()
            os.makedirs(os.path.dirname(mark), exist_ok=True)
            json.dump({"inputs": want}, open(mark, "w"))
        else:
            print("Site card: no change.")
    return warnings


def main():
    ap = argparse.ArgumentParser(description="Draw the project share cards.")
    ap.add_argument("--only", nargs="+", help="project ids to draw as samples into cards-samples/")
    ap.add_argument("--all", action="store_true", help="redraw every card")
    ap.add_argument("--no-site-card", action="store_true", help="leave og-card.png alone")
    args = ap.parse_args()
    if args.only:
        data = json.load(open(os.path.join(ROOT, "projects.json"), encoding="utf-8"))
        try:
            outlines = json.load(open(os.path.join(ROOT, "boundaries.geojson"), encoding="utf-8"))
        except (OSError, ValueError):
            outlines = {"features": []}
        chosen = [p for p in data["projects"] if p["id"] in args.only]
        render(data["projects"], data["stages"], outlines, [(p, os.path.join(SAMPLES, f"{p['id']}.jpg")) for p in chosen])
        print(f"Drew {len(chosen)} sample card(s) into {SAMPLES}")
        return
    for w in run(ROOT, args.all, not args.no_site_card):
        print("  -", w)


if __name__ == "__main__":
    main()
