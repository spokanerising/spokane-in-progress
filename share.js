// Spokane in Progress — shared tools for sharing and downloading.
// Loaded before app.js (the map) and about.js (Stats & About), so both pages
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

  // Waits for the site's two typefaces before anything is drawn on a canvas,
  // so an export never falls back to a system font. Gives up after `ms`.
  function fontsReady(ms = 3000) {
    if (!document.fonts || !document.fonts.load) return Promise.resolve(false);
    const loads = Promise.all([
      document.fonts.load('500 40px "Newsreader"'),
      document.fonts.load('600 40px "Newsreader"'),
      document.fonts.load('400 16px "Libre Franklin"'),
      document.fonts.load('600 16px "Libre Franklin"'),
    ]).then(() => document.fonts.ready).then(() => true, () => false);
    return Promise.race([loads, new Promise((r) => setTimeout(() => r(false), ms))]);
  }

  window.Share = {
    SITE_NAME, SITE_HOST,
    shareLinks, nativeShare, prefersNativeShare,
    copyText,
    downloadBlob, downloadText, downloadCanvas, filename, toCsv,
    toast,
    creditLine, fontsReady,
  };
})();
