// The editor (issue #1, phase 1). Loaded by app.js only in a browser where
// you've signed in at /admin/ (which sets localStorage "sip-editor"), so the
// public never downloads it.
//
// A pencil in the project's top bar opens a form with every field. Save sends
// only what you changed to /api/edit, which commits one file to data/edits/.
// The next build applies it (edits.py) and the site updates a few minutes
// later; until then the pencil shows a dot.
(function () {
  "use strict";
  const App = window.SIPApp;
  const PENDING_KEY = "sip-editor-pending";
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  let session = { state: "checking", email: "" };

  // ---- the fields --------------------------------------------------------
  const fieldValue = (p, label) => ((p.fields || []).find((f) => f.label === label) || {}).value;
  const digits = (v) => (v === undefined || v === null || v === "" ? "" : String(v).replace(/[^0-9.]/g, "").replace(/\.0+$/, ""));

  // key, label, input type, how to read the current value, section
  const FIELDS = [
    ["name", "Name", "text", (p) => p.name, "Basics"],
    ["address", "Address", "text", (p) => p.address, "Basics"],
    ["description", "Description", "textarea", (p) => p.description, "Basics"],
    ["status", "Stage", "stage", (p) => p.status, "Stage"],
    ["statusUpdated", "Reached this stage on", "date", (p) => p.statusUpdated, "Stage"],
    ["units", "Housing units", "int", (p) => digits(p.units), "The building"],
    ["stories", "Stories", "int", (p) => digits(p.stories), "The building"],
    ["sqft", "Floor area (sq ft)", "int", (p) => digits(fieldValue(p, "Floor area")), "The building"],
    ["parking", "Parking stalls", "int", (p) => digits(fieldValue(p, "Parking stalls")), "The building"],
    ["estCost", "Estimated cost ($)", "int", (p) => digits(fieldValue(p, "Estimated cost")), "The building"],
    ["projectType", "Type (as you'd describe it)", "text", (p) => p.projectType, "The building"],
    ["developer", "Developer", "text", (p) => fieldValue(p, "Developer"), "Who's behind it"],
    ["architect", "Architect", "text", (p) => fieldValue(p, "Architect"), "Who's behind it"],
    ["permitUrl", "Permit application link", "url", (p) => fieldValue(p, "Permit application"), "Links"],
    ["sourceUrls", "Sources (one link per line)", "urls", (p) => (p.sourceUrls || []).join("\n"), "Links"],
    ["imageUrl", "Picture (link)", "url", (p) => p.imageUrl, "Picture and PDF"],
    ["imageCredit", "Picture credit", "text", (p) => p.imageCredit, "Picture and PDF"],
    ["imagePermission", "Picture permission", "permission", (p) => (p.imageUrl ? "granted" : ""), "Picture and PDF"],
    ["docUrl", "PDF (link)", "url", (p) => p.docUrl, "Picture and PDF"],
    ["docLabel", "PDF label", "text", (p) => p.docLabel, "Picture and PDF"],
    ["lat", "Latitude", "float", (p) => p.lat ?? "", "Location"],
    ["lng", "Longitude", "float", (p) => p.lng ?? "", "Location"],
  ];
  const PERMISSIONS = [
    ["", "Not set"], ["granted", "My photo, or the owner gave permission"],
    ["public-record", "Public record (e.g. a city filing)"], ["not-sure", "Not sure (saved, not shown)"],
  ];
  // Where the current value came from. "sheet" predates data/projects/.
  const handTyped = (s) => (s === "sheet" ? "typed in by hand" : s);
  const SOURCE_NOTE = { units: (p) => handTyped(p.unitsSource), status: (p) => handTyped(p.stageSource) };

  const norm = (type, v) => {
    const s = String(v ?? "").trim();
    if (type === "int") return digits(s);
    if (type === "float") return s === "" ? "" : String(Number(s));
    if (type === "urls") return s.split(/\s*\n\s*/).filter(Boolean).join("\n");
    return s;
  };
  const outgoing = (type, v) => {
    if (type === "urls") return norm(type, v).split("\n").filter(Boolean);
    if (type === "int" || type === "float") return v === "" ? null : Number(v);
    return v === "" ? null : v;
  };

  // ---- saved edits waiting for the next build ----------------------------
  function pending() {
    try { return JSON.parse(localStorage.getItem(PENDING_KEY) || "[]"); } catch { return []; }
  }
  function setPending(list) {
    try { localStorage.setItem(PENDING_KEY, JSON.stringify(list)); } catch { /* private mode */ }
  }
  const pendingFor = (id) => pending().filter((e) => e.id === id);

  let polling = 0;
  function poll() {
    clearTimeout(polling);
    if (!pending().length) return;
    polling = setTimeout(async () => {
      try {
        const res = await fetch("projects.json", { cache: "no-store" });
        const data = await res.json();
        const byId = new Map((data.projects || []).map((p) => [p.id, p]));
        const builtAt = data.builtAt || "";
        const still = [];
        const before = pending().length;
        for (const e of pending()) {
          const p = byId.get(e.id);
          const live = e.hide ? !p : e.add ? !!p : p && (p.editedAt || "") >= e.at;
          if (live || (builtAt > e.at && Date.now() - Date.parse(e.at) > 30 * 60e3)) {
            Share.toast(`Your edit to ${e.name} is live. Reload the page to see it.`, 10000);
          } else still.push(e);
        }
        setPending(still);
        if (still.length !== before) loadSide();
        App.redrawTools();
      } catch { /* try again next time */ }
      poll();
    }, 45000);
  }

  // ---- history and build notes (phase 3) ---------------------------------------
  // data/edit-history.json: project id -> every edit applied, oldest first.
  // data/build-notes.json: the last build's "things to look at", by project.
  let side = { history: {}, notes: {}, other: [], builtAt: "", candidates: [] };
  async function loadSide() {
    const get = async (url) => { try { const r = await fetch(url, { cache: "no-store" }); return r.ok ? r.json() : null; } catch { return null; } };
    const [history, notes, candidates] = await Promise.all(
      [get("data/edit-history.json"), get("data/build-notes.json"), get("data/candidates.json")]);
    side = { history: history || {}, notes: (notes && notes.projects) || {}, other: (notes && notes.other) || [],
             builtAt: (notes && notes.builtAt) || "", candidates: Array.isArray(candidates) ? candidates : [] };
  }

  const LABELS = Object.fromEntries(FIELDS.map(([k, l]) => [k, l]));
  LABELS.hidden = "Hidden from map";
  const day = (iso) => (iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "");
  const shown = (v) => (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length) ? "blank"
    : Array.isArray(v) ? v.join(", ") : v === true ? "yes" : v === false ? "no" : String(v));
  const touches = (e, key) => key in (e.set || {}) || (e.unset || []).includes(key);

  // What Undo would send for list[i]: each field it changed that nothing
  // later changed goes back to what it was before. "Before" is the last
  // earlier edit's value, or the automatic value if there wasn't one.
  function undoFor(list, i) {
    const e = list[i], set = {}, unset = [], was = {};
    const latest = (key) => !list.slice(i + 1).some((later) => touches(later, key));
    for (const key of Object.keys(e.set || {})) {
      if (!latest(key)) continue;
      was[key] = e.set[key];
      const prev = list.slice(0, i).reverse().find((x) => touches(x, key));
      if (prev && key in (prev.set || {})) set[key] = prev.set[key];
      else unset.push(key);
    }
    for (const key of e.unset || []) {
      if (!latest(key) || !(key in (e.was || {}))) continue;
      set[key] = e.was[key];
      was[key] = null;
    }
    return { set, unset, was, any: Object.keys(set).length + unset.length > 0 };
  }

  function historyHtml(p) {
    const list = side.history[p.id] || [];
    if (!list.length) return `<p class="edhist__none">No edits yet. Edits you save show up here after the next build.</p>`;
    return `<ol class="edhist">${list.map((e, i) => {
      const rows = [
        ...Object.entries(e.set || {}).map(([k, v]) => `<li><b>${esc(LABELS[k] || k)}</b>: ${esc(shown((e.was || {})[k]))} → ${esc(shown(v))}</li>`),
        ...(e.unset || []).map((k) => `<li><b>${esc(LABELS[k] || k)}</b>: reset to automatic</li>`),
      ].join("");
      const undo = undoFor(list, i);
      return `<li class="edhist__item">
        <div class="edhist__head"><span class="edhist__date">${esc(day(e.at))}</span>
          ${undo.any ? `<button type="button" class="linkbtn" data-undo="${i}">Undo</button>` : `<span class="edhist__later">Changed again since</span>`}</div>
        <ul>${rows}</ul>${e.note ? `<p class="edhist__note">${esc(e.note)}</p>` : ""}
      </li>`;
    }).reverse().join("")}</ol>`;
  }

  function notesHtml(p) {
    const notes = side.notes[p.id] || [];
    if (!notes.length) return "";
    return `<div class="ednotes"><p class="label">Notes from the last build${side.builtAt ? `, ${esc(day(side.builtAt))}` : ""}</p>
      <ul>${notes.map((n) => `<li>${esc(n.replace(/^[^:]*:\s*/, ""))}</li>`).join("")}</ul></div>`;
  }

  // ---- the pencil ---------------------------------------------------------
  function tools(p, box) {
    const waiting = pendingFor(p.id).length > 0;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "iconbtn editbtn" + (waiting ? " is-pending" : "");
    btn.dataset.editProject = "";
    btn.setAttribute("aria-label", waiting ? "Edit this project (your last edit is on its way)" : "Edit this project");
    btn.innerHTML = Share.icon("pencil");
    btn.addEventListener("click", () => open(p));
    box.append(btn);
  }

  // ---- uploads (phase 2) -----------------------------------------------------
  // Photos are shrunk here to 2,400 px on the long side (and turned the right
  // way up) before they go anywhere; PDFs go as they are. /api/upload stores
  // the file and answers with its address, which goes into the field. Nothing
  // changes on the project until Save.
  const MAX_BYTES = 25 * 1024 * 1024;
  const LONG_SIDE = 2400;
  const UPLOADS = {
    imageUrl: { label: "Upload a photo", accept: "image/jpeg,image/png,image/webp,image/heic,image/*" },
    docUrl: { label: "Upload a PDF", accept: "application/pdf,.pdf" },
  };
  const kb = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

  function uploadHtml(key) {
    const u = UPLOADS[key];
    return `<div class="edupload">
        <label class="btn btn--small"><input type="file" class="visually-hidden" data-upload="${key}" accept="${u.accept}">${esc(u.label)}…</label>
        <span class="edupload__status" aria-live="polite"></span>
      </div>`;
  }

  async function shrink(file) {
    let bitmap;
    try {
      bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch {
      throw new Error("Couldn't read that photo. Try a JPEG or PNG.");
    }
    const scale = Math.min(1, LONG_SIDE / Math.max(bitmap.width, bitmap.height));
    const w = Math.round(bitmap.width * scale), h = Math.round(bitmap.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";           // transparent PNGs get a white background
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close && bitmap.close();
    const blob = await new Promise((done) => canvas.toBlob(done, "image/jpeg", 0.85));
    if (!blob) throw new Error("Couldn't shrink that photo.");
    // A small JPEG that needed no shrinking goes as it is.
    if (scale === 1 && file.type === "image/jpeg" && file.size <= blob.size) return { blob: file, w, h };
    return { blob, w, h };
  }

  async function upload(p, key, file, status, form, say) {
    const photo = key === "imageUrl";
    status.classList.remove("is-bad");
    try {
      if (!photo && !/\.pdf$/i.test(file.name) && file.type !== "application/pdf") throw new Error("That isn't a PDF.");
      let body = file, size = "";
      if (photo) {
        status.textContent = "Shrinking…";
        const s = await shrink(file);
        body = s.blob;
        size = `${s.w}×${s.h}, `;
      }
      if (body.size > MAX_BYTES) throw new Error(`That file is ${kb(body.size)}; the limit is 25 MB.`);
      status.textContent = `Uploading ${kb(body.size)}…`;
      const res = await fetch(`/api/upload?project=${encodeURIComponent(p.id)}&name=${encodeURIComponent(file.name)}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": body.type || "application/octet-stream" },
        body,
      });
      let reply = {};
      try { reply = await res.json(); } catch { /* sign-in page, not JSON */ }
      if (res.status === 401 || (!res.ok && !reply.error)) {
        session.state = "out";
        throw new Error("Your sign-in has run out. Open /admin/ in a new tab, sign in, and upload again.");
      }
      if (!res.ok) throw new Error(reply.error || `The upload failed (HTTP ${res.status}).`);
      form.elements[key].value = reply.url;
      status.textContent = `Uploaded (${size}${kb(reply.bytes || body.size)}). Press Save to add it to the project.`;
      if (photo) {
        const old = status.parentElement.querySelector(".edupload__preview");
        if (old) old.remove();
        const img = new Image();
        img.className = "edupload__preview";
        img.alt = "The uploaded photo";
        img.src = URL.createObjectURL(body);
        status.parentElement.append(img);
        if (!form.elements.imagePermission.value) {
          say("Now pick a picture permission, then Save.");
          form.elements.imagePermission.focus();
        }
      }
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("is-bad");
    }
  }

  // ---- the form -------------------------------------------------------------
  let dialog = null;

  function inputHtml(key, type, value, p) {
    const id = `ed-${key}`;
    if (type === "textarea" || type === "urls") {
      return `<textarea id="${id}" name="${key}" rows="${type === "urls" ? 3 : 4}">${esc(value)}</textarea>`;
    }
    if (type === "stage") {
      const names = App.stages().map((s) => s.name);
      return `<select id="${id}" name="${key}">${names.map((n) => `<option${n === value ? " selected" : ""}>${esc(n)}</option>`).join("")}</select>`;
    }
    if (type === "permission") {
      return `<select id="${id}" name="${key}">${PERMISSIONS.map(([v, l]) => `<option value="${v}"${v === value ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    }
    const attrs = {
      int: 'inputmode="numeric" autocomplete="off"', float: 'inputmode="decimal" autocomplete="off"',
      date: 'type="date"', url: 'type="url" placeholder="https://"', text: 'type="text"',
    }[type] || 'type="text"';
    return `<input id="${id}" name="${key}" ${attrs} value="${esc(value)}">`;
  }

  function fieldsHtml(p) {
    const edited = new Set(p.edited || []);
    let section = "";
    let html = "";
    for (const [key, label, type, read, sec] of FIELDS) {
      if (sec !== section) {
        html += `${section ? "</fieldset>" : ""}<fieldset><legend class="label">${esc(sec)}</legend>`;
        section = sec;
      }
      const note = SOURCE_NOTE[key] && SOURCE_NOTE[key](p);
      html += `<div class="edfield" data-key="${key}">
        <label for="ed-${key}">${esc(label)}</label>
        ${inputHtml(key, type, read(p) ?? "", p)}
        ${UPLOADS[key] ? uploadHtml(key) : ""}
        ${note && !edited.has(key) ? `<p class="edfield__note">From: ${esc(note)}</p>` : ""}
        ${edited.has(key) ? `<p class="edfield__note">You edited this. <button type="button" class="linkbtn" data-reset="${key}">Reset to automatic</button></p>` : ""}
      </div>`;
      if (key === "imagePermission") html += `<p class="edfield__hint">This also decides whether the PDF's first page is shown as a preview.</p>`;
      if (key === "status") html += `<p class="edfield__hint">The city's permit records can still move the stage forward from what you pick, but never back and never off Stalled.</p>`;
    }
    return html + "</fieldset>";
  }

  // "city-b2404005bldc · B2404005BLDC, B2404006BLDC…", without repeating the id.
  function idLine(p) {
    const permits = (p.permitNumbers || []).filter((n) => n.toLowerCase() !== p.id.toLowerCase());
    const shown = permits.slice(0, 4).join(", ") + (permits.length > 4 ? "…" : "");
    return shown ? `${p.id} · ${shown}` : p.id;
  }

  function formHtml(p) {
    return `
      <form method="dialog" class="editor__form" novalidate>
        <header class="editor__head">
          <div>
            <p class="label">Edit project</p>
            <h2>${esc(p.name)}</h2>
            <p class="editor__id">${esc(idLine(p))}</p>
          </div>
          <button type="button" class="iconbtn" data-close aria-label="Close without saving">${Share.icon("close")}</button>
        </header>
        <div class="edtabs" role="tablist">
          <button type="button" role="tab" aria-selected="true" data-tab="edit">Edit</button>
          <button type="button" role="tab" aria-selected="false" data-tab="history">History (${(side.history[p.id] || []).length})</button>
        </div>
        <div class="editor__body editor__history" data-panel="history" hidden>${historyHtml(p)}</div>
        <div class="editor__body" data-panel="edit">
          ${notesHtml(p)}
          ${session.state === "out" ? `<p class="editor__alert" role="alert">You're signed out. <a href="/admin/" target="_blank" rel="noopener">Sign in again</a> in a new tab, then press Save.</p>` : ""}
          ${fieldsHtml(p)}
          <fieldset><legend class="label">Note</legend>
            <div class="edfield"><label for="ed-note">Where this came from (kept with the edit's history)</label>
            <textarea id="ed-note" name="note" rows="2"></textarea></div>
          </fieldset>
        </div>
        <footer class="editor__foot">
          <p class="editor__msg" role="status" aria-live="polite"></p>
          <div class="editor__actions">
            <button type="button" class="btn btn--quiet" data-hide>Hide from map</button>
            <span class="editor__spacer"></span>
            <button type="button" class="btn" data-close>Cancel</button>
            <button type="submit" class="btn btn--ink" data-save>Save</button>
          </div>
        </footer>
      </form>`;
  }

  function open(p) {
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.className = "editor";
      dialog.setAttribute("aria-label", "Edit project");
      document.body.append(dialog);
    }
    dialog.innerHTML = formHtml(p);
    const form = dialog.querySelector("form");
    const resets = new Set();
    const msg = dialog.querySelector(".editor__msg");
    const say = (text, bad = false) => { msg.textContent = text; msg.classList.toggle("is-bad", bad); };

    dialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
    dialog.querySelectorAll("[data-reset]").forEach((b) => b.addEventListener("click", () => {
      const key = b.dataset.reset;
      const row = b.closest(".edfield");
      const on = !resets.has(key);
      on ? resets.add(key) : resets.delete(key);
      row.classList.toggle("is-reset", on);
      row.querySelector("input, select, textarea").disabled = on;
      b.textContent = on ? "Keep my edit" : "Reset to automatic";
      say(on ? `${row.querySelector("label").textContent} goes back to the automatic value when you save.` : "");
    }));

    dialog.querySelectorAll("[data-tab]").forEach((tab) => tab.addEventListener("click", () => {
      dialog.querySelectorAll("[data-tab]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
      dialog.querySelectorAll("[data-panel]").forEach((panel) => (panel.hidden = panel.dataset.panel !== tab.dataset.tab));
      dialog.querySelector(".editor__actions").hidden = tab.dataset.tab !== "edit";
      say("");
    }));
    dialog.querySelectorAll("[data-undo]").forEach((b) => b.addEventListener("click", () => {
      const list = side.history[p.id] || [];
      const i = Number(b.dataset.undo);
      const u = undoFor(list, i);
      if (!b.classList.contains("is-armed")) {
        dialog.querySelectorAll("[data-undo].is-armed").forEach((x) => { x.classList.remove("is-armed"); x.textContent = "Undo"; });
        b.classList.add("is-armed");
        b.textContent = "Press again to undo";
        return;
      }
      send(p, u.set, u.unset, u.was, `Undo of the edit on ${day(list[i].at)}`, false, say);
    }));

    dialog.querySelectorAll("[data-upload]").forEach((input) => input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const status = input.closest(".edupload").querySelector(".edupload__status");
      upload(p, input.dataset.upload, file, status, form, say).finally(() => (input.value = ""));
    }));

    let hideArmed = false;
    const hideBtn = dialog.querySelector("[data-hide]");
    hideBtn.addEventListener("click", () => {
      if (!hideArmed) {
        hideArmed = true;
        hideBtn.textContent = "Press again to hide";
        hideBtn.classList.add("is-armed");
        say("This takes the project off the map and the list. You can put it back from the editor page (/admin/).");
        return;
      }
      send(p, { hidden: true }, [], { hidden: false }, form.note.value, true, say);
    });

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const set = {}, was = {};
      for (const [key, , type, read] of FIELDS) {
        const el = form.elements[key];
        if (!el || resets.has(key)) continue;
        const before = norm(type, read(p) ?? "");
        const now = norm(type, el.value);
        if (now !== before) { set[key] = outgoing(type, now); was[key] = outgoing(type, before); }
      }
      if ("imageUrl" in set && !("imagePermission" in set)) set.imagePermission = form.elements.imagePermission.value;
      if (set.imageUrl && !set.imagePermission) {
        form.elements.imagePermission.focus();
        return say("Pick a picture permission first. \"Not sure\" saves the picture without showing it.", true);
      }
      for (const key of resets) {
        const [, , type, read] = FIELDS.find((f) => f[0] === key);
        was[key] = outgoing(type, norm(type, read(p) ?? ""));
      }
      if (!Object.keys(set).length && !resets.size) return say("Nothing has changed yet.");
      send(p, set, [...resets], was, form.note.value, false, say);
    });

    dialog.showModal();
    const first = dialog.querySelector("input, textarea, select");
    if (first) first.focus();
  }

  // ---- adding a project (phase 3) ----------------------------------------------
  // A new hand-curated project: /api/project writes data/projects/hand-<name>.json.
  // It needs a name and somewhere to put it: a pin, a parcel number or a permit
  // number (the build looks the last two up). Listing permits claims them, so
  // the city's own version of the project steps aside.
  const ADD_FIELDS = [
    ["name", "Name", "text", "Basics"], ["address", "Address", "text", "Basics"],
    ["description", "Description", "textarea", "Basics"],
    ["parcelId", "Parcel number (e.g. 35192.0101)", "text", "Where"],
    ["permits", "Permit numbers (separate with ;)", "text", "Where"],
    ["status", "Stage", "stage", "Stage"], ["statusUpdated", "Reached this stage on", "date", "Stage"],
    ["units", "Housing units", "int", "The building"], ["stories", "Stories", "int", "The building"],
    ["sqft", "Floor area (sq ft)", "int", "The building"], ["parking", "Parking stalls", "int", "The building"],
    ["estCost", "Estimated cost ($)", "int", "The building"], ["projectType", "Type (as you'd describe it)", "text", "The building"],
    ["developer", "Developer", "text", "Who's behind it"], ["architect", "Architect", "text", "Who's behind it"],
    ["permitUrl", "Permit application link", "url", "Links"], ["sourceUrls", "Sources (one link per line)", "urls", "Links"],
  ];

  function addHtml() {
    let section = "", html = "";
    for (const [key, label, type, sec] of ADD_FIELDS) {
      if (sec !== section) {
        html += `${section ? "</fieldset>" : ""}<fieldset><legend class="label">${esc(sec)}</legend>`;
        if (sec === "Where") {
          html += `<div class="edfield edpin" data-key="pin">
            <span class="edfield__label">Location</span>
            <div class="edupload"><button type="button" class="btn btn--small" data-pick>Pick on map</button>
            <span class="edupload__status" data-pin-status>No pin yet. Or give a parcel or permit number below and the build will find it.</span></div>
            <input type="hidden" name="lat"><input type="hidden" name="lng"></div>`;
        }
        section = sec;
      }
      html += `<div class="edfield" data-key="${key}"><label for="ed-${key}">${esc(label)}${key === "name" ? " (required)" : ""}</label>
        ${inputHtml(key, type, key === "status" ? "Pre-Application" : "", {})}</div>`;
    }
    return `
      <form method="dialog" class="editor__form" novalidate>
        <header class="editor__head">
          <div><p class="label">Add a project</p><h2>New project</h2>
            <p class="editor__id">It appears on the map after the next build, in a minute or two.</p></div>
          <button type="button" class="iconbtn" data-close aria-label="Close without saving">${Share.icon("close")}</button>
        </header>
        <div class="editor__body">${fromPermitHtml()}${html}</fieldset></div>
        <footer class="editor__foot">
          <p class="editor__msg" role="status" aria-live="polite"></p>
          <div class="editor__actions"><span class="editor__spacer"></span>
            <button type="button" class="btn" data-close>Cancel</button>
            <button type="submit" class="btn btn--ink" data-save>Add project</button></div>
        </footer>
      </form>`;
  }

  // "Start from a permit": housing permits in the city's reports that aren't on
  // the map (data/candidates.json). Picking one fills the form; the permit
  // numbers let the build place it, and claim it from then on.
  const candidateLabel = (c) => [c.name || c.address || c.key, c.address && c.address !== c.name ? c.address : "",
    c.units ? `${c.units} homes` : "", c.key].filter(Boolean).join(" · ");

  function fromPermitHtml() {
    if (!side.candidates.length) return "";
    return `<fieldset class="edfrom"><legend class="label">Start from a permit</legend>
      <div class="edfield" data-key="fromPermit"><label for="ed-fromPermit">Housing permits in the city's reports that aren't on the map (${side.candidates.length})</label>
        <select id="ed-fromPermit" name="fromPermit"><option value="">Start from scratch</option>
          ${side.candidates.map((c) => `<option value="${esc(c.key)}">${esc(candidateLabel(c))}</option>`).join("")}</select>
        <p class="edfield__note" data-from-note></p></div></fieldset>`;
  }

  function fillFrom(form, c) {
    const set = (k, v) => { if (form.elements[k]) form.elements[k].value = v ?? ""; };
    set("name", c.name); set("address", c.address); set("description", c.description);
    set("parcelId", c.parcelId); set("permits", (c.permits || []).join("; "));
    set("status", c.status || "Pre-Application"); set("statusUpdated", c.date);
    set("units", c.units); set("estCost", c.estCost);
    set("sourceUrls", c.reportUrl || "");
  }

  function openAdd(startKey = "") {
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.className = "editor";
      document.body.append(dialog);
    }
    dialog.setAttribute("aria-label", "Add a project");
    dialog.innerHTML = addHtml();
    const form = dialog.querySelector("form");
    const msg = dialog.querySelector(".editor__msg");
    const say = (text, bad = false) => { msg.innerHTML = text; msg.classList.toggle("is-bad", bad); };
    dialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
    const pinStatus = dialog.querySelector("[data-pin-status]");
    const from = form.elements.fromPermit;
    const fromNote = dialog.querySelector("[data-from-note]");
    const pickCandidate = (key) => {
      const c = side.candidates.find((x) => x.key === key);
      if (!c) return;
      fillFrom(form, c);
      fromNote.textContent = `From the ${c.source}. Check the name and details, then Add project. The build finds it on the map from its permit${c.parcelId ? " and parcel" : ""} number.`;
    };
    if (from) {
      from.addEventListener("change", () => (from.value ? pickCandidate(from.value) : (fromNote.textContent = "")));
      if (startKey && side.candidates.some((c) => c.key === startKey)) { from.value = startKey; pickCandidate(startKey); }
    }
    dialog.querySelector("[data-pick]").addEventListener("click", () => {
      dialog.close();
      App.pickPoint((point) => {
        if (point) {
          form.elements.lat.value = point.lat.toFixed(6);
          form.elements.lng.value = point.lng.toFixed(6);
          pinStatus.textContent = `Pin at ${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}. Pick again to move it.`;
          say("");
        }
        // After this event is done: an Escape that cancelled picking would
        // otherwise go on to close the form it just reopened.
        setTimeout(() => dialog.showModal(), 0);
      }, "Click the map where the new project is");
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = {};
      for (const [key, , type] of ADD_FIELDS) {
        if (!form.elements[key]) continue;
        const v = norm(type, form.elements[key].value);
        if (v !== "") body[key] = type === "urls" ? v.split("\n") : v;
      }
      if (form.elements.lat.value) { body.lat = Number(form.elements.lat.value); body.lng = Number(form.elements.lng.value); }
      if (!body.name) { form.elements.name.focus(); return say("Give it a name first.", true); }
      if (!body.lat && !body.parcelId && !body.permits) return say("Pick it on the map, or give a parcel or permit number, so the map knows where it goes.", true);
      const save = dialog.querySelector("[data-save]");
      save.disabled = true;
      save.setAttribute("aria-busy", "true");
      say("Adding…");
      try {
        const res = await fetch("/api/project", {
          method: "POST", credentials: "same-origin",
          headers: { "content-type": "application/json" }, body: JSON.stringify(body),
        });
        let reply = {};
        try { reply = await res.json(); } catch { /* sign-in page */ }
        if (res.status === 401 || (!res.ok && !reply.error)) {
          session.state = "out";
          throw new Error('Your sign-in has run out. Open <a href="/admin/" target="_blank" rel="noopener">the editor page</a> in a new tab, then press Add project again.');
        }
        if (!res.ok) throw new Error(esc(reply.error || `That didn't save (HTTP ${res.status}).`));
        session.state = "in";
        setPending([...pending(), { id: reply.id, name: body.name, at: reply.at, add: true }]);
        dialog.close();
        Share.toast(`${body.name} added. It appears on the map in a minute or two.`, 7000);
        poll();
      } catch (error) {
        say(error.message, true);
      } finally {
        save.disabled = false;
        save.removeAttribute("aria-busy");
      }
    });
    dialog.showModal();
    form.elements.name.focus();
  }

  function addButton() {
    const box = document.querySelector(".listtools__actions");
    if (!box || box.querySelector("[data-add-project]")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "iconbtn";
    btn.dataset.addProject = "";
    btn.setAttribute("aria-label", "Add a project");
    btn.innerHTML = Share.icon("plus");
    btn.addEventListener("click", () => openAdd());
    box.prepend(btn);
  }

  async function send(p, set, unset, was, note, hide, say) {
    const save = dialog.querySelector("[data-save]");
    dialog.querySelectorAll(".editor__actions button").forEach((b) => (b.disabled = true));
    save.setAttribute("aria-busy", "true");
    say("Saving…");
    try {
      const res = await fetch("/api/edit", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ project: p.id, name: p.name, permits: p.permitNumbers || [], set, unset, was, note }),
      });
      let body = {};
      try { body = await res.json(); } catch { /* sign-in page, not JSON */ }
      if (res.status === 401 || (!res.ok && !body.error)) {
        session.state = "out";
        throw new Error('Your sign-in has run out. Open <a href="/admin/" target="_blank" rel="noopener">the editor page</a> in a new tab to sign in again, then press Save.');
      }
      if (!res.ok) throw new Error(body.error || `The save failed (HTTP ${res.status}).`);
      session.state = "in";
      setPending([...pending(), { id: p.id, name: p.name, at: body.at, hide }]);
      dialog.close();
      Share.toast(hide ? `${p.name} will leave the map in a few minutes.` : `Saved. The site updates in a few minutes.`, 6000);
      App.redrawTools();
      poll();
    } catch (error) {
      const m = dialog.querySelector(".editor__msg");
      m.innerHTML = error.message.includes("<a ") ? error.message : esc(error.message);
      m.classList.add("is-bad");
      if (/Failed to fetch|NetworkError|Load failed/i.test(error.message)) {
        session.state = "out";
        m.innerHTML = 'Couldn\'t reach the editor. Your sign-in may have run out: open <a href="/admin/" target="_blank" rel="noopener">the editor page</a> in a new tab, then press Save again.';
      }
    } finally {
      dialog.querySelectorAll(".editor__actions button").forEach((b) => (b.disabled = false));
      save.removeAttribute("aria-busy");
    }
  }

  // ---- start ---------------------------------------------------------------
  async function checkSession() {
    try {
      const res = await fetch("/api/me", { credentials: "same-origin", cache: "no-store" });
      const body = res.ok ? await res.json() : {};
      session = body.email ? { state: "in", email: body.email } : { state: "out", email: "" };
    } catch {
      session = { state: "out", email: "" };
    }
    document.body.dataset.editor = session.state;
  }

  window.SIPEditor = { tools, open, openAdd, session: () => session, undoFor, loaded: () => loadSide() };
  document.body.dataset.editor = "checking";
  checkSession();
  addButton();
  // "Add to the map" on /admin/ hands over a permit to start from.
  loadSide().then(() => {
    let key = "";
    try { key = sessionStorage.getItem("sip-add") || ""; sessionStorage.removeItem("sip-add"); } catch { /* storage blocked */ }
    if (key) openAdd(key);
  });
  App.redrawTools();
  poll();
})();
