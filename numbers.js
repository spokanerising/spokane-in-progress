// Bold numbers (issue #42). Wherever the site states a quantity (homes,
// projects, counts, sizes, costs, shares), the figure is set bold so it stands
// out from the words around it, in the serif lines and the sans data alike.
//
// The pages build most of their text in JavaScript, so this watches the page
// and wraps each figure in <b class="num"> inside the places listed in AREAS.
// Addresses, project names, dates, years, zoning codes and parcel numbers are
// left alone: AREAS never covers names or addresses, and DATE below skips
// dates and years.
(function () {
  "use strict";

  // Where figures are quantities. A spec row counts only when its label is one
  // of SPEC_LABELS (so "Zoning CB-150" and parcel numbers stay plain).
  const AREAS = [
    ".lede", ".spine__key", ".figure__title", ".tally", ".inview", ".card__facts", ".tipcard__facts",
    ".standfirst", ".chip__n", ".picker__n", ".pill", ".mapkey",
    ".article__dek", ".stat", ".bars__value", ".bars__n", ".cols__n", ".table td", ".share__value",
    ".chart__title", ".section__lede", ".deflist dd",
  ].join(", ");
  const SPEC_LABELS = /^(housing units|homes|floor area|stories|parking stalls|estimated cost|lot size|homes per acre|frequent transit|units)$/i;
  const SKIP = "b, strong, .num, script, style, textarea, input, select, option, code, pre, a.card__name, [contenteditable], .no-num";

  const MONTH = "(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\\.?";
  // Dates ("Nov. 27, 2026", "July 16"), years alone ("2026", "Q3 2025") and quarters.
  const DATE = new RegExp(`\\b${MONTH}\\s+\\d{1,2}(?:,\\s*\\d{4})?|\\bQ[1-4]\\b|\\b(?:19|20)\\d{2}\\b`, "g");
  // A figure: optional $, digits with thousands commas, a decimal part, an optional %, ½ or ¼.
  const FIGURE = /\$?\d[\d,]*(?:\.\d+)?%?|[½¼¾]/g;

  function inArea(node) {
    const el = node.parentElement;
    if (!el || el.closest(SKIP)) return false;
    const area = el.closest(AREAS);
    if (area) return true;
    const dd = el.closest(".specs dd");
    if (dd) {
      const dt = dd.previousElementSibling;
      return !!(dt && dt.tagName === "DT" && SPEC_LABELS.test(dt.textContent.trim()));
    }
    return false;
  }

  function wrapText(node) {
    const text = node.nodeValue;
    if (!text || !/\d|[½¼¾]/.test(text) || !inArea(node)) return;
    // Mark the spans that are dates, then wrap every figure outside them.
    const blocked = [];
    text.replace(DATE, (m, i) => { blocked.push([i, i + m.length]); return m; });
    const hits = [];
    text.replace(FIGURE, (m, i) => {
      const end = i + m.length;
      if (!blocked.some(([a, b]) => i < b && end > a)) hits.push([i, end]);
      return m;
    });
    if (!hits.length) return;
    const frag = document.createDocumentFragment();
    let at = 0;
    for (const [a, b] of hits) {
      if (a > at) frag.appendChild(document.createTextNode(text.slice(at, a)));
      const num = document.createElement("b");
      num.className = "num";
      num.textContent = text.slice(a, b);
      frag.appendChild(num);
      at = b;
    }
    if (at < text.length) frag.appendChild(document.createTextNode(text.slice(at)));
    node.parentNode.replaceChild(frag, node);
  }

  function scan(root) {
    if (root.nodeType === Node.TEXT_NODE) return wrapText(root);
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(wrapText);
  }

  let busy = false;
  function onChange(records) {
    if (busy) return;
    busy = true;
    try {
      for (const r of records) {
        if (r.type === "characterData") scan(r.target);
        else r.addedNodes.forEach(scan);
      }
    } finally {
      observer.takeRecords();   // our own wrapping isn't news
      busy = false;
    }
  }
  const observer = new MutationObserver(onChange);
  function start() {
    scan(document.body);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();
