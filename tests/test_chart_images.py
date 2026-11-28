"""Phase 5 of the sharing plan: each About chart downloads as an image
(PNG), an SVG and its data (CSV), drawn from the same numbers the page
shows, with the chart's title, note, source and the site's name."""
import csv, io, os, sys, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, SHOTS, REPO
sys.path.insert(0, REPO)
import branding  # noqa: E402
from playwright.sync_api import sync_playwright
from PIL import Image

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

os.makedirs(SHOTS, exist_ok=True)

def open_menu(tools):
    """Open a chart's download menu, clicking again if the first click landed
    while the page was still scrolling it into view."""
    btn = tools.locator(".iconbtn")
    tools.page.wait_for_function("!document.querySelector('.menu:not([hidden])')", timeout=5000)
    for _ in range(3):
        btn.click()
        try:
            tools.page.wait_for_function("b => b.getAttribute('aria-expanded') === 'true'", arg=btn.element_handle(), timeout=2000)
            return
        except Exception:
            pass
    raise AssertionError("the download menu didn't open")
site, data = make_site()
P = data["projects"]
stage_colors = [tuple(int(s["color"][i:i + 2], 16) for i in (1, 3, 5)) for s in data["stages"][:5]]
units = lambda p: p["units"] if (p.get("units") or 0) > 0 else 0

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    logs = []
    pg.on("console", lambda m: logs.append(f"{m.type}: {m.text[:300]}"))
    wire(pg, site); pg.goto(f"{SITE}/stats.html")
    pg.wait_for_selector("#chart-quarter .chart__tools")
    # Smooth scrolling lets a click land while the page is still moving.
    pg.add_style_tag(content="html { scroll-behavior: auto !important; }")
    IDS = ["stage", "top", "size", "type", "middle", "density", "district", "hood", "zone", "transit", "quarter"]
    check(pg.locator(".chart__tools").count() == len(IDS), f"a download button under each of the {len(IDS)} charts")
    check(pg.locator(".chart__tools .iconbtn[aria-label='Download this chart']").count() == len(IDS), "each is a labelled icon")
    check(pg.locator("#chart-history").is_hidden(), "no pipeline-over-time chart without 30 days of history")
    pg.locator("#chart-district").screenshot(path=f"{SHOTS}/p5-page-district.png")

    counted = [p for p in P if units(p)]
    expect_rows = {"type": None, "district": len({p["councilDistrict"] for p in P if p.get("councilDistrict") is not None}),
                   "hood": 12, "size": 5, "quarter": None, "stage": None, "top": 10, "middle": 2, "zone": None, "transit": 4,
                   "density": sum(1 for p in P if (p.get("homesPerAcre") or 0) > 0)}
    for n, cid in enumerate(IDS):
        if n and n % 3 == 0:
            # Chrome stops answering after a long run of downloads from one
            # page, so start a fresh one every three charts.
            pg.close(); pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
            wire(pg, site); pg.goto(f"{SITE}/stats.html"); pg.wait_for_selector("#chart-quarter .chart__tools")
        tools = pg.locator(f"#chart-{cid} .chart__tools")
        title = pg.locator(f"#chart-{cid} .chart__title").inner_text()
        # PNG
        try:
            with pg.expect_download(timeout=45000) as dl:
                tools.locator(".iconbtn").click(); pg.locator('.menu [data-item="png"]').click()
        except Exception:
            print("page messages:", [l for l in logs if "GL Driver" not in l], "toast:", pg.evaluate("document.getElementById('toast') && document.getElementById('toast').textContent"))
            raise
        name = dl.value.suggested_filename
        check(name.startswith("spokane-in-progress-") and "-chart-" in name and name.endswith(".png"), name)
        img = Image.open(dl.value.path())
        check(img.format == "PNG" and img.width == 2400 and 600 < img.height < 4000, f"{cid}: {img.size}")
        img.save(f"{SHOTS}/p5-{cid}.png")
        rgb = img.convert("RGB")
        check(all(abs(a - b) < 6 for a, b in zip(rgb.getpixel((5, 5)), branding.rgb("accent"))), f"{cid}: teal band on top {rgb.getpixel((5, 5))}")
        check(all(abs(a - b) < 6 for a, b in zip(rgb.getpixel((5, 40)), branding.rgb("paper"))), f"{cid}: paper background {rgb.getpixel((5, 40))}")
        pg.wait_for_function("!document.querySelector('.chart__tools [aria-busy]')")
        # SVG
        with pg.expect_download() as dl:
            open_menu(tools); pg.locator('.menu [data-item="svg"]').click()
        svg = open(dl.value.path(), encoding="utf-8").read()
        root = ET.fromstring(svg)
        texts = " ".join(("".join(el.itertext())) for el in root.iter("{http://www.w3.org/2000/svg}text"))
        check(title in texts or title.split(",")[0] in texts, f"{cid}: title in the SVG")
        check("Source: City of Spokane permit records" in texts and "PROJECTS.SPOKANERISING.COM" in texts, f"{cid}: source and site")
        check(root.get("width") == "1200", "1200 wide")
        # CSV
        with pg.expect_download() as dl:
            open_menu(tools); pg.locator('.menu [data-item="csv"]').click()
        rows = list(csv.DictReader(io.StringIO(open(dl.value.path(), encoding="utf-8-sig").read())))
        if expect_rows[cid] is not None:
            check(len(rows) == expect_rows[cid], f"{cid}: {len(rows)} rows")
        if cid == "district":
            for r in rows:
                d = int(r["label"].split()[-1])
                check(int(r["homes"]) == sum(units(p) for p in P if p.get("councilDistrict") == d), f"district {d} homes")
                check(int(r["projects"]) == sum(1 for p in P if p.get("councilDistrict") == d), f"district {d} projects")
                check(sum(int(v) for k, v in r.items() if k.startswith("homes_")) == int(r["homes"]), "stage columns add up")
            page_vals = pg.eval_on_selector_all("#chart-district .bars__value b", "els => els.map(e => +e.textContent.replace(/,/g, ''))")
            check(page_vals == [int(r["homes"]) for r in rows], f"CSV matches the page {page_vals}")
        if cid == "quarter":
            check(sum(int(r["projects"]) for r in rows) == sum(1 for p in P if any(x.get("opened") for x in p.get("permits") or [])), "every dated project in one quarter")
        if cid == "size":
            check(sum(int(r["projects"]) for r in rows) == len(P), "size rows cover every project")
        if cid == "stage":
            check(sum(int(r["homes"]) for r in rows if r["label"] != "(all)") == sum(units(p) for p in P), "stage rows cover every home")
        if cid == "top":
            want = sorted((units(p) for p in P), reverse=True)[:10]
            check([int(r["homes"]) for r in rows] == want, "top 10 by homes, largest first")
            check(pg.locator("#chart-top .bars__label a").count() == 10, "each links to its project")
        if cid == "transit":
            check(sum(int(r["homes"]) for r in rows) == sum(units(p) for p in P if p.get("transitMiles") is not None), "transit bands cover every home")
        if cid == "middle":
            mid = [p for p in counted if p.get("middleHousing")]
            check(int(rows[0]["middle_housing"]) == len(mid) and int(rows[0]["total"]) == len(counted), "middle share of projects")
            check(int(rows[1]["middle_housing"]) == sum(units(p) for p in mid), "middle share of homes")
        if cid == "density":
            check(pg.locator("#chart-density .strip__dot").count() == len(rows), "one dot per project")
        if cid == "type":
            groups = {r["group"] for r in rows}
            check({"Middle housing", "Other housing"} <= groups, groups)
        pg.wait_for_function("!document.querySelector('.chart__tools [aria-busy]')")

    # Colors: the stacked chart images use the stage colors
    img = Image.open(f"{SHOTS}/p5-district.png").convert("RGB").resize((600, 300))
    px = list(img.getdata())
    hits = sum(1 for p in px if any(sum(abs(a - b) for a, b in zip(p, c)) < 30 for c in stage_colors))
    check(hits > 200, f"stage-colored bars drawn ({hits})")
    check(not errors, errors)

    # Pipeline over time: appears once the daily log covers 30 days.
    import datetime
    os.makedirs(os.path.join(site, "data"), exist_ok=True)
    head = "date,projects,homes,projects_no_count,pre_application_projects,pre_application_homes,applied_projects,applied_homes,approved_projects,approved_homes,under_construction_projects,under_construction_homes,complete_projects,complete_homes,stalled_projects,stalled_homes"
    day0 = datetime.date(2026, 11, 27)
    lines = [head] + [f"{day0 + datetime.timedelta(days=i)},100,2000,30,40,{600 + i},18,{400 + i},20,{570 + 2 * i},30,{420 + i},1,2,0,0" for i in range(40)]
    open(os.path.join(site, "data", "pipeline-history.csv"), "w").write("\n".join(lines) + "\n")
    pg.reload(); pg.wait_for_selector("#chart-history .chart__tools")
    pg.add_style_tag(content="html { scroll-behavior: auto !important; }")
    title = pg.locator("#chart-history .chart__title").inner_text()
    check("risen by 156" in title, title)
    check(pg.locator("#chart-history path").count() == 3, "three lines")
    pg.locator("#chart-history").screenshot(path=f"{SHOTS}/p5-page-history.png")
    with pg.expect_download() as dl:
        pg.locator("#chart-history .iconbtn").click(); pg.locator('.menu [data-item="csv"]').click()
    rows = list(csv.DictReader(io.StringIO(open(dl.value.path(), encoding="utf-8-sig").read())))
    check(len(rows) == 40 and rows[-1]["homes_pipeline"] == str(400 + 39 + 570 + 78 + 420 + 39), "history data")
    with pg.expect_download(timeout=45000) as dl:
        pg.locator("#chart-history .iconbtn").click(); pg.locator('.menu [data-item="png"]').click()
    Image.open(dl.value.path()).save(f"{SHOTS}/p5-history.png")
    check(not errors, errors)

    # Phone: buttons big enough to tap
    m = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    mp = m.new_page(); wire(mp, site); mp.goto(f"{SITE}/stats.html"); mp.wait_for_selector("#chart-size .chart__tools")
    hts = mp.eval_on_selector_all(".chart__tools button", "els => els.map(e => e.getBoundingClientRect().height)")
    check(min(hts) >= 36, hts)
    check(not mp.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"), "no sideways scroll")
    m.close()
    b.close()
print(f"{ok} checks passed")
