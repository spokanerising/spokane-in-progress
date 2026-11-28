"""Small pages for sharing: one per project, neighborhood and council district.

Social sites (Bluesky, Reddit, LinkedIn, X, iMessage, Slack...) don't run
JavaScript, so a link to the map always previews as the generic site. These
pages give each project, neighborhood council and council district its own
address with its own title, description and image in the page's tags, and
send people straight on to the map:

  p/<project id>/   ->  /?p=<project id>
  n/<slug>/         ->  /?hood=<slug>      (a neighborhood council)
  d/<number>/       ->  /?district=<number>

The forwarding is a one-line script, so link-preview crawlers (which don't
run it) read the tags while people land on the map instantly. Without
JavaScript there's a plain link.

A project that leaves the map keeps its page, reworded to say it's no
longer tracked, so links people already shared still go somewhere useful.
sitemap.xml lists the home page, About and every current page.

build.py calls write_all() after writing projects.json. It can also be run
by itself on the current projects.json:

    python3 pages.py                     # links for projects.spokanerising.com
    python3 pages.py --origin https://<branch>.spokane-in-progress.pages.dev

Standard library only.
"""

import argparse
import html
import json
import os
import re

import branding

C = branding.COLORS

SITE_NAME = "Spokane in Progress"
ORIGIN = os.environ.get("SITE_ORIGIN", "https://projects.spokanerising.com").rstrip("/")
CARD = {"path": "/og-card.png", "width": 1200, "height": 630,
        "alt": "Spokane in Progress: a map of Spokane with every tracked housing project as a dot, colored by stage."}
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
GONE_MARK = '<meta name="sip-page" content="gone">'
# A page for something no longer on the map still answers old links, but
# search engines shouldn't list it.
ROBOTS_GONE = '<meta name="robots" content="noindex">'

STAGE_PHRASE = {
    "Pre-Application": "proposed",
    "Applied": "in permit review",
    "Approved": "approved",
    "Under Construction": "under construction",
    "Complete": "complete",
    "Stalled": "stalled",
}
AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]


def slug(text):
    """Same as the map's slug(): lowercase, anything else becomes a hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def ap_date(iso):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return ""
    return f"{AP_MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(1)}"


def plural(n, one, many):
    return f"{n:,} {one if n == 1 else many}"


def stage_inferred(p):
    return p.get("status") == "Under Construction" and "trade permit" in (p.get("stageSource") or "").lower()


# ---------------------------------------------------------------------------
# Words for each page
# ---------------------------------------------------------------------------

def project_description(p):
    """'Conversion or addition with 96 homes, likely under construction.
    10 N Post St, Riverside.' Only what the data holds, nothing guessed."""
    units = p.get("units") if isinstance(p.get("units"), int) and p["units"] > 0 else None
    btype = p.get("buildingType") if p.get("buildingType") not in (None, "", "Not yet known") else ""
    stage = STAGE_PHRASE.get(p.get("status"), (p.get("status") or "").lower())
    if stage_inferred(p):
        stage = "likely under construction"
    elif p.get("statusUpdated") and p.get("stageSinceExact"):
        # Events read with a date ("approved Nov. 17, 2026"); states with "since".
        event = p.get("status") in ("Pre-Application", "Approved", "Complete")
        stage += f"{' ' if event else ' since '}{ap_date(p['statusUpdated'])}"
    what = " with ".join(x for x in [btype, plural(units, "home", "homes") if units else ""] if x)
    first = ", ".join(x for x in [what, stage] if x)
    first = first[:1].upper() + first[1:] if first else ""
    where = ", ".join(x for x in [p.get("address"), p.get("neighborhood") or p.get("neighborhoodCouncil")] if x)
    return " ".join(x for x in [f"{first}." if first else "", f"{where}." if where else ""] if x)


def area_description(name, items):
    homes = sum(p["units"] for p in items if isinstance(p.get("units"), int) and p["units"] > 0)
    building = sum(1 for p in items if p.get("status") == "Under Construction")
    parts = [f"{plural(len(items), 'housing project', 'housing projects')} in {name}"]
    if homes:
        parts[0] += f", with at least {homes:,} homes"
    if building:
        parts.append(f"{building:,} under construction")
    return "; ".join(parts) + ". From first proposals to move-in, tracked by Spokane in Progress."


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def page(*, origin, path, title, description, target, heading, kicker, gone=False, card=None):
    """card: {"path", "width", "height", "alt", "type"} for this page's own
    image (a project card from cards.py); the site card otherwise."""
    e = lambda s: html.escape(str(s), quote=True)
    url = f"{origin}{path}"
    card = card or {**CARD, "type": "image/png"}
    image = f"{origin}{card['path']}"
    full_title = f"{title} · {SITE_NAME}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
{GONE_MARK + chr(10) + ROBOTS_GONE if gone else ""}
<title>{e(full_title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:url" content="{e(url)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:image" content="{e(image)}">
<meta property="og:image:type" content="{card['type']}">
<meta property="og:image:width" content="{card['width']}">
<meta property="og:image:height" content="{card['height']}">
<meta property="og:image:alt" content="{e(card['alt'])}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(description)}">
<meta name="twitter:image" content="{e(image)}">
<meta name="twitter:image:alt" content="{e(card['alt'])}">
<script>location.replace({json.dumps(target)} + location.hash);</script>
<style>
body {{ margin: 0; background: {C["paper"]}; color: {C["ink"]}; font: 17px/1.5 Georgia, "Times New Roman", serif; }}
main {{ max-width: 34rem; margin: 12vh auto; padding: 0 24px; }}
.kicker {{ font: 600 12px/1 system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase; color: {C["muted"]}; }}
h1 {{ margin: .4em 0 .3em; font-size: 2rem; line-height: 1.15; }}
a {{ color: {C["link"]}; font-family: system-ui, sans-serif; font-weight: 600; }}
</style>
</head>
<body>
<main>
<p class="kicker">{e(kicker)}</p>
<h1>{e(heading)}</h1>
<p>{e(description)}</p>
<p><a href="{e(target)}">{"Go to the map" if gone else "See it on the map"} &rarr;</a></p>
</main>
</body>
</html>
"""


def project_card(p, root):
    """The project's own share card, if cards.py has drawn the current one."""
    try:
        import cards   # needs nothing beyond the standard library to import
    except Exception:
        return None
    if not os.path.exists(cards.card_path(p, root)):
        return None
    return {"path": f"/p/{p['id']}/{cards.card_name(p)}", "width": 1200, "height": 630,
            "alt": cards.card_alt(p), "type": "image/jpeg"}


def write_if_changed(path, text):
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def write_all(projects, root=".", origin=ORIGIN):
    """Writes every page and sitemap.xml under root. Returns warnings."""
    origin = origin.rstrip("/")
    warnings, written, current = [], 0, {"p": set(), "n": set(), "d": set()}

    ids = [p.get("id") for p in projects]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        # Two projects would share one page; build.py should have prevented this.
        return [f"Pages not written: duplicate project ids {', '.join(dupes)}."]

    for p in projects:
        pid = p.get("id") or ""
        if not SAFE_ID.match(pid):
            warnings.append(f'{p.get("name")}: id "{pid}" can\'t be a page address; it shares as a ?p= link.')
            continue
        current["p"].add(pid)
        written += write_if_changed(os.path.join(root, "p", pid, "index.html"), page(
            card=project_card(p, root),
            origin=origin, path=f"/p/{pid}/", title=p.get("name") or "Housing project",
            description=project_description(p), target=f"/?p={pid}",
            heading=p.get("name") or "Housing project", kicker=f"{SITE_NAME} · {p.get('status') or ''}".rstrip(" ·"),
        ))

    hoods, districts = {}, {}
    for p in projects:
        if p.get("neighborhoodCouncil"):
            hoods.setdefault(p["neighborhoodCouncil"], []).append(p)
        if isinstance(p.get("councilDistrict"), int):
            districts.setdefault(p["councilDistrict"], []).append(p)
    for name, items in hoods.items():
        s = slug(name)
        current["n"].add(s)
        written += write_if_changed(os.path.join(root, "n", s, "index.html"), page(
            origin=origin, path=f"/n/{s}/", title=f"{name}: housing projects",
            description=area_description(name, items), target=f"/?hood={s}",
            heading=name, kicker=f"{SITE_NAME} · Neighborhood council",
        ))
    for number, items in districts.items():
        current["d"].add(str(number))
        written += write_if_changed(os.path.join(root, "d", str(number), "index.html"), page(
            origin=origin, path=f"/d/{number}/", title=f"City Council District {number}: housing projects",
            description=area_description(f"City Council District {number}", items), target=f"/?district={number}",
            heading=f"City Council District {number}", kicker=f"{SITE_NAME} · City Council district",
        ))

    # A project page whose id is gone, but whose permit is now part of another
    # project (an older permit joined it, or a hand-curated file took it over):
    # forward to that project, so links people shared keep working.
    by_permit = {}
    for p in projects:
        for n in p.get("permitNumbers") or []:
            by_permit.setdefault(str(n).upper(), p)
    def moved_to(name):
        permit = re.sub(r"^(city|monthly)-", "", name).upper()
        if len(permit) < 8:
            return None
        return by_permit.get(permit) or next((p for n, p in by_permit.items() if n.startswith(permit)), None)

    # Pages for things no longer on the map stay, reworded.
    gone = 0
    for kind, what in (("p", "project"), ("n", "neighborhood"), ("d", "district")):
        folder = os.path.join(root, kind)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            index = os.path.join(folder, name, "index.html")
            if name in current[kind] or not os.path.isfile(index):
                continue
            now = moved_to(name) if kind == "p" else None
            if now and SAFE_ID.match(now.get("id") or ""):
                # Same page as the project's own (its address and card), forwarding to it.
                written += write_if_changed(index, page(
                    card=project_card(now, root),
                    origin=origin, path=f"/p/{now['id']}/", title=now.get("name") or "Housing project",
                    description=project_description(now), target=f"/?p={now['id']}",
                    heading=now.get("name") or "Housing project",
                    kicker=f"{SITE_NAME} · {now.get('status') or ''}".rstrip(" ·"),
                ))
                continue
            with open(index, encoding="utf-8") as handle:
                old = handle.read()
            if GONE_MARK in old:
                continue
            m = re.search(r'<meta property="og:title" content="([^"]*)"', old)
            heading = html.unescape(m.group(1)) if m else "This page"
            write_if_changed(index, page(
                origin=origin, path=f"/{kind}/{name}/", title=f"{heading} (no longer tracked)",
                description=f"This {what} is no longer on the Spokane in Progress map. It may have been finished, withdrawn or merged with another entry.",
                target="/", heading=heading, kicker=f"{SITE_NAME} · No longer tracked", gone=True,
            ))
            gone += 1

    # Cloudflare serves stats.html at /stats (and redirects the .html address
    # there), so the sitemap lists the address a page actually lives at.
    urls = [f"{origin}/", f"{origin}/stats", f"{origin}/about", f"{origin}/glossary"]
    urls += [f"{origin}/{kind}/{name}/" for kind in ("p", "n", "d") for name in sorted(current[kind])]
    write_if_changed(os.path.join(root, "sitemap.xml"),
                     '<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                     + "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in urls)
                     + "</urlset>\n")
    total = sum(len(v) for v in current.values())
    print(f"Pages: {total} current ({len(current['p'])} projects, {len(current['n'])} neighborhoods, "
          f"{len(current['d'])} districts), {written} changed, {gone} marked no longer tracked.")
    return warnings


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--origin", default=ORIGIN, help="site address the pages link to")
    ap.add_argument("--root", default=".", help="folder to write into")
    args = ap.parse_args()
    with open(os.path.join(args.root, "projects.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    for w in write_all(data["projects"], args.root, args.origin):
        print("  -", w)
