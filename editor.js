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
        for (const e of pending()) {
          const p = byId.get(e.id);
          const live = e.hide ? !p : p && (p.editedAt || "") >= e.at;
          if (live || (builtAt > e.at && Date.now() - Date.parse(e.at) > 30 * 60e3)) {
            Share.toast(`Your edit to ${e.name} is live. Reload the page to see it.`, 10000);
          } else still.push(e);
        }
        setPending(still);
        App.redrawTools();
      } catch { /* try again next time */ }
      poll();
    }, 45000);
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
        ${note && !edited.has(key) ? `<p class="edfield__note">From: ${esc(note)}</p>` : ""}
        ${edited.has(key) ? `<p class="edfield__note">You edited this. <button type="button" class="linkbtn" data-reset="${key}">Reset to automatic</button></p>` : ""}
      </div>`;
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
        <div class="editor__body">
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
      if (!res.ok) throw new Error(esc(body.error || `The save failed (HTTP ${res.status}).`));
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

  window.SIPEditor = { tools, open, session: () => session };
  document.body.dataset.editor = "checking";
  checkSession();
  App.redrawTools();
  poll();
})();
