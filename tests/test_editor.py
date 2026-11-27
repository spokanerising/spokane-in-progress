"""The editor (editor.js, admin/): the pencil only in a signed-in browser, the
form's values, what Save sends, errors, Hide, Reset, the pending dot, phones,
and the /admin/ page. /api/ is faked; the real functions are tested in
test_functions.py."""
import json, os, shutil, sys
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

site, data = make_site(with_facts=True)
shutil.copy(os.path.join(REPO, "editor.js"), site)
shutil.copytree(os.path.join(REPO, "admin"), os.path.join(site, "admin"))
os.makedirs(os.path.join(site, "data"), exist_ok=True)
projects = data["projects"]
# One project already edited, one with a picture, for Reset and permissions.
edited = projects[0]
edited["edited"] = ["units"]
edited["unitsSource"] = "edited by hand on 2026-11-20"
pictured = projects[1]
pictured["imageUrl"] = "/media/x.jpg"
json.dump(data, open(os.path.join(site, "projects.json"), "w"))
json.dump([{"id": "gone-one", "name": "Gone One", "at": "2026-11-20T10:00:00Z"}], open(os.path.join(site, "data", "hidden.json"), "w"))
detailed = next(p for p in projects if any(f["label"] == "Floor area" for f in p["fields"]))

posts = []
api = {"me": (200, {"email": "spokanerising@gmail.com"}), "edit": (200, None)}

def fake_api(route):
    url = route.request.url
    name = "me" if url.endswith("/api/me") else "edit"
    status, body = api[name]
    if name == "edit":
        posts.append(json.loads(route.request.post_data))
        if body is None:
            body = {"ok": True, "at": "2026-11-27T18:00:00Z", "path": "data/edits/x.json"}
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

with sync_playwright() as pw:
    b = pw.chromium.launch()

    # ---- not signed in: no editor at all --------------------------------
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    wire(pg, site)
    asked = []
    pg.on("request", lambda r: asked.append(r.url))
    pg.goto(f"{SITE}/?p={detailed['id']}")
    pg.wait_for_selector("#detail-tools [data-copy-project]")
    check(pg.locator("[data-edit-project]").count() == 0, "no pencil for the public")
    check(not any("editor.js" in u or "/api/" in u for u in asked), "editor.js and /api/ never requested")
    ctx.close()

    # ---- signed in ---------------------------------------------------------
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script("localStorage.setItem('sip-editor', '1')")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    wire(pg, site)
    pg.route(f"{SITE}/api/**", fake_api)
    pg.goto(f"{SITE}/?p={detailed['id']}")
    pg.wait_for_selector("[data-edit-project]")
    check(pg.locator("#detail-tools [data-edit-project]").get_attribute("aria-label") == "Edit this project", "pencil labelled")
    pg.wait_for_function("document.body.dataset.editor === 'in'")

    # Opening and saving without changes sends nothing, for every project.
    spurious = pg.evaluate("""async () => {
      const res = await fetch('projects.json'); const data = await res.json();
      const bad = [];
      for (const p of data.projects) {
        SIPEditor.open(p);
        const d = document.querySelector('dialog.editor');
        d.querySelector('form').requestSubmit();
        const msg = d.querySelector('.editor__msg').textContent;
        if (!/Nothing has changed/.test(msg)) bad.push(p.id + ': ' + msg);
        d.close();
      }
      return bad; }""")
    check(spurious == [] and posts == [], f"no spurious changes: {spurious[:5]}")

    # The form shows the project's values.
    pg.click("[data-edit-project]")
    dlg = pg.locator("dialog.editor")
    check(dlg.is_visible(), "dialog open")
    check(pg.evaluate("document.activeElement.id") == "ed-name", "focus on the first field")
    val = lambda k: pg.input_value(f"#ed-{k}")
    check(val("name") == detailed["name"], "name filled")
    check(val("status") == detailed["status"], "stage filled")
    check(val("units") == (str(detailed["units"]) if detailed.get("units") is not None else ""), "units filled")
    sqft = next(f["value"] for f in detailed["fields"] if f["label"] == "Floor area")
    check(val("sqft") == "".join(c for c in sqft if c.isdigit()), f"floor area filled from {sqft}")
    stage_options = pg.eval_on_selector_all("#ed-status option", "os => os.map(o => o.textContent)")
    check(stage_options == [s["name"] for s in data["stages"]], "six stages offered")
    pg.screenshot(path=os.path.join(SHOTS, "editor-desktop.png"))

    # Save sends only what changed, with the old values and the permits.
    pg.fill("#ed-units", "1,234")
    pg.select_option("#ed-status", "Complete")
    pg.fill("#ed-sourceUrls", "https://a.example\n\nhttps://b.example ")
    pg.fill("#ed-note", "Checked with the developer")
    pg.click("[data-save]")
    pg.wait_for_function("!document.querySelector('dialog.editor').open")
    check(len(posts) == 1, "one save")
    sent = posts[-1]
    check(sent["project"] == detailed["id"] and sent["permits"] == detailed["permitNumbers"], "id and permits sent")
    check(sent["set"] == {"units": 1234, "status": "Complete", "sourceUrls": ["https://a.example", "https://b.example"]}, f"set {sent['set']}")
    check(sent["was"]["status"] == detailed["status"] and sent["unset"] == [] and sent["note"] == "Checked with the developer", f"was/unset/note {sent}")
    check("live" not in pg.locator("#toast").inner_text() and "Saved" in pg.locator("#toast").inner_text(), "saved notice")
    check(pg.locator("[data-edit-project].is-pending").count() == 1, "pending dot after save")
    pending = pg.evaluate("JSON.parse(localStorage.getItem('sip-editor-pending'))")
    check(pending and pending[0]["id"] == detailed["id"], "pending remembered")

    # Errors stay in the form.
    api["edit"] = (400, {"error": "units should be a whole number."})
    pg.click("[data-edit-project]")
    pg.fill("#ed-stories", "7")
    pg.click("[data-save]")
    pg.wait_for_function("document.querySelector('.editor__msg').textContent.includes('whole number')")
    check(dlg.is_visible() and pg.locator(".editor__msg.is-bad").count() == 1, "server error shown, form kept")
    api["edit"] = (401, {"error": "Not signed in."})
    pg.click("[data-save]")
    pg.wait_for_selector(".editor__msg a[href='/admin/']")
    check(pg.locator(".editor__msg a[target=_blank]").count() == 1, "sign-in link opens in a new tab")
    check(val("stories") == "7", "typed value kept after an error")
    api["edit"] = (200, None)
    pg.click("[data-close] >> nth=0")

    # Picture needs a permission choice.
    n = len(posts)
    pg.evaluate("SIPEditor.open(SIPApp.projectById(arguments[0]))".replace("arguments[0]", json.dumps(detailed["id"])))
    pg.fill("#ed-imageUrl", "https://example.com/r.jpg")
    pg.click("[data-save]")
    check(len(posts) == n and "permission" in pg.locator(".editor__msg").inner_text(), "picture without permission stopped")
    pg.select_option("#ed-imagePermission", "public-record")
    pg.click("[data-save]")
    pg.wait_for_function(f"!document.querySelector('dialog.editor').open")
    check(posts[-1]["set"] == {"imageUrl": "https://example.com/r.jpg", "imagePermission": "public-record"}, f"picture saved {posts[-1]['set']}")

    # Hide takes two presses.
    n = len(posts)
    pg.click("[data-edit-project]")
    pg.click("[data-hide]")
    check(len(posts) == n and pg.locator("[data-hide]").inner_text() == "Press again to hide", "first press only arms")
    pg.click("[data-hide]")
    pg.wait_for_function("!document.querySelector('dialog.editor').open")
    check(posts[-1]["set"] == {"hidden": True}, "hide sent")

    # Reset to automatic on an edited field.
    pg.evaluate(f"SIPEditor.open(SIPApp.projectById({json.dumps(edited['id'])}))")
    check("You edited this" in pg.locator('.edfield[data-key="units"]').inner_text(), "edited field marked")
    pg.click('[data-reset="units"]')
    check(pg.locator("#ed-units").is_disabled(), "reset disables the field")
    pg.click("[data-save]")
    pg.wait_for_function("!document.querySelector('dialog.editor').open")
    check(posts[-1]["unset"] == ["units"] and posts[-1]["set"] == {}, f"reset sent {posts[-1]}")

    # An existing picture starts as "granted", so it isn't re-sent.
    pg.evaluate(f"SIPEditor.open(SIPApp.projectById({json.dumps(pictured['id'])}))")
    check(val("imagePermission") == "granted", "existing picture shown as granted")
    pg.keyboard.press("Escape")
    check(not dlg.is_visible(), "Escape closes")

    # Phones: the form fills the screen, nothing wider than it.
    pg.set_viewport_size({"width": 375, "height": 740})
    pg.evaluate(f"SIPEditor.open(SIPApp.projectById({json.dumps(detailed['id'])}))")
    box = dlg.bounding_box()
    check(box["width"] >= 374 and box["height"] >= 700, f"full screen on phones {box}")
    wide = pg.evaluate("[...document.querySelectorAll('dialog.editor *')].filter(e => e.getBoundingClientRect().right > innerWidth + 1).map(e => e.className || e.tagName).slice(0, 5)")
    check(wide == [], f"no overflow on phones {wide}")
    foot = pg.locator(".editor__foot").bounding_box()
    check(foot["y"] + foot["height"] <= 741, "Save visible without scrolling the page")
    pg.screenshot(path=os.path.join(SHOTS, "editor-phone.png"))
    check(not errors, f"no page errors {errors}")
    ctx.close()

    # ---- /admin/ ---------------------------------------------------------------
    ctx = b.new_context(viewport={"width": 1000, "height": 800})
    pg = ctx.new_page()
    wire(pg, site)
    pg.route(f"{SITE}/api/**", fake_api)
    pg.goto(f"{SITE}/admin/")
    pg.wait_for_selector("#actions:not([hidden])")
    check("spokanerising@gmail.com" in pg.inner_text("#status"), "admin shows who's signed in")
    check(pg.evaluate("localStorage.getItem('sip-editor')") == "1", "admin turns the editor on")
    pg.wait_for_selector("[data-unhide]")
    check("Gone One" in pg.inner_text("#hidden"), "hidden list")
    pg.click("[data-unhide]")
    pg.wait_for_function("document.querySelector('[data-unhide]').textContent.includes('few minutes')")
    check(posts[-1]["unset"] == ["hidden"] and posts[-1]["project"] == "gone-one", "put back sent")
    pg.screenshot(path=os.path.join(SHOTS, "editor-admin.png"))
    api["me"] = (401, {"error": "Not signed in."})
    pg.evaluate("localStorage.removeItem('sip-editor')")
    pg.reload()
    pg.wait_for_function("!document.getElementById('status').textContent.includes('Checking')")
    check(pg.evaluate("localStorage.getItem('sip-editor')") is None and pg.locator("#actions").is_hidden(), "signed out: editor stays off")
    ctx.close()
    b.close()

print(f"{ok} checks passed")
