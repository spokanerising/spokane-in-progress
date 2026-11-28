// Spokane in Progress — shared tools for sharing and downloading.
// Loaded before app.js (the map) and stats.js (the Stats page), so both pages
// share, copy, save files and show notices the same way. Everything lives on
// one object, `Share`, so nothing here collides with the page scripts.

(function () {
  "use strict";

  const SITE_NAME = "Spokane in Progress";
  const SITE_HOST = "projects.spokanerising.com";

  // ---- share links ------------------------------------------------------------
  //
  // Plain links to each network's own "compose a post" page: no outside
  // scripts, nothing loads until someone clicks. Order is the menu's order.
  // Bluesky takes one text field (300 characters) with the link inside it;
  // X takes text and url separately (280 characters together).

  const clip = (text, max) => (text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`);

  function shareLinks(url, text = "", title = "") {
    const u = encodeURIComponent(url);
    const subject = title || text || SITE_NAME;
    return [
      { id: "bluesky", label: "Bluesky",
        href: `https://bsky.app/intent/compose?text=${encodeURIComponent(`${clip(text, 300 - url.length - 1)} ${url}`.trim())}` },
      { id: "reddit", label: "Reddit",
        href: `https://www.reddit.com/submit?url=${u}&title=${encodeURIComponent(clip(subject, 300))}` },
      { id: "linkedin", label: "LinkedIn",
        href: `https://www.linkedin.com/sharing/share-offsite/?url=${u}` },
      { id: "x", label: "X",
        href: `https://x.com/intent/tweet?text=${encodeURIComponent(clip(text, 280 - 24))}&url=${u}` },
      { id: "email", label: "Email",
        href: `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(`${text ? `${text}\n\n` : ""}${url}`)}` },
    ];
  }

  // The phone's own share sheet, where there is one. Returns "shared",
  // "cancelled", or "unavailable" (then the caller shows its own menu).
  async function nativeShare({ url, title, text }) {
    if (!navigator.share) return "unavailable";
    const data = { url, title: title || SITE_NAME, text: text || "" };
    if (navigator.canShare && !navigator.canShare(data)) return "unavailable";
    try {
      await navigator.share(data);
      return "shared";
    } catch (error) {
      return error && error.name === "AbortError" ? "cancelled" : "unavailable";
    }
  }

  // Phones and tablets get the share sheet; desktop browsers that also have
  // navigator.share (Safari, Edge) get the menu, which offers more choices.
  const prefersNativeShare = () =>
    !!navigator.share && window.matchMedia("(pointer: coarse)").matches;

  // ---- copying ------------------------------------------------------------------

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      // Older or locked-down browsers: a hidden text box and the old command.
      const box = document.createElement("textarea");
      box.value = text;
      box.setAttribute("readonly", "");
      box.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
      document.body.appendChild(box);
      box.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      box.remove();
      return ok;
    }
  }

  // ---- downloads ----------------------------------------------------------------

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  function downloadText(text, filename, type = "text/plain") {
    downloadBlob(new Blob([text], { type: `${type};charset=utf-8` }), filename);
  }

  function downloadCanvas(canvas, filename, type = "image/png", quality = 0.92) {
    return new Promise((resolve, reject) =>
      canvas.toBlob((blob) => {
        if (!blob) return reject(new Error("The image couldn't be made."));
        downloadBlob(blob, filename);
        resolve(blob);
      }, type, quality)
    );
  }

  // "spokane-in-progress-2026-11-26-filtered.csv"
  function filename(parts, ext, date = new Date()) {
    const day = date.toISOString().slice(0, 10);
    const tail = [].concat(parts || []).filter(Boolean).join("-");
    return `spokane-in-progress-${day}${tail ? `-${tail}` : ""}.${ext}`;
  }

  // CSV that Excel and Google Sheets both open cleanly (quotes doubled, a BOM
  // so Excel reads accents correctly).
  function toCsv(rows, columns) {
    const cell = (v) => {
      const s = v === null || v === undefined ? "" : Array.isArray(v) ? v.join("; ") : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [columns.map((c) => cell(c.label)).join(",")];
    rows.forEach((r) => lines.push(columns.map((c) => cell(c.value(r))).join(",")));
    return "﻿" + lines.join("\r\n") + "\r\n";
  }

  // ---- notices ------------------------------------------------------------------
  //
  // One small notice at the bottom of the screen ("Link copied"). Announced
  // to screen readers, gone after a few seconds, and a new one replaces it.

  let toastTimer = null;
  function toast(message, ms = 2600) {
    let box = document.getElementById("toast");
    if (!box) {
      box = document.createElement("div");
      box.id = "toast";
      box.className = "toast";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    box.textContent = message;
    box.classList.add("is-on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.remove("is-on"), ms);
  }

  // ---- credits and fonts for anything exported ------------------------------------

  const AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
  const apDate = (d) => `${AP_MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;

  // "Spokane in Progress · projects.spokanerising.com · Data as of Nov. 26, 2026"
  function creditLine(builtAt, extra = []) {
    const parts = [SITE_NAME, SITE_HOST];
    if (builtAt instanceof Date && !isNaN(builtAt)) parts.push(`Data as of ${apDate(builtAt)}`);
    return parts.concat(extra).join(" · ");
  }

  // The site's type, from brand.css (made from brand/brand.json), for images
  // drawn in the browser. canvas() gives a ctx.font string for headlines.
  const STRETCH_WORDS = [[50, "ultra-condensed"], [62.5, "extra-condensed"], [75, "condensed"], [87.5, "semi-condensed"],
    [100, "normal"], [112.5, "semi-expanded"], [125, "expanded"], [150, "extra-expanded"], [200, "ultra-expanded"]];
  function brandFonts() {
    const css = getComputedStyle(document.documentElement);
    const v = (n, d) => css.getPropertyValue(`--${n}`).trim() || d;
    const pct = parseFloat(v("display-stretch", "100%")) || 100;
    const word = STRETCH_WORDS.reduce((a, b) => (Math.abs(b[0] - pct) < Math.abs(a[0] - pct) ? b : a))[1];
    const f = {
      display: v("display", "Georgia, serif"), displayWeight: v("display-weight", "600"),
      displayStretch: `${pct}%`, stretchWord: word,
      emStyle: v("display-em-style", "italic"), emWeight: v("display-em-weight", "500"),
      deck: v("deck", "Georgia, serif"), deckWeight: v("deck-weight", "400"),
      sans: v("sans", "Arial, sans-serif"),
    };
    // "condensed 800 34px Archivo, sans-serif": font-stretch must be a keyword in ctx.font.
    f.canvas = (px, em = false) => `${em ? f.emStyle + " " : ""}${f.stretchWord} ${em ? f.emWeight : f.displayWeight} ${px}px ${f.display}`;
    return f;
  }

  // Waits for the site's typefaces before anything is drawn on a canvas,
  // so an export never falls back to a system font. Gives up after `ms`.
  function fontsReady(ms = 3000) {
    if (!document.fonts || !document.fonts.load) return Promise.resolve(false);
    const f = brandFonts();
    const loads = Promise.all([
      document.fonts.load(f.canvas(40)),
      document.fonts.load(f.canvas(40, true)),
      document.fonts.load(`${f.deckWeight} 16px ${f.deck}`),
      document.fonts.load(`400 16px ${f.sans}`),
      document.fonts.load(`600 16px ${f.sans}`),
    ]).then(() => document.fonts.ready).then(() => true, () => false);
    return Promise.race([loads, new Promise((r) => setTimeout(() => r(false), ms))]);
  }

  // ---- projects as data files ----------------------------------------------------
  //
  // One column list for every download (the map's filtered list and the
  // About page's full list), so the files always match.

  // A project's own page (pages.py writes one per project), which shows its
  // name and details when the link is shared and forwards to the map.
  function projectUrl(id, origin = location.origin) {
    return `${origin}/p/${encodeURIComponent(id)}/`;
  }
  // The same for a neighborhood council or a council district.
  const hoodUrl = (hoodSlug, origin = location.origin) => `${origin}/n/${encodeURIComponent(hoodSlug)}/`;
  const districtUrl = (n, origin = location.origin) => `${origin}/d/${encodeURIComponent(n)}/`;

  const firstFiled = (p) => ((p.permits || []).map((x) => x.opened).filter(Boolean).sort()[0] || "");
  const blank = (v) => (v === null || v === undefined ? "" : v);

  const PROJECT_COLUMNS = [
    ["id", (p) => p.id],
    ["name", (p) => p.name],
    ["address", (p) => p.address],
    ["neighborhood", (p) => p.neighborhood],
    ["neighborhood_council", (p) => p.neighborhoodCouncil],
    ["council_district", (p) => blank(p.councilDistrict)],
    ["stage", (p) => p.status],
    ["stage_since", (p) => p.statusUpdated],
    ["building_type", (p) => p.buildingType],
    ["middle_housing", (p) => (p.middleHousing ? "yes" : "no")],
    ["units", (p) => (p.units > 0 ? p.units : "")],
    ["stories", (p) => p.stories || ""],
    ["first_filed", (p) => firstFiled(p)],
    ["permits", (p) => (p.permitNumbers || []).join("; ")],
    ["parcel", (p) => p.parcelId],
    ["zoning", (p) => p.zone || ""],
    ["lot_acres", (p) => blank(p.acres)],
    ["homes_per_acre", (p) => blank(p.homesPerAcre)],
    ["miles_to_frequent_transit", (p) => blank(p.transitMiles)],
    ["historic_district", (p) => p.historicDistrict || ""],
    ["mfte_area", (p) => ({ STIA: "Targeted Investment Area", AHEA: "Affordable Housing Emphasis Area" })[p.mfteArea] || ""],
    ["opportunity_zone_2027", (p) => (p.oz2 === undefined ? "" : p.oz2 ? "yes" : "no")],
    ["qualified_census_tract", (p) => (p.qct === undefined ? "" : p.qct ? "yes" : "no")],
    ["census_tract", (p) => p.tract || ""],
    ["lat", (p) => p.lat],
    ["lng", (p) => p.lng],
    ["link", (p) => projectUrl(p.id)],
  ].map(([label, value]) => ({ label, value }));

  const projectsCsv = (projects) => toCsv(projects, PROJECT_COLUMNS);

  // GeoJSON for GIS tools: a point per project with the same fields, plus a
  // note at the top saying where it came from and what was filtered.
  function projectsGeoJson(projects, meta = {}) {
    const props = PROJECT_COLUMNS.filter((c) => c.label !== "lat" && c.label !== "lng");
    const value = (c, p) => {
      const v = c.value(p);
      return v === "" ? null : v;
    };
    return JSON.stringify({
      type: "FeatureCollection",
      name: SITE_NAME,
      source: `${SITE_NAME}, ${SITE_HOST}`,
      ...meta,
      features: projects
        .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng))
        .map((p) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [+p.lng.toFixed(6), +p.lat.toFixed(6)] },
          properties: Object.fromEntries(props.map((c) => [c.label, value(c, p)])),
        })),
    }, null, 1);
  }

  // ---- small pop-up menus (Share, Download) -------------------------------------
  //
  // menu(button, items): opens a list under the button. Each item is
  // { label, href } (a link; opens in a new tab except mailto:) or
  // { label, onSelect }. Arrow keys move, Enter picks, Escape and Tab close,
  // a click outside closes, and focus goes back to the button.

  let openMenuState = null;

  function closeMenu(returnFocus = true) {
    if (!openMenuState) return;
    const { box, anchor, cleanup } = openMenuState;
    openMenuState = null;
    cleanup();
    box.remove();
    anchor.setAttribute("aria-expanded", "false");
    if (returnFocus) anchor.focus();
  }

  function menu(anchor, items, { label = "" } = {}) {
    const same = openMenuState && openMenuState.anchor === anchor;
    closeMenu(false);
    if (same) return null;   // a second click on the same button closes it

    const box = document.createElement("div");
    box.className = "menu";
    box.setAttribute("role", "menu");
    if (label) box.setAttribute("aria-label", label);
    items.forEach((item) => {
      if (item.divider) {
        const hr = document.createElement("div");
        hr.className = "menu__rule";
        hr.setAttribute("role", "separator");
        box.appendChild(hr);
        return;
      }
      const el = document.createElement(item.href ? "a" : "button");
      el.className = "menu__item";
      el.setAttribute("role", "menuitem");
      el.tabIndex = -1;
      el.textContent = item.label;
      if (item.id) el.dataset.item = item.id;
      if (item.note) {
        const small = document.createElement("small");
        small.textContent = item.note;
        el.appendChild(small);
      }
      if (item.href) {
        el.href = item.href;
        if (!item.href.startsWith("mailto:")) {
          el.target = "_blank";
          el.rel = "noopener";
        }
        el.addEventListener("click", () => closeMenu(false));
      } else {
        el.type = "button";
        el.addEventListener("click", () => {
          closeMenu();
          item.onSelect && item.onSelect();
        });
      }
      box.appendChild(el);
    });
    document.body.appendChild(box);

    // Under the button, kept on screen; above it if there's no room below.
    // If the page scrolls, the menu follows its button, and closes once the
    // button has scrolled out of sight.
    const place = () => {
      const r = anchor.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight || (!r.width && !r.height)) return false;
      const w = box.offsetWidth, h = box.offsetHeight;
      // Line up with the button's left edge if it's on the left half of the
      // screen, its right edge otherwise, so the menu opens toward the page.
      const start = r.left + r.width / 2 < window.innerWidth / 2 ? r.left : r.right - w;
      const left = Math.max(8, Math.min(start, window.innerWidth - w - 8));
      const below = r.bottom + 6 + h <= window.innerHeight - 8;
      box.style.left = `${left}px`;
      box.style.top = `${below ? r.bottom + 6 : Math.max(8, r.top - 6 - h)}px`;
      return true;
    };
    place();

    const entries = () => [...box.querySelectorAll(".menu__item")];
    const onKey = (e) => {
      const list = entries();
      const i = list.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
      else if (e.key === "Home") { e.preventDefault(); list[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); list[list.length - 1].focus(); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeMenu(); }  // the menu, not the project behind it
      else if (e.key === "Tab") closeMenu(false);
    };
    const onDown = (e) => {
      if (!box.contains(e.target) && !anchor.contains(e.target)) closeMenu(false);
    };
    const onMove = () => { if (!place()) closeMenu(false); };
    box.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown, true);
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    openMenuState = {
      box, anchor,
      cleanup: () => {
        document.removeEventListener("pointerdown", onDown, true);
        window.removeEventListener("resize", onMove);
        window.removeEventListener("scroll", onMove, true);
      },
    };
    anchor.setAttribute("aria-expanded", "true");
    entries()[0].focus();
    return box;
  }

  // ---- sharing, put together --------------------------------------------------------
  //
  // share(button, {url, title, text}): on phones, the phone's own share
  // sheet; elsewhere (or if the sheet isn't available), a menu with Copy
  // link and each network. Desktop browsers that have a share sheet get it
  // as a last "More options" item.

  // `copied` names the thing in the notice: "Link to this view copied".
  async function share(anchor, { url, title, text, copied = "" }) {
    if (prefersNativeShare()) {
      const result = await nativeShare({ url, title, text });
      if (result !== "unavailable") return result;
    }
    const items = [
      { id: "copy", label: "Copy link", onSelect: async () => {
          if (await window.Share.copyText(url)) toast(copied ? `Link to ${copied} copied` : "Link copied");
          else toast(`Copy this link: ${url}`, 8000);
        } },
      { divider: true },
      ...shareLinks(url, text, title).map((l) => ({ id: l.id, label: l.label, href: l.href })),
    ];
    if (navigator.share) {
      items.push({ divider: true }, { id: "more", label: "More options…", onSelect: () => nativeShare({ url, title, text }) });
    }
    menu(anchor, items, { label: "Share" });
    return "menu";
  }

  // ---- icons and tooltips (polish round, phase B) -----------------------------------
  //
  // Our own line icons on a 20px grid, 1.5px strokes to match the hairline
  // rules. The sprite is added to the page once; buttons use
  // <svg class="icon"><use href="#i-NAME"></use></svg>, or Share.icon(name).

  const ICONS = {
    share: '<path d="M7 8H5v9h10V8h-2"/><path d="M10 12.5V3"/><path d="M6.5 6.5 10 3l3.5 3.5"/>',
    download: '<path d="M10 3v10"/><path d="M6.5 9.5 10 13l3.5-3.5"/><path d="M4 16.5h12"/>',
    link: '<path d="M8.6 11.4l2.8-2.8"/><path d="M9.3 6.4l1.2-1.2a3.1 3.1 0 0 1 4.4 4.4l-1.2 1.2"/><path d="M10.7 13.6l-1.2 1.2a3.1 3.1 0 0 1-4.4-4.4l1.2-1.2"/>',
    mail: '<rect x="3" y="5" width="14" height="10"/><path d="M3.5 5.5 10 11l6.5-5.5"/>',
    camera: '<path d="M3 7h3.2l1.4-2h4.8l1.4 2H17v9H3z"/><circle cx="10" cy="11.3" r="2.7"/>',
    close: '<path d="M5 5l10 10M15 5 5 15"/>',
    city: '<path d="M3 7.5V3h4.5M12.5 3H17v4.5M17 12.5V17h-4.5M7.5 17H3v-4.5"/>',
    plus: '<path d="M10 4v12M4 10h12"/>',
    pencil: '<path d="M4 16l.8-3.6L13 4.2 15.8 7l-8.2 8.2z"/><path d="M11.4 5.8l2.8 2.8"/>',
    help: '<circle cx="10" cy="10" r="7"/><path d="M7.9 8.1a2.2 2.2 0 1 1 3.1 2c-.6.3-1 .8-1 1.4v.4"/><path d="M10 14.4v.1"/>',
  };

  function addSprite() {
    if (document.getElementById("icon-sprite")) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = `<svg id="icon-sprite" xmlns="http://www.w3.org/2000/svg" style="display:none">${
      Object.entries(ICONS).map(([k, v]) => `<symbol id="i-${k}" viewBox="0 0 20 20">${v}</symbol>`).join("")}</svg>`;
    document.body.prepend(wrap.firstChild);
  }

  const icon = (name) => `<svg class="icon" aria-hidden="true" focusable="false"><use href="#i-${name}"></use></svg>`;

  // Tooltips for icon buttons: the button's aria-label (or data-tip), shown
  // after a short pause on hover and at once on keyboard focus. One floating
  // label, kept on screen, under the button (above it if there's no room).
  let tipEl = null, tipFor = null, tipTimer = 0;
  function tipText(b) { return b.dataset.tip || b.getAttribute("aria-label") || ""; }
  function showTip(b) {
    clearTimeout(tipTimer);
    if (openMenuState && openMenuState.anchor === b) return;
    const text = tipText(b);
    if (!text) return;
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "tip-label";
      tipEl.setAttribute("aria-hidden", "true");
      document.body.appendChild(tipEl);
    }
    tipEl.textContent = text;
    tipEl.classList.add("is-on");
    tipFor = b;
    const r = b.getBoundingClientRect(), w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    const left = Math.max(6, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 6));
    const below = r.bottom + 6 + h <= window.innerHeight - 6;
    tipEl.style.left = `${left}px`;
    tipEl.style.top = `${below ? r.bottom + 6 : r.top - 6 - h}px`;
  }
  function hideTip() {
    clearTimeout(tipTimer);
    tipFor = null;
    if (tipEl) tipEl.classList.remove("is-on");
  }
  function wireTips() {
    const target = (e) => e.target && e.target.closest && e.target.closest(".iconbtn");
    // A showing tooltip can be pointed at (WCAG 1.4.13, hoverable): its hit
    // area reaches across the 6px gap (CSS), so the pointer goes straight from
    // the button onto it, and it hides as soon as the pointer is on neither.
    const onTip = (n) => !!(tipEl && n && tipEl.contains(n));
    document.addEventListener("pointerover", (e) => {
      if (e.pointerType === "touch" || onTip(e.target)) return;
      const b = target(e);
      if (!b || b === tipFor) return;
      hideTip();
      tipTimer = setTimeout(() => showTip(b), 400);
    });
    document.addEventListener("pointerout", (e) => {
      const to = e.relatedTarget;
      if (onTip(e.target)) { if (!onTip(to) && !(tipFor && tipFor.contains(to))) hideTip(); return; }
      const b = target(e);
      if (b && !b.contains(to) && !onTip(to)) hideTip();
    });
    document.addEventListener("focusin", (e) => {
      const b = target(e);
      if (b && b.matches(":focus-visible")) showTip(b);
    });
    document.addEventListener("focusout", (e) => { if (target(e)) hideTip(); });
    document.addEventListener("pointerdown", hideTip, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
    window.addEventListener("scroll", hideTip, true);
  }
  // A tooltip that's showing follows a label change (e.g. "Saving…").
  function retip(b) { if (tipFor === b) showTip(b); }

  if (document.body) { addSprite(); wireTips(); }
  else document.addEventListener("DOMContentLoaded", () => { addSprite(); wireTips(); });

  window.Share = {
    icon, retip, hideTip,
    SITE_NAME, SITE_HOST,
    shareLinks, nativeShare, prefersNativeShare,
    copyText,
    downloadBlob, downloadText, downloadCanvas, filename, toCsv,
    toast,
    creditLine, fontsReady, brandFonts,
    projectUrl, hoodUrl, districtUrl, PROJECT_COLUMNS, projectsCsv, projectsGeoJson,
    menu, closeMenu, share,
  };
})();
