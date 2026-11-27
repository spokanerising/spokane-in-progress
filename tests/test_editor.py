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
# History and build notes for the detailed project (phase 3).
HIST = [
    {"at": "2026-11-20T10:00:00Z", "file": "a.json", "set": {"units": 50}, "was": {"units": 44}, "unset": [], "note": "First count"},
    {"at": "2026-11-21T10:00:00Z", "file": "b.json", "set": {"units": 60, "stories": 4}, "was": {"units": 50, "stories": None}, "unset": [], "note": ""},
    {"at": "2026-11-22T10:00:00Z", "file": "c.json", "set": {}, "was": {"stories": 4}, "unset": ["stories"], "note": "Back to the city's"},
]
json.dump({detailed["id"]: HIST}, open(os.path.join(site, "data", "edit-history.json"), "w"))
CANDS = [
    {"key": "B2610907BLDC", "source": "weekly permit report", "permits": ["B2610907BLDC"], "name": "Khinda 4-unit Apartments",
     "address": "3133 N Stuart", "units": 3, "estCost": 250000, "date": "2026-07-27", "status": "Approved",
     "description": "Change of use from a house to 4 apartments.", "parcelId": "35084.1234", "reportUrl": "https://example.gov/r.pdf"},
    {"key": "B25M0067PDEV", "source": "monthly permit report (Significant PDEV & MFTEs, as of 2026-05-31)", "permits": ["B25M0067PDEV"],
     "name": "Canyon Bluff Apartments", "address": "", "units": 168, "estCost": None, "date": "2026-05-31", "status": "Pre-Application",
     "description": "", "parcelId": "", "reportUrl": ""},
]
json.dump(CANDS, open(os.path.join(site, "data", "candidates.json"), "w"))
json.dump({"builtAt": "2026-11-27T19:00:00Z", "projects": {detailed["id"]: [f"{detailed['name']}: you set 60 units; city permit report says 44. Yours is shown."]},
           "other": ["Monthly: Canyon Bluff Apartments (168 units) has no street address. Not mapped."]},
          open(os.path.join(site, "data", "build-notes.json"), "w"))

posts = []
uploads = []
api = {"me": (200, {"email": "spokanerising@gmail.com"}), "edit": (200, None), "upload": (200, None)}

def fake_api(route):
    url = route.request.url
    if "/api/project" in url:
        posts.append({"add": json.loads(route.request.post_data)})
        status, reply = api.get("project", (200, None))
        reply = reply or {"ok": True, "id": "hand-new-place", "at": "2026-11-27T19:30:00Z"}
        return route.fulfill(status=status, content_type="application/json", body=json.dumps(reply))
    if "/api/upload" in url:
        body = route.request.post_data_buffer
        uploads.append({"url": url, "type": route.request.headers.get("content-type"), "body": body})
        status, reply = api["upload"]
        if reply is None:
            ext = "pdf" if body[:5] == b"%PDF-" else "jpg"
            reply = {"ok": True, "url": f"https://site.test/media/x/20261127T190000Z-0000000{len(uploads)}.{ext}", "bytes": len(body)}
        return route.fulfill(status=status, content_type="application/json", body=json.dumps(reply))
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
    api["edit"] = (503, {"error": "The editor isn't set up yet: GITHUB_TOKEN is missing."})
    pg.click("[data-save]")
    pg.wait_for_function("document.querySelector('.editor__msg').textContent.includes('GITHUB_TOKEN')")
    check(pg.locator(".editor__msg").inner_text() == "The editor isn't set up yet: GITHUB_TOKEN is missing.", "error text shown once-escaped")
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

    # Uploads: photos shrink to 2,400 px and turn the right way up; PDFs go as
    # they are; the address lands in the field; Save sends it.
    import io
    from PIL import Image
    def jpeg(w, h, orientation=None):
        buf = io.BytesIO()
        img = Image.new("RGB", (w, h), (180, 90, 40))
        if orientation:
            exif = Image.Exif(); exif[0x0112] = orientation
            img.save(buf, "JPEG", exif=exif)
        else:
            img.save(buf, "JPEG")
        return buf.getvalue()
    def png_alpha():
        buf = io.BytesIO(); Image.new("RGBA", (300, 200), (0, 0, 0, 0)).save(buf, "PNG"); return buf.getvalue()
    def dims(b):
        return Image.open(io.BytesIO(b)).size

    pg.evaluate(f"SIPEditor.open(SIPApp.projectById({json.dumps(detailed['id'])}))")
    check(pg.locator('[data-upload="imageUrl"]').count() == 1 and pg.locator('[data-upload="docUrl"]').count() == 1, "upload buttons")
    status = lambda k: pg.locator(f'.edfield[data-key="{k}"] .edupload__status')
    pg.set_input_files('[data-upload="imageUrl"]', files=[{"name": "big.jpg", "mimeType": "image/jpeg", "buffer": jpeg(4000, 3000)}])
    pg.wait_for_function("document.querySelector('[data-key=imageUrl] .edupload__status').textContent.includes('Press Save')")
    u = uploads[-1]
    check(u["body"][:3] == b"\xff\xd8\xff" and dims(u["body"]) == (2400, 1800), f"big photo shrunk to {dims(u['body'])}")
    check("project=" + detailed["id"] in u["url"] and "name=big.jpg" in u["url"], "upload names the project and file")
    check(val("imageUrl").startswith("https://site.test/media/") and "2400×1800" in status("imageUrl").inner_text(), "address in the field")
    check(pg.locator(".edupload__preview").count() == 1, "preview shown")
    check("permission" in pg.locator(".editor__msg").inner_text() and pg.evaluate("document.activeElement.id") == "ed-imagePermission", "asks for permission next")
    pg.set_input_files('[data-upload="imageUrl"]', files=[{"name": "phone.jpg", "mimeType": "image/jpeg", "buffer": jpeg(300, 200, orientation=6)}])
    pg.wait_for_function("document.querySelector('[data-key=imageUrl] .edupload__status').textContent.includes('Press Save')")
    check(dims(uploads[-1]["body"]) == (200, 300), f"phone photo turned upright {dims(uploads[-1]['body'])}")
    check(pg.locator(".edupload__preview").count() == 1, "one preview at a time")
    pg.set_input_files('[data-upload="imageUrl"]', files=[{"name": "clear.png", "mimeType": "image/png", "buffer": png_alpha()}])
    pg.wait_for_function("document.querySelector('[data-key=imageUrl] .edupload__status').textContent.includes('Press Save')")
    check(Image.open(io.BytesIO(uploads[-1]["body"])).convert("RGB").getpixel((5, 5)) == (255, 255, 255), "transparent PNG on white")
    n = len(uploads)
    pg.set_input_files('[data-upload="imageUrl"]', files=[{"name": "fake.jpg", "mimeType": "image/jpeg", "buffer": b"not a picture"}])
    pg.wait_for_selector('[data-key=imageUrl] .edupload__status.is-bad')
    check(len(uploads) == n and "Couldn't read" in status("imageUrl").inner_text(), "broken photo not uploaded")
    pdf = b"%PDF-1.4\n" + b"x" * 5000
    pg.set_input_files('[data-upload="docUrl"]', files=[{"name": "plans.pdf", "mimeType": "application/pdf", "buffer": pdf}])
    pg.wait_for_function("document.querySelector('[data-key=docUrl] .edupload__status').textContent.includes('Press Save')")
    check(uploads[-1]["body"] == pdf and uploads[-1]["type"] == "application/pdf", "PDF sent unchanged")
    check(val("docUrl").endswith(".pdf"), "PDF address in the field")
    pg.set_input_files('[data-upload="docUrl"]', files=[{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hi"}])
    pg.wait_for_selector('[data-key=docUrl] .edupload__status.is-bad')
    check("isn't a PDF" in status("docUrl").inner_text(), "non-PDF refused")
    api["upload"] = (503, {"error": "File storage isn't set up yet: the MEDIA bucket isn't connected."})
    pg.set_input_files('[data-upload="docUrl"]', files=[{"name": "plans.pdf", "mimeType": "application/pdf", "buffer": pdf}])
    pg.wait_for_selector('[data-key=docUrl] .edupload__status.is-bad')
    check("MEDIA bucket" in status("docUrl").inner_text() and val("docUrl").endswith(".pdf"), "server error shown, field kept")
    api["upload"] = (200, None)
    pg.screenshot(path=os.path.join(SHOTS, "editor-uploads.png"))
    pg.select_option("#ed-imagePermission", "granted")
    pg.click("[data-save]")
    pg.wait_for_function("!document.querySelector('dialog.editor').open")
    sent = posts[-1]["set"]
    check(sent["imageUrl"].endswith(".jpg") and sent["docUrl"].endswith(".pdf") and sent["imagePermission"] == "granted", f"Save sends the uploads {sent}")

    # ---- phase 3: build notes, History and Undo ----
    pg.evaluate(f"SIPEditor.open(SIPApp.projectById({json.dumps(detailed['id'])}))")
    notes = pg.locator(".ednotes")
    check(notes.count() == 1 and "you set 60 units; city permit report says 44" in notes.inner_text(), "build notes at the top")
    check(detailed["name"] + ":" not in notes.inner_text(), "note shown without the name prefix")
    check(pg.locator('[data-tab="history"]').inner_text() == "History (3)", "history count")
    pg.click('[data-tab="history"]')
    check(pg.locator('[data-panel="edit"]').is_hidden() and pg.locator(".editor__actions").is_hidden(), "edit form hidden on History")
    items = pg.locator(".edhist__item")
    check(items.count() == 3 and "Nov 22, 2026" in items.nth(0).inner_text(), "newest first")
    check("Stories: reset to automatic" in items.nth(0).inner_text() and "Back to the city's" in items.nth(0).inner_text(), "reset and note shown")
    check("Housing units: 50 → 60" in items.nth(1).inner_text() and "Stories: blank → 4" in items.nth(1).inner_text(), "old → new")
    check("Changed again since" in items.nth(2).inner_text() and items.nth(2).locator("[data-undo]").count() == 0, "older edit can't be undone")
    n = len(posts)
    items.nth(1).locator("[data-undo]").click()
    check(len(posts) == n and items.nth(1).locator("[data-undo]").inner_text() == "Press again to undo", "undo arms first")
    items.nth(1).locator("[data-undo]").click()
    pg.wait_for_function("!document.querySelector('dialog.editor').open")
    u = posts[-1]
    check(u["set"] == {"units": 50} and u["unset"] == [] and u["was"] == {"units": 60}, f"undo goes back to the earlier edit, skips later-changed {u}")
    check(u["note"] == "Undo of the edit on Nov 21, 2026", "undo note")
    pg.evaluate(f"SIPEditor.open(SIPApp.projectById({json.dumps(detailed['id'])}))")
    pg.click('[data-tab="history"]')
    pg.locator(".edhist__item").nth(0).locator("[data-undo]").click()
    pg.locator(".edhist__item").nth(0).locator("[data-undo]").click()
    pg.wait_for_function("!document.querySelector('dialog.editor').open")
    check(posts[-1]["set"] == {"stories": 4} and posts[-1]["unset"] == [], f"undoing a reset puts the value back {posts[-1]}")
    first_only = pg.evaluate("SIPEditor.undoFor([{set:{units:50},was:{units:44},unset:[]}], 0)")
    check(first_only["unset"] == ["units"] and first_only["set"] == {}, "undoing the only edit goes back to automatic")
    pg.evaluate(f"SIPEditor.open(SIPApp.projectById({json.dumps(projects[5]['id'])}))")
    pg.click('[data-tab="history"]')
    check("No edits yet" in pg.locator(".editor__history").inner_text() and pg.locator(".ednotes").count() == 0, "no history, no notes")
    pg.keyboard.press("Escape")

    # ---- phase 3: adding a project ----
    add = pg.locator("[data-add-project]")
    check(add.count() == 1 and add.get_attribute("aria-label") == "Add a project", "Add a project button")
    add.click()
    check(pg.evaluate("document.activeElement.name") == "name", "name field first")
    n = len(posts)
    pg.click("[data-save]")
    check(len(posts) == n and "name" in pg.locator(".editor__msg").inner_text(), "name required")
    pg.fill("#ed-name", "New Place Townhomes")
    pg.click("[data-save]")
    check(len(posts) == n and "map knows where" in pg.locator(".editor__msg").inner_text(), "location required")
    pg.click("[data-pick]")
    check(not dlg.is_visible() and pg.evaluate("document.body.dataset.picking") == "on", "picking on the map")
    check("new project" in pg.inner_text("#pickhint"), "pick hint says what for")
    pg.keyboard.press("Escape")
    pg.wait_for_function("document.querySelector('dialog.editor').open")
    check(pg.input_value("#ed-name") == "New Place Townhomes" and "No pin yet" in pg.inner_text("[data-pin-status]"), "cancel keeps the form, no pin")
    check(pg.inner_text("#pickhint span") == "Click the map to choose a spot", "hint text restored")
    pg.click("[data-pick]")
    mb = pg.locator("#map canvas").bounding_box()
    pg.mouse.click(mb["x"] + mb["width"] / 2 + 40, mb["y"] + mb["height"] / 2 + 30)
    pg.wait_for_function("document.querySelector('dialog.editor').open")
    check("Pin at 47." in pg.inner_text("[data-pin-status]"), "pin placed " + pg.inner_text("[data-pin-status]"))
    check(pg.locator("#ed-near").count() == 0 and pg.evaluate("document.body.dataset.picking") == "off", "Near not touched, picking off")
    pg.fill("#ed-permits", "b2600001bldc")
    pg.fill("#ed-units", "8")
    pg.select_option("#ed-status", "Applied")
    pg.fill("#ed-sourceUrls", "https://news.example/a\nhttps://news.example/b")
    pg.screenshot(path=os.path.join(SHOTS, "editor-add.png"))
    pg.click("[data-save]")
    pg.wait_for_function("!document.querySelector('dialog.editor').open")
    body = posts[-1]["add"]
    check(body["name"] == "New Place Townhomes" and body["units"] == "8" and body["status"] == "Applied" and body["permits"] == "b2600001bldc", f"add sends {body}")
    check(isinstance(body["lat"], float) and 47.5 < body["lat"] < 47.8 and -117.6 < body["lng"] < -117.2, "add sends the pin")
    check(body["sourceUrls"] == ["https://news.example/a", "https://news.example/b"] and "address" not in body, "blank fields left out")
    check("added" in pg.locator("#toast").inner_text(), "added notice")
    check(any(e.get("add") and e["id"] == "hand-new-place" for e in pg.evaluate("JSON.parse(localStorage.getItem('sip-editor-pending'))")), "add remembered until live")
    api["project"] = (409, {"error": "There's already a project file called hand-new-place-townhomes. Give this one a different name."})
    add.click()
    pg.fill("#ed-name", "New Place Townhomes")
    pg.fill("#ed-parcelId", "35192.0101")
    pg.click("[data-save]")
    pg.wait_for_selector(".editor__msg.is-bad")
    check("already a project file" in pg.locator(".editor__msg").inner_text() and dlg.is_visible(), "duplicate refused, form kept")
    pg.keyboard.press("Escape")
    del api["project"]

    # Start from a permit: the picker fills the form from the city's report.
    add.click()
    opts = pg.eval_on_selector_all("#ed-fromPermit option", "os => os.map(o => o.textContent)")
    check(len(opts) == 3 and opts[0] == "Start from scratch" and "Khinda 4-unit Apartments · 3133 N Stuart · 3 homes · B2610907BLDC" == opts[1], f"permit picker {opts}")
    pg.select_option("#ed-fromPermit", "B2610907BLDC")
    check(val("name") == "Khinda 4-unit Apartments" and val("address") == "3133 N Stuart" and val("permits") == "B2610907BLDC", "filled basics")
    check(val("units") == "3" and val("estCost") == "250000" and val("status") == "Approved" and val("statusUpdated") == "2026-07-27", "filled numbers, stage, date")
    check(val("parcelId") == "35084.1234" and val("sourceUrls") == "https://example.gov/r.pdf" and "weekly permit report" in pg.inner_text("[data-from-note]"), "filled parcel, source, note")
    pg.click("[data-save]")
    pg.wait_for_function("!document.querySelector('dialog.editor').open")
    sent_add = posts[-1]["add"]
    check(sent_add["permits"] == "B2610907BLDC" and sent_add["parcelId"] == "35084.1234" and "lat" not in sent_add and "fromPermit" not in sent_add, f"sent from a permit {sent_add}")
    # Escape during picking also closes an open project, as it always has; reopen it.
    pg.goto(f"{SITE}/?p={detailed['id']}")
    pg.wait_for_selector("[data-edit-project]")

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
    check("Canyon Bluff" in pg.inner_text("#notes") and "1 note(s) about 1 project(s)" in pg.inner_text("#notes"), "admin shows build notes")
    # Permits not on the map: Skip (two presses), and Add to the map hands over to the map's Add form.
    check(pg.locator("#cands li").count() == 2 and "Khinda" in pg.inner_text("#cands"), "permit list on /admin/")
    skip = pg.locator('[data-skip="B25M0067PDEV"]')
    n = len(posts)
    skip.click()
    check(len(posts) == n and skip.inner_text() == "Press again to skip", "skip arms first")
    skip.click()
    pg.wait_for_function("document.querySelector('[data-skip=B25M0067PDEV]').textContent === 'Skipped'")
    check(posts[-1]["project"] == "candidate-B25M0067PDEV" and posts[-1]["set"] == {"hidden": True}, f"skip sent {posts[-1]}")
    pg.evaluate("localStorage.setItem('sip-editor', '1')")
    pg.click('[data-add="B2610907BLDC"]')
    pg.wait_for_url(f"{SITE}/")
    pg.wait_for_function("document.querySelector('dialog.editor') && document.querySelector('dialog.editor').open")
    check(pg.input_value("#ed-fromPermit") == "B2610907BLDC" and pg.input_value("#ed-name") == "Khinda 4-unit Apartments", "lands on the map with the form filled")
    check(pg.evaluate("sessionStorage.getItem('sip-add')") is None, "handoff used once")
    pg.keyboard.press("Escape")
    pg.goto(f"{SITE}/admin/")
    pg.screenshot(path=os.path.join(SHOTS, "editor-admin.png"))
    api["me"] = (401, {"error": "Not signed in."})
    pg.evaluate("localStorage.removeItem('sip-editor')")
    pg.reload()
    pg.wait_for_function("!document.getElementById('status').textContent.includes('Checking')")
    check(pg.evaluate("localStorage.getItem('sip-editor')") is None and pg.locator("#actions").is_hidden(), "signed out: editor stays off")
    ctx.close()
    b.close()

print(f"{ok} checks passed")
