"""Hover card (issue #2), glossary and "How to read this map" (issue #4).

Hover card: stage, name, homes and type, address on hover and on [ / ];
none on touch screens. Glossary: every id the page can ask for exists in
glossary.json, terms open and close by click, hover and Escape, and the
Glossary page lists every term with an anchor. How to read: opens, lists the stages,
Escape returns focus."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, REPO
from playwright.sync_api import sync_playwright

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

SHOTS = os.path.join(os.path.dirname(__file__), ".shots")
os.makedirs(SHOTS, exist_ok=True)
READY = "typeof map !== 'undefined' && map && map.loaded() && map.getSource('projects') && state.list"
GLOSS = json.load(open(os.path.join(REPO, "glossary.json")))
IDS = {t["id"] for g in GLOSS["groups"] for t in g["terms"]}
check(len(IDS) == sum(len(g["terms"]) for g in GLOSS["groups"]), "glossary ids are unique")
check(all(t["definition"].strip() and t["term"].strip() for g in GLOSS["groups"] for t in g["terms"]), "every term has a definition")

site, data = make_site(with_facts=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)
    pg.goto(SITE + "/")
    pg.wait_for_function(READY)
    pg.wait_for_timeout(300)

    # ---- hover card ----------------------------------------------------------
    # A big project with a type and an address, zoomed in so nothing overlaps it.
    pid = pg.evaluate("""() => state.onMap.filter(p => p.units > 20 && p.address && p.buildingType && p.buildingType !== UNKNOWN_TYPE)
        .sort((a, z) => z.units - a.units)[0].id""")
    p = next(x for x in data["projects"] if x["id"] == pid)
    pg.evaluate("(id) => { const p = state.projects.find(x => x.id === id); map.jumpTo({center: [p.lng, p.lat], zoom: 17}); }", pid)
    pg.wait_for_function("!map.isMoving() && map.loaded()")
    pg.wait_for_timeout(200)
    box = pg.locator("#map canvas").bounding_box()
    pt = pg.evaluate("(id) => { const p = state.projects.find(x => x.id === id); const q = map.project([p.lng, p.lat]); return [q.x, q.y]; }", pid)
    pg.mouse.move(box["x"] + pt[0] + 1, box["y"] + pt[1] + 1)
    pg.wait_for_selector(".tipcard", timeout=3000)
    card = pg.locator(".tipcard")
    check(card.locator(".tipcard__name").inner_text() == p["name"], "card shows the name")
    facts = card.locator(".tipcard__facts").inner_text()
    check(facts == f'{p["units"]:,} homes · {p["buildingType"]}', f"card shows homes and type: {facts}")
    check(p["address"] in card.locator(".tipcard__where").inner_text(), "card shows the address")
    check(card.locator(".tipcard__stage").inner_text().strip().lower() == p["status"].lower(), "card shows the stage")
    check(pg.evaluate("hovered") == pid, "the dot is ringed")
    cb = card.bounding_box()
    check(cb["width"] <= 290 and cb["x"] >= 0 and cb["x"] + cb["width"] <= 1280, f"card is a sensible size {cb}")
    pg.screenshot(path=os.path.join(SHOTS, "hover-card.png"), clip={"x": box["x"] + pt[0] - 200, "y": box["y"] + pt[1] - 160, "width": 420, "height": 220})
    pg.mouse.move(box["x"] + 5, box["y"] + box["height"] - 5)
    pg.wait_for_function("!document.querySelector('.tipcard')")
    check(True, "card goes when the pointer leaves")

    # A project without a unit count or type: no empty lines.
    bare = pg.evaluate("tipHtml({name: 'Test', status: 'Applied', units: 0})")
    check("tipcard__facts" not in bare and "tipcard__where" not in bare, "empty lines don't render")
    check("&lt;b&gt;" in pg.evaluate("tipHtml({name: '<b>x</b>', status: 'Applied'})"), "the name is escaped")

    # Keyboard stepping shows the same card.
    pg.evaluate("map.getCanvas().focus()")
    pg.keyboard.press("]")
    pg.wait_for_selector(".tipcard")
    stepped = pg.evaluate("hovered")
    check(pg.locator(".tipcard__name").inner_text() == pg.evaluate("(id) => state.projects.find(x => x.id === id).name", stepped), "stepping shows the card")
    pg.keyboard.press("Escape")

    # ---- glossary: every id the page can produce exists ----------------------
    used = pg.evaluate("""() => {
        const out = new Set();
        state.projects.forEach(p => {
          out.add(Gloss.stage(p.status)); out.add(Gloss.type(p.buildingType));
          (p.permits || []).forEach(x => { out.add(Gloss.permitKind(x.type)); out.add(Gloss.permitStatus(x.status)); });
        });
        STAGES.forEach(s => out.add(Gloss.stage(s.name)));
        out.add(Gloss.type("Middle housing"));
        out.delete("");
        return [...out];
    }""")
    missing = sorted(set(used) - IDS)
    check(not missing, f"glossary has every term the page uses: missing {missing}")
    unmapped = pg.evaluate("""() => [...new Set(state.projects.flatMap(p => (p.permits || []).map(x => x.status)))]
        .filter(s => s && !Gloss.permitStatus(s))""")
    check(len(unmapped) <= 3, f"almost every permit status has a definition; unmapped: {unmapped}")

    # ---- glossary on a project page -------------------------------------------
    gid = pg.evaluate("""() => state.projects.find(p => (p.permits || []).some(x => /^final/i.test(x.status)) && p.buildingType === 'Townhomes'
        || (p.permits || []).some(x => /^final/i.test(x.status)))?.id""")
    pg.evaluate("(id) => select(id, false)", gid)
    pg.wait_for_selector("#detail:not([hidden]) .ptable")
    check(pg.locator("#detail .track__label .gloss").count() == 1, "the stage is a term")
    final = pg.locator('#detail .ptable .gloss[data-gloss="finaled"]').first
    check(final.count() == 1, "a Final status is a term")
    # Fonts settled and the term mid-screen, so the popover has room either side.
    pg.evaluate("document.fonts.ready")
    final.evaluate("e => e.scrollIntoView({block: 'center'})")
    final.click()
    pop = pg.locator(".glosspop")
    pg.wait_for_selector(".glosspop:not([hidden])")
    check(pop.locator(".glosspop__term").inner_text() == "Final (finaled)", "popover shows the term")
    check("final inspection" in pop.locator(".glosspop__def").inner_text(), "and its definition")
    check(final.get_attribute("aria-expanded") == "true", "term says it's open")
    check(pop.locator("a").get_attribute("href") == "/glossary#g-finaled", "links to the Glossary page")
    pb, fb = pop.bounding_box(), final.bounding_box()
    # Under the term, or above it when the term is near the bottom of the window.
    below = abs(pb["y"] - (fb["y"] + fb["height"])) < 12
    above = abs((pb["y"] + pb["height"]) - fb["y"]) < 12
    check(pb["x"] >= 0 and pb["x"] + pb["width"] <= 1280 and (below or above), f"popover next to the term {pb} {fb}")
    pg.screenshot(path=os.path.join(SHOTS, "glossary-popover.png"))
    # Still open when Escape is pressed: if something closed it first (the page
    # shifting as a picture loads), Escape would close the project instead, and
    # the failure would blame the wrong thing (issue #41).
    check(pop.is_visible() and final.get_attribute("aria-expanded") == "true", "popover still open before Escape")
    pg.keyboard.press("Escape")
    pg.wait_for_selector(".glosspop", state="hidden")
    check(pg.locator("#detail").is_visible(), "Escape closes the popover, not the project")
    check(pg.evaluate("document.activeElement.dataset.gloss") == "finaled", "focus goes back to the term")
    # Keyboard: Enter opens; clicking elsewhere closes.
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".glosspop:not([hidden])")
    pg.mouse.click(1270, 890)
    pg.wait_for_selector(".glosspop", state="hidden")
    # Hover opens after a pause and closes on leaving.
    stage = pg.locator("#detail .track__label .gloss")
    stage.hover()
    pg.wait_for_selector(".glosspop:not([hidden])", timeout=2000)
    pg.mouse.move(5, 890)
    pg.wait_for_selector(".glosspop", state="hidden", timeout=2000)
    pg.keyboard.press("Escape")

    # ---- How to read this map ------------------------------------------------
    pg.wait_for_selector("#detail", state="hidden")
    pg.click("#how-to-read")
    panel = pg.locator("#howto")
    check(panel.is_visible(), "the panel opens")
    check(pg.locator("#how-to-read").get_attribute("aria-expanded") == "true", "button says it's open")
    check(pg.locator("#howto-stages li").count() == pg.evaluate("STAGES.length"), "every stage listed")
    check(pg.locator("#howto-stages .gloss").count() == pg.evaluate("STAGES.length"), "stages are terms")
    check(pg.evaluate("document.activeElement.id") == "howto", "focus moves to the panel")
    check(pg.locator(".howto__hover").is_visible() and not pg.locator(".howto__touch").is_visible(), "mouse wording on desktop")
    hb = panel.bounding_box(); mb = pg.locator("#map").bounding_box()
    check(hb["y"] + hb["height"] <= mb["y"] + mb["height"] and hb["x"] >= mb["x"], f"panel inside the map {hb}")
    pg.screenshot(path=os.path.join(SHOTS, "how-to-read.png"))
    pg.keyboard.press("Escape")
    check(not panel.is_visible() and pg.evaluate("document.activeElement.id") == "how-to-read", "Escape closes and returns focus")

    # ---- Glossary page list (an old About link forwards to it) ----------------
    pg.goto(SITE + "/about.html#g-finaled")
    pg.wait_for_url("**/glossary#g-finaled")
    pg.wait_for_selector("#glossary dt")
    check(pg.locator("#glossary dt").count() == len(IDS), "the Glossary lists every term")
    check(pg.locator("#g-finaled.is-target").count() == 1, "the linked term is marked")
    check(pg.evaluate("document.getElementById('g-finaled').getBoundingClientRect().top") < 300, "and scrolled to")
    check(not errors, errors)

    # ---- phones: no hover card, tap opens; touch wording ---------------------
    m = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    mp = m.new_page()
    merr = []
    mp.on("pageerror", lambda e: merr.append(str(e)))
    wire(mp, site)
    mp.goto(SITE + "/")
    mp.wait_for_function(READY)
    mp.evaluate("(id) => { const p = state.projects.find(x => x.id === id); map.jumpTo({center: [p.lng, p.lat], zoom: 17}); }", pid)
    mp.wait_for_function("!map.isMoving() && map.loaded()")
    mp.wait_for_timeout(200)
    mbox = mp.locator("#map canvas").bounding_box()
    q = mp.evaluate("(id) => { const p = state.projects.find(x => x.id === id); const q = map.project([p.lng, p.lat]); return [q.x, q.y]; }", pid)
    mp.touchscreen.tap(mbox["x"] + q[0], mbox["y"] + q[1])
    mp.wait_for_selector("#detail:not([hidden])")
    check(mp.locator(".tipcard").count() == 0, "no hover card on a phone")
    mp.evaluate("closeDetailAndReturn ? closeDetailAndReturn() : null")
    mp.click("#how-to-read")
    check(mp.locator(".howto__touch").is_visible() and not mp.locator(".howto__hover").is_visible(), "touch wording on phones")
    hb = mp.locator("#howto").bounding_box()
    check(hb["x"] >= 0 and hb["x"] + hb["width"] <= 390, f"panel fits the phone {hb}")
    mp.screenshot(path=os.path.join(SHOTS, "how-to-read-phone.png"))
    check(not merr, merr)
    b.close()
print(f"{ok} checks passed")
