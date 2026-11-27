"""One look for every control (item 11): heights, corners, borders, toggles,
checkboxes and the focus ring, on a wide screen and a phone, plus the
unlinked style guide page (styleguide.html)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

LINK = "rgb(39, 91, 132)"
INK = "rgb(18, 18, 18)"

# selector -> which size it should be
SIZES = {
    "#search": "ctl", ".chip": "ctl", ".picker__button": "ctl", "#basemap": "ctl",
    ".mapbtn": "ctl", ".maplibregl-ctrl-zoom-in": "ctl",
    "#measure": "sm", "#sort": "sm",
}

STYLE = """(sel) => [...document.querySelectorAll(sel)].filter(e => e.offsetParent || e.getClientRects().length).map(e => {
  const s = getComputedStyle(e), r = e.getBoundingClientRect();
  return {h: Math.round(r.height), radius: s.borderTopLeftRadius};
})"""

def sizes(pg, want):
    for sel, kind in SIZES.items():
        got = pg.evaluate(STYLE, sel)
        check(got, f"{sel} is on the page")
        for g in got:
            check(abs(g["h"] - want[kind]) <= 1, f"{sel} height {g['h']} (want {want[kind]})")
            if sel not in (".maplibregl-ctrl-zoom-in",):
                check(g["radius"] == "2px", f"{sel} corner {g['radius']}")

site, _ = make_site(with_facts=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)
    pg.goto(SITE + "/")
    pg.wait_for_selector(".card")
    pg.wait_for_selector(".maplibregl-ctrl-zoom-in")
    sizes(pg, {"ctl": 36, "sm": 28})

    # Segmented toggles: one ink outline, the chosen part filled with ink.
    for grp, on in [("#measure", "#measure [aria-pressed=true]"), ("#basemap", "#basemap [aria-pressed=true]")]:
        s = pg.eval_on_selector(grp, "e => { const s = getComputedStyle(e); return [s.borderTopColor, s.borderTopWidth, s.borderTopLeftRadius]; }")
        check(s == [INK, "1px", "2px"], f"{grp} outline {s}")
        bg = pg.eval_on_selector(on, "e => getComputedStyle(e).backgroundColor")
        check(bg == INK, f"{on} filled {bg}")

    # The focus ring: blue, 2px, from the keyboard.
    pg.keyboard.press("Tab")
    for sel in ["#search", ".chip", "#sort", "#inview-only", "#share-view", ".mapbtn", "#basemap button"]:
        pg.focus(sel)
        st = pg.eval_on_selector(sel, "e => { const s = getComputedStyle(e); return [e.matches(':focus-visible'), s.outlineStyle, s.outlineWidth, s.outlineColor]; }")
        check(st[0] and st[1] == "solid" and st[2] == "2px", f"{sel} focus ring {st}")
        # the selected toggle part uses a paper ring so it shows on ink
        if sel != "#basemap button":
            check(st[3] == LINK, f"{sel} ring colour {st[3]}")

    # Checkboxes: the site's own square, ink when ticked, a dash when partly ticked.
    pg.locator(".picker__button").first.click()
    pg.wait_for_selector(".picker__panel .picker__item input")
    cb = pg.eval_on_selector(".picker__panel .picker__item:not(.picker__item--group) input",
                             "e => { const s = getComputedStyle(e); return [s.appearance, s.width, s.backgroundColor, e.checked]; }")
    check(cb[0] == "none" and cb[1] == "15px", f"custom checkbox {cb}")
    check(cb[3] and cb[2] == INK, f"ticked box is ink {cb}")
    pg.locator(".picker__panel .picker__item:not(.picker__item--group) .picker__text").first.click()
    tri = pg.eval_on_selector(".picker__panel .picker__item--group input",
                              "e => [e.indeterminate, getComputedStyle(e).backgroundImage.includes('svg')]")
    check(tri == [True, True], f"group box shows a dash {tri}")
    quick = pg.eval_on_selector_all(".picker__panel .picker__quick button", "els => els.map(e => e.getClientRects().length)")
    check(all(n == 1 for n in quick), f"All/None links stay on one line {quick}")
    pg.screenshot(path=os.path.join(os.path.dirname(__file__), ".shots", "controls-desktop.png"))

    # The style guide renders every family without errors.
    pg.goto(SITE + "/styleguide.html")
    for sel in [".button", ".chip", ".picker__button", ".sort select", ".measure", ".seg", ".basemap", ".mapbtn",
                ".picker__item input", ".pill", ".iconbtn", ".sharebtn", ".menu", ".toast"]:
        check(pg.locator(sel).count() > 0, f"style guide shows {sel}")
    check(pg.eval_on_selector('meta[name="robots"]', "e => e.content") == "noindex", "style guide is noindex")
    pg.screenshot(path=os.path.join(os.path.dirname(__file__), ".shots", "styleguide.png"), full_page=True)

    # Phones: everything grows to 40px (36px small).
    m = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    m.on("pageerror", lambda e: errors.append(str(e)))
    wire(m, site)
    m.goto(SITE + "/")
    m.wait_for_selector(".maplibregl-ctrl-zoom-in")
    m.locator('.viewswitch [data-view="list"]').tap()
    m.locator("#more-filters").tap()
    for sel, want in [("#search", 40), (".chip", 40), (".picker__button", 40), ("#measure", 36), ("#sort", 36),
                      ("#more-filters", 40)]:
        hs = m.eval_on_selector_all(sel, "els => els.filter(e => e.getClientRects().length).map(e => Math.round(e.getBoundingClientRect().height))")
        check(hs and all(abs(h - want) <= 1 for h in hs), f"phone {sel} heights {hs} (want {want})")
    m.locator('.viewswitch [data-view="map"]').tap()
    for sel in ["#basemap", ".mapbtn", ".maplibregl-ctrl-zoom-in"]:
        hs = m.eval_on_selector_all(sel, "els => els.map(e => Math.round(e.getBoundingClientRect().height))")
        check(hs and all(abs(h - 40) <= 1 for h in hs), f"phone {sel} heights {hs}")
    w = m.evaluate("() => document.documentElement.scrollWidth")
    check(w <= 390, f"no sideways scroll on a phone ({w}px)")

    check(not errors, f"page errors: {errors}")
    b.close()

print(f"{ok} checks passed")
