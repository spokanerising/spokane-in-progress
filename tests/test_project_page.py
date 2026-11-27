"""The project page (polish round, phase E): kicker and standfirst, specs in
sections that only appear when they have something, the permits table, the
satellite view when there's no image, PDF thumbnails (pdf_thumbs.py), the
foot, links to a section, printing and phones."""
import io, json, os, shutil, sys, tempfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import make_site, wire, SITE
from playwright.sync_api import sync_playwright
from PIL import Image
import pdf_thumbs

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

SHOTS = os.path.join(os.path.dirname(__file__), ".shots")

# ---- pdf_thumbs.py, offline ---------------------------------------------------
def make_pdf(pages, color):
    ims = [Image.new("RGB", (850, 1100), color) for _ in range(pages)]
    buf = io.BytesIO(); ims[0].save(buf, "PDF", save_all=True, append_images=ims[1:]); return buf.getvalue()

root = tempfile.mkdtemp(prefix="thumbs-")
if not (shutil.which("pdftoppm") and shutil.which("pdfinfo")):
    # Without poppler: no thumbnails, one warning each, nothing downloaded.
    calls_np = []
    nop = [{"id": "A1", "name": "Has permission", "docUrl": "https://example.org/a.pdf", "_docThumbOk": True}]
    w = pdf_thumbs.add(nop, root, fetch=lambda u: calls_np.append(u))
    check("docThumb" not in nop[0] and "_docThumbOk" not in nop[0] and not calls_np and "poppler" in w[0], "fails soft without poppler")
    print("poppler not installed: skipping the thumbnail drawing checks")
    skip_thumbs = True
else:
    skip_thumbs = False
pdf = make_pdf(3, (200, 60, 40)) if not skip_thumbs else b""
if not skip_thumbs:
    calls = []
    def fake_fetch(url):
        calls.append(url)
        if "broken" in url: raise ValueError("not a PDF")
        return DOCS[url]
    DOCS = {"https://example.org/a.pdf": pdf}
    projects = [
        {"id": "A1", "name": "Has permission", "docUrl": "https://example.org/a.pdf", "_docThumbOk": True},
        {"id": "B2", "name": "No permission", "docUrl": "https://example.org/a.pdf", "_docThumbOk": False},
        {"id": "C3", "name": "Broken", "docUrl": "https://example.org/broken.pdf", "_docThumbOk": True},
        {"id": "D4", "name": "No document"},
    ]
    now = datetime(2026, 11, 27, tzinfo=timezone.utc)
    warns = pdf_thumbs.add(projects, root, now=now, fetch=fake_fetch)
    a, b_, c, d = projects
    check(all("_docThumbOk" not in p for p in projects), "internal flag removed from every project")
    check(a.get("docThumb", "").startswith("/p/A1/doc-") and a["docThumb"].endswith(".jpg") and a.get("docPages") == 3, a)
    im = Image.open(os.path.join(root, a["docThumb"].lstrip("/")))
    check(im.size[0] == 600 and im.format == "JPEG", f"600 wide JPEG {im.size}")
    check("docThumb" not in b_ and "docThumb" not in c and "docThumb" not in d, "no thumbnail without permission, on failure, or without a PDF")
    check(len(warns) == 1 and "Broken" in warns[0], warns)
    check(calls.count("https://example.org/a.pdf") == 1, "PDFs without permission aren't downloaded")
    # Next day: cached, not fetched again.
    calls.clear()
    again = [{"id": "A1", "name": "x", "docUrl": "https://example.org/a.pdf", "_docThumbOk": True}]
    pdf_thumbs.add(again, root, now=now + timedelta(days=1), fetch=fake_fetch)
    check(not calls and again[0]["docThumb"] == a["docThumb"], "cached for a month")
    # After a month, with a changed PDF: redrawn under a new name, old file removed.
    DOCS["https://example.org/a.pdf"] = make_pdf(5, (40, 60, 200))
    later = [{"id": "A1", "name": "x", "docUrl": "https://example.org/a.pdf", "_docThumbOk": True}]
    pdf_thumbs.add(later, root, now=now + timedelta(days=40), fetch=fake_fetch)
    check(later[0]["docThumb"] != a["docThumb"] and later[0]["docPages"] == 5, "redrawn when the PDF changes")
    check(not os.path.exists(os.path.join(root, a["docThumb"].lstrip("/"))), "old thumbnail removed")
shutil.rmtree(root)

# ---- the page -------------------------------------------------------------------
site, _ = make_site(with_facts=True)
data = json.load(open(os.path.join(site, "projects.json")))
P = data["projects"]
big = max(P, key=lambda p: len(p["permits"]))
plain = next(p for p in P if not any(f["label"] in ("Developer", "Architect", "Estimated cost") for f in p["fields"]) and p["permits"])
# Give one project an image and one a PDF with a thumbnail, to see both.
pic = next(p for p in P if p["id"] not in (big["id"], plain["id"]))
pic["imageUrl"] = "/og-card.png"; pic["imageCredit"] = "Test"
docp = next(p for p in P if p["id"] not in (big["id"], plain["id"], pic["id"]))
docp["docUrl"] = "https://example.org/plans.pdf"; docp["docLabel"] = "Design review packet"; docp["docThumb"] = "/og-card.png"; docp["docPages"] = 12
json.dump(data, open(os.path.join(site, "projects.json"), "w"))

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    tiles = []
    wire(pg, site)
    pg.on("request", lambda r: tiles.append(r.url) if "arcgisonline" in r.url else None)

    pg.goto(f"{SITE}/?p={big['id']}")
    pg.wait_for_selector(".ptable")
    body = pg.locator("#detail-body")

    # Top of the page.
    kicker = pg.locator(".pkicker").inner_text()
    check(big["buildingType"].upper() in kicker.upper(), kicker)
    if big.get("middleHousing"):
        check("MIDDLE HOUSING" in kicker.upper(), kicker)
    sf = pg.locator(".standfirst").inner_text()
    check(sf.endswith(".") and (str(big["units"]) in sf if big.get("units") else True), sf)

    # Sections, in order, each with a heading and an anchor.
    ids = pg.eval_on_selector_all("#detail-body .psec", "els => els.map(e => e.id)")
    order = ["building", "site", "people", "progress"]
    check(ids == [i for i in order if i in ids] and "building" in ids and "progress" in ids, ids)
    heads = pg.eval_on_selector_all("#detail-body .psec__hed", "els => els.map(e => e.textContent)")
    check(len(heads) == len(ids), heads)
    check(pg.locator("#site dt", has_text="Zoning").count() == 1, "zoning under The site")
    check(pg.locator("#building dt", has_text="Building type").count() == 1, "building type under The building")
    check(pg.locator("#detail-body dt", has_text="Source").count() == 0, "source moved to the foot")
    check(pg.locator("#detail-body dt", has_text="Permit application").count() == 0, "permit link moved into the table")

    # Permits table: every permit, newest first, six at a time.
    rows = pg.locator(".ptable tbody tr")
    check(rows.count() == len(big["permits"]), f"{rows.count()} rows")
    visible = pg.eval_on_selector_all(".ptable tbody tr", "els => els.filter(e => !e.hidden).length")
    check(visible == min(6, len(big["permits"])), f"{visible} shown at first")
    dates = pg.eval_on_selector_all(".ptable tbody time", "els => els.map(e => e.getAttribute('datetime'))")
    check(dates == sorted(dates, reverse=True), "newest first")
    links = pg.eval_on_selector_all(".ptable tbody th a", "els => els.map(e => [e.textContent, e.href, e.target])")
    want = {x["id"]: x["url"] for x in big["permits"]}
    check(all(want[t] == h and tg == "_blank" for t, h, tg in links), "each permit links to the city's record")
    kinds = pg.eval_on_selector_all(".ptable__kind", "els => els.map(e => e.textContent)")
    check("New building (commercial)" in kinds or all(k for k in kinds), kinds[:3])
    if len(big["permits"]) > 6:
        btn = pg.locator("[data-show-permits]")
        check(btn.inner_text() == f"Show all {len(big['permits'])} permits", btn.inner_text())
        pg.emulate_media(media="print")
        check(pg.eval_on_selector_all(".ptable tbody tr", "els => els.filter(e => getComputedStyle(e).display !== 'none').length") == len(big["permits"]), "print shows every permit")
        pg.emulate_media(media="screen")
        btn.click()
        check(pg.eval_on_selector_all(".ptable tbody tr", "els => els.filter(e => !e.hidden).length") == len(big["permits"]) and pg.locator("[data-show-permits]").count() == 0, "Show all")
    table_w = pg.eval_on_selector(".ptable", "e => [e.scrollWidth, e.parentElement.clientWidth]")
    check(table_w[0] <= table_w[1] + 1, f"table fits the panel {table_w}")

    # Satellite view (no image): a map in the picture slot, centered on the pin.
    pg.wait_for_selector("#site-map canvas")
    check(tiles, "satellite tiles requested")
    cap = pg.locator(".sitemap figcaption").inner_text()
    check("Satellite view" in cap and "Esri" in cap, cap)
    pin = pg.locator(".sitemap__pin").bounding_box(); box = pg.locator("#site-map").bounding_box()
    check(abs((pin["x"] + pin["width"] / 2) - (box["x"] + box["width"] / 2)) < 3 and abs((pin["y"] + pin["height"] / 2) - (box["y"] + box["height"] / 2)) < 3, f"pin centered {pin} {box}")
    check(abs(box["width"] / box["height"] - 16 / 9) < 0.05, "16:9")
    check(pg.evaluate("!siteView.isMoving() && !siteView.scrollZoom.isEnabled() && !siteView.dragPan.isEnabled()"), "a still picture, not a second map to scroll")

    # The foot.
    fix = pg.locator(".pfoot__fix a").get_attribute("href")
    check(fix.startswith("mailto:spokanerising@gmail.com?subject=Correction"), fix)
    foot = pg.locator(".pfoot").inner_text()
    check("Data as of" in foot and "This page displays available information at the time of project entry." in foot, foot)
    pg.screenshot(path=os.path.join(SHOTS, "project-desktop.png"))

    # Closing removes the satellite map.
    pg.locator("#detail-close").click()
    check(pg.evaluate("siteView") is None, "satellite view removed on close")

    # An empty section doesn't appear.
    pg.goto(f"{SITE}/?p={plain['id']}")
    pg.wait_for_selector(".psec")
    check(pg.locator("#people").count() == 0, "no 'Who's behind it' without developer, architect or cost")

    # A project with its own image: the image, no satellite view.
    pg.goto(f"{SITE}/?p={pic['id']}")
    pg.wait_for_selector(".pfig img")
    check(pg.locator("#site-map").count() == 0, "image instead of the satellite view")
    check("Image: Test" in pg.locator(".pfig figcaption").inner_text(), "image credit")

    # A PDF with a thumbnail.
    pg.goto(f"{SITE}/?p={docp['id']}")
    pg.wait_for_selector(".doc--thumb")
    check(pg.locator(".doc__thumb").get_attribute("src") == "/og-card.png", "thumbnail shown")
    check("12 pages · PDF" in pg.locator(".doc").inner_text(), pg.locator(".doc").inner_text())

    # A link to a section scrolls the project to it.
    pg.goto(f"{SITE}/?p={big['id']}#permits")
    pg.wait_for_selector(".ptable")
    pg.wait_for_timeout(300)
    top = pg.evaluate("document.getElementById('permits').getBoundingClientRect().top - document.getElementById('detail').getBoundingClientRect().top")
    check(0 <= top < 140, f"#permits scrolled into view ({top}px from the top)")
    check(pg.evaluate("location.search + location.hash") == f"?p={big['id']}#permits", "a shared link keeps its address after loading")

    # Phone: fits, 4:3 picture.
    m = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    m.on("pageerror", lambda e: errors.append(str(e)))
    wire(m, site)
    m.goto(f"{SITE}/?p={big['id']}")
    m.wait_for_selector("#site-map canvas")
    bx = m.locator("#site-map").bounding_box()
    check(abs(bx["width"] / bx["height"] - 4 / 3) < 0.05, "4:3 on phones")
    w = m.evaluate("[document.getElementById('detail').scrollWidth, document.getElementById('detail').clientWidth]")
    check(w[0] <= w[1], f"no sideways scroll in the project {w}")
    m.screenshot(path=os.path.join(SHOTS, "project-phone.png"), full_page=True)

    check(not errors, f"page errors: {errors}")
    b.close()

print(f"{ok} checks passed")
