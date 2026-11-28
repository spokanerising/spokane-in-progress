"""Reads brand/brand.json, the one place for the site's colors, stage colors,
fonts, names and logos. Python scripts (build, cards, pages, icons) import this
instead of typing colors themselves. Standard library only.

    import branding
    branding.COLORS["ink"]      -> "#121212"
    branding.STAGES             -> [{"name": "Pre-Application", "color": "#ce5c11"}, ...]
    branding.rgba("paper", 0.9) -> "rgba(250, 248, 243, 0.9)"
"""
import base64
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "brand", "brand.json")
HEX = re.compile(r"^#[0-9a-f]{6}$")


def load(path=PATH):
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    # A color may name another color ("link": "brand") to reuse it.
    for name, c in b["colors"].items():
        seen = [name]
        while not HEX.match(c["value"]) and c["value"] in b["colors"] and c["value"] not in seen:
            seen.append(c["value"])
            c["value"] = b["colors"][c["value"]]["value"]
        if not HEX.match(c["value"]):
            raise ValueError(f"brand.json: color {name!r} must be a 6-digit lowercase hex like #1a2b3c, or another color's name, not {c['value']!r}")
    for s in b["stages"]:
        if not HEX.match(s["color"]):
            raise ValueError(f"brand.json: stage {s['name']!r} must be a 6-digit lowercase hex, not {s['color']!r}")
    return b


BRAND = load()
COLORS = {name: c["value"] for name, c in BRAND["colors"].items()}
# What travels in projects.json: name and color only.
STAGES = [{"name": s["name"], "color": s["color"]} for s in BRAND["stages"]]
STAGE_COLOR = {s["name"]: s["color"] for s in STAGES}
FALLBACK_STAGE_COLOR = STAGES[-1]["color"]   # Stalled's gray, for anything unrecognized
FONTS = BRAND["fonts"]


def rgb(name_or_hex):
    h = COLORS.get(name_or_hex, name_or_hex).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(name_or_hex, alpha):
    r, g, b = rgb(name_or_hex)
    return f"rgba({r}, {g}, {b}, {alpha})"


def stage_color(name):
    return STAGE_COLOR.get(name, FALLBACK_STAGE_COLOR)


def logo_svg(key="main"):
    with open(os.path.join(HERE, BRAND["logo"][key]), encoding="utf-8") as f:
        return f.read()


def logo_data_uri(key="main"):
    """A logo as a data: URL, for images drawn outside the site (share cards)."""
    return "data:image/svg+xml;base64," + base64.b64encode(logo_svg(key).encode()).decode()


# Changes whenever anything a drawn image shows from the brand changes (colors,
# stages, fonts, the logo), so share cards redraw themselves after a reskin.
FINGERPRINT = hashlib.sha1(json.dumps(
    [COLORS, STAGES, FONTS, logo_svg("main")], sort_keys=True).encode()).hexdigest()[:10]
