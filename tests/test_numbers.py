"""Bold numbers (issue #42, numbers.js): quantities are wrapped in <b class="num">
wherever the site states them, and dates, years, addresses, names and codes
are left alone."""
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

site, data = make_site(with_facts=True)
P = data["projects"]
# A project with units, a street-number address and an exact stage date.
p = next(x for x in P if x.get("units") and x.get("units") > 9 and x.get("address", "")[:1].isdigit() and x.get("stageSinceExact"))

BOLD = "sel => [...document.querySelectorAll(sel + ' b')].map(b => b.textContent)"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)
    pg.goto(f"{SITE}/")
    pg.wait_for_selector(".card")
    pg.wait_for_timeout(300)

    lede = pg.evaluate(BOLD, ".lede")
    check(lede and all(any(c.isdigit() for c in n) for n in lede), f"headline sentence numbers are bold: {lede}")
    check(len(pg.evaluate(BOLD, ".spine__key")) >= 5, "every stage total in the header key is bold")
    check(pg.evaluate("getComputedStyle(document.querySelector('.spine__key b')).fontWeight") == "800", "header key totals are extra bold")
    chips = pg.evaluate(BOLD, ".chip__n")
    check(len(chips) == pg.evaluate("document.querySelectorAll('.chip__n').length"), f"chip counts bold: {chips}")
    check(pg.evaluate(BOLD, ".tally"), "the list tally's numbers are bold")
    # Text reads the same with or without the wrapping.
    check(pg.evaluate("document.querySelector('.chip__n').textContent.trim() === String(+document.querySelector('.chip__n').textContent)"), "chip count text unchanged")
    # Names and addresses in the list stay plain.
    check(not pg.evaluate("document.querySelector('.card__name b.num, .card__where b.num')"), "no bold numbers in list names or addresses")

    # The project page: units bold, the date and the address plain.
    pg.goto(f"{SITE}/?p={p['id']}")
    pg.wait_for_selector(".standfirst")
    pg.wait_for_timeout(300)
    stand = pg.evaluate(BOLD, ".standfirst")
    check(f"{p['units']:,}" in stand, f"standfirst units bold: {stand}")
    check(not any(len(n) == 4 and n.startswith("20") for n in stand), f"no years bolded: {stand}")
    check(not pg.evaluate("[...document.querySelectorAll('.detail b.num')].some(b => b.closest('h2, .pkicker, .addr, .detail__where'))"), "name, kicker and address stay plain")
    units_dd = pg.evaluate("""(() => { const dt = [...document.querySelectorAll('.specs dt')].find(d => /^housing units$/i.test(d.textContent.trim()));
                                       return dt ? [...dt.nextElementSibling.querySelectorAll('b.num')].map(b => b.textContent) : null; })()""")
    check(units_dd is None or units_dd, f"housing units spec bold: {units_dd}")
    zone = pg.evaluate("""(() => { const dt = [...document.querySelectorAll('.specs dt')].find(d => /^zoning$/i.test(d.textContent.trim()));
                                   return dt ? dt.nextElementSibling.querySelectorAll('b.num').length : 0; })()""")
    check(zone == 0, "zoning codes stay plain")

    # Stats: big numbers and chart values.
    pg.goto(f"{SITE}/stats.html")
    pg.wait_for_selector(".bars__value")
    pg.wait_for_timeout(300)
    check(pg.evaluate("document.querySelectorAll('.bars__value b.num, .bars__value > b').length") > 5, "chart values bold")
    check(not errors, f"page errors: {errors}")
    b.close()

print(f"{ok} checks passed")
