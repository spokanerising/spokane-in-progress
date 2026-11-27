"""Phase 5 of the sharing plan: each About chart downloads as an image
(PNG), an SVG and its data (CSV), drawn from the same numbers the page
shows, with the chart's title, note, source and the site's name."""
import csv, io, os, sys, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import make_site, wire, SITE, SHOTS
from playwright.sync_api import sync_playwright
from PIL import Image

ok = 0
def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1

os.makedirs(SHOTS, exist_ok=True)
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
    wire(pg, site); pg.goto(f"{SITE}/about.html")
    pg.wait_for_selector("#chart-size .chart__tools")
    check(pg.locator(".chart__tools").count() == 5, "a download row under each of the 5 charts")
    pg.locator("#chart-district").screenshot(path=f"{SHOTS}/p5-page-district.png")

    expect_rows = {"type": None, "district": len({p["councilDistrict"] for p in P if p.get("councilDistrict") is not None}),
                   "hood": 12, "size": 5, "quarter": None}
    for cid in ["type", "district", "hood", "quarter", "size"]:
        tools = pg.locator(f"#chart-{cid} .chart__tools")
        title = pg.locator(f"#chart-{cid} .chart__title").inner_text()
        # PNG
        try:
            with pg.expect_download(timeout=45000) as dl:
                tools.locator('[data-format="png"]').click()
        except Exception:
            print("page messages:", [l for l in logs if "GL Driver" not in l], "toast:", pg.evaluate("document.getElementById('toast') && document.getElementById('toast').textContent"))
            raise
        name = dl.value.suggested_filename
        check(name.startswith("spokane-in-progress-") and "-chart-" in name and name.endswith(".png"), name)
        img = Image.open(dl.value.path())
        check(img.format == "PNG" and img.width == 2400 and 600 < img.height < 4000, f"{cid}: {img.size}")
        img.save(f"{SHOTS}/p5-{cid}.png")
        corner = img.convert("RGB").getpixel((5, 5))
        check(all(abs(a - b) < 6 for a, b in zip(corner, (250, 248, 243))), f"{cid}: paper background {corner}")
        # SVG
        with pg.expect_download() as dl:
            tools.locator('[data-format="svg"]').click()
        svg = open(dl.value.path(), encoding="utf-8").read()
        root = ET.fromstring(svg)
        texts = " ".join(("".join(el.itertext())) for el in root.iter("{http://www.w3.org/2000/svg}text"))
        check(title in texts or title.split(",")[0] in texts, f"{cid}: title in the SVG")
        check("Source: City of Spokane permit records" in texts and "PROJECTS.SPOKANERISING.COM" in texts, f"{cid}: source and site")
        check(root.get("width") == "1200", "1200 wide")
        # CSV
        with pg.expect_download() as dl:
            tools.locator('[data-format="csv"]').click()
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

    # Phone: buttons big enough to tap
    m = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    mp = m.new_page(); wire(mp, site); mp.goto(f"{SITE}/about.html"); mp.wait_for_selector("#chart-size .chart__tools")
    hts = mp.eval_on_selector_all(".chart__tools button", "els => els.map(e => e.getBoundingClientRect().height)")
    check(min(hts) >= 36, hts)
    check(not mp.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"), "no sideways scroll")
    m.close()
    b.close()
print(f"{ok} checks passed")
