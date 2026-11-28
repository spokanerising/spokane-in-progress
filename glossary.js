// Glossary: dotted-underlined terms that open a short definition, and the
// full list on the Glossary page (/glossary, glossary.html). Definitions live in glossary.json.
//
//   Gloss.term(id, html)   wrap already-escaped html in a term button
//   Gloss.stage(status) / Gloss.type(buildingType) / Gloss.permitKind(type) /
//   Gloss.permitStatus(status)   the glossary id for a value, or ""
//   Gloss.list(box)        draw every term into box (Glossary page)
//   Gloss.load()           the glossary data, once loaded (About's stage list)
(function () {
  "use strict";

  let data = null, loading = null;
  const byId = {};
  function load() {
    if (data) return Promise.resolve(data);
    return (loading ||= fetch("glossary.json")
      .then((r) => { if (!r.ok) throw new Error(`glossary.json: ${r.status}`); return r.json(); })
      .then((json) => {
        data = json;
        json.groups.forEach((g) => g.terms.forEach((t) => { byId[t.id] = t; }));
        return data;
      })
      .catch((err) => { loading = null; throw err; }));
  }

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const term = (id, html) =>
    id ? `<button type="button" class="gloss" data-gloss="${esc(id)}" aria-expanded="false">${html}</button>` : html;

  // Values in the data mapped to glossary ids.
  const STAGE = {
    "Pre-Application": "pre-application", Applied: "applied", Approved: "approved",
    "Under Construction": "under-construction", Complete: "complete", Stalled: "stalled",
  };
  const TYPE = {
    Townhomes: "townhomes", "Cottage housing": "cottage-housing", "House + ADU": "adu",
    "Conversion or addition": "conversion", "Senior & group living": "senior-group", "Middle housing": "middle-housing",
  };
  const KIND = {
    "Pre-Development Conference": "pre-development-conference", "SEPA Review": "sepa",
    "Design Review Board": "design-review", "Commercial Change of Use": "change-of-use",
    "Private Development": "private-development", "Final Short Plat": "short-plat",
    "Boundary Line Adjustment": "lot-line-adjustment", "Grading Permit": "grading",
  };
  function permitStatus(s) {
    const v = String(s || "").toLowerCase();
    if (!v) return "";
    if (v.startsWith("co final")) return "co-final";
    if (v.startsWith("final") || v === "completed") return "finaled";
    if (v.startsWith("issued")) return "issued";
    if (v.startsWith("plan review approved")) return "plan-review-approved";
    if (v.startsWith("plan review")) return "plan-review";
    if (v.startsWith("revisions")) return "revisions-required";
    if (v.startsWith("recording")) return "recording";
    if (v === "pending") return "pending";
    if (v === "closed") return "closed";
    return "";
  }

  // ---- the popover ---------------------------------------------------------
  let pop = null, openFor = null, pinned = false, hoverTimer = 0, leaveTimer = 0, openAt = null;
  const canHover = () => window.matchMedia("(hover: hover)").matches;
  const onGlossaryPage = () => !!document.getElementById("glossary");

  function ensurePop() {
    if (pop) return pop;
    pop = document.createElement("div");
    pop.className = "glosspop";
    pop.id = "glosspop";
    pop.setAttribute("role", "dialog");
    pop.hidden = true;
    pop.addEventListener("mouseenter", () => clearTimeout(leaveTimer));
    pop.addEventListener("mouseleave", () => { if (!pinned) leaveTimer = setTimeout(close, 200); });
    document.body.appendChild(pop);
    return pop;
  }

  function place(button) {
    const r = button.getBoundingClientRect(), gap = 6, edge = 8;
    pop.style.left = "0px"; pop.style.top = "0px";
    const w = pop.offsetWidth, h = pop.offsetHeight;
    let left = Math.min(Math.max(edge, r.left), window.innerWidth - w - edge);
    let top = r.bottom + gap;
    if (top + h > window.innerHeight - edge && r.top - gap - h > edge) top = r.top - gap - h;
    pop.style.left = `${Math.round(left + window.scrollX)}px`;
    pop.style.top = `${Math.round(top + window.scrollY)}px`;
  }

  async function open(button, pin) {
    clearTimeout(leaveTimer);
    if (openFor === button) { if (pin) pinned = true; return; }
    try { await load(); } catch (e) { return; }
    const t = byId[button.dataset.gloss];
    if (!t) return;
    close();
    ensurePop();
    const more = onGlossaryPage() ? `#g-${t.id}` : `/glossary#g-${t.id}`;
    pop.setAttribute("aria-label", t.term);
    pop.innerHTML = `<p class="glosspop__term">${esc(t.term)}</p>
      <p class="glosspop__def">${esc(t.definition)}</p>
      <a class="glosspop__more" href="${more}">All terms <span aria-hidden="true">→</span></a>`;
    pop.hidden = false;
    place(button);
    openFor = button;
    openAt = button.getBoundingClientRect();
    pinned = !!pin;
    button.setAttribute("aria-expanded", "true");
    button.setAttribute("aria-controls", "glosspop");
  }

  function close(returnFocus) {
    clearTimeout(hoverTimer); clearTimeout(leaveTimer);
    if (!openFor) return;
    const b = openFor;
    openFor = null; pinned = false;
    if (pop) pop.hidden = true;
    b.setAttribute("aria-expanded", "false");
    b.removeAttribute("aria-controls");
    if (returnFocus && document.contains(b)) b.focus();
  }

  function wire() {
    document.addEventListener("click", (e) => {
      const b = e.target.closest(".gloss");
      if (b) {
        e.preventDefault();
        e.stopPropagation();
        if (openFor === b && pinned) close();
        else open(b, true);
        return;
      }
      if (openFor && pop && !pop.contains(e.target)) close();
    }, true);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && openFor) {
        const focusInside = pop.contains(document.activeElement) || document.activeElement === openFor;
        e.stopPropagation();
        close(focusInside);
      }
    }, true);
    document.addEventListener("mouseover", (e) => {
      if (!canHover()) return;
      const b = e.target.closest && e.target.closest(".gloss");
      if (!b) return;
      clearTimeout(hoverTimer); clearTimeout(leaveTimer);
      if (openFor !== b) hoverTimer = setTimeout(() => open(b, false), 350);
    });
    document.addEventListener("mouseout", (e) => {
      const b = e.target.closest && e.target.closest(".gloss");
      if (!b || b.contains(e.relatedTarget)) return;
      clearTimeout(hoverTimer);
      if (openFor === b && !pinned) leaveTimer = setTimeout(close, 200);
    });
    // Scrolling the page or a panel moves the term away from its popover. A
    // scroll that leaves the term where it was (the browser keeping it in place
    // while a picture above it loads) changes nothing.
    document.addEventListener("scroll", (e) => {
      if (!openFor || (pop && pop.contains(e.target))) return;
      const r = openFor.getBoundingClientRect();
      if (openAt && Math.abs(r.top - openAt.top) < 2 && Math.abs(r.left - openAt.left) < 2) return;
      close();
    }, true);
    window.addEventListener("resize", () => close());
  }

  // ---- the Glossary page list ----------------------------------------------
  // Jump links to each group, then each group as a section with its own
  // heading. Every term has an anchor (#g-finaled) so popovers, project pages
  // and readers can link straight to it.
  async function list(box) {
    if (!box) return;
    try { await load(); } catch (e) {
      box.innerHTML = `<p>The glossary didn’t load. Please refresh the page.</p>`;
      return;
    }
    const jumps = document.getElementById("glossary-jumps");
    if (jumps) {
      jumps.innerHTML = data.groups.map((g) =>
        `<li><a href="#${esc(g.id)}">${esc(g.title)}</a> <span>${g.terms.length}</span></li>`).join("");
    }
    box.innerHTML = data.groups.map((g) => `
      <section class="section" aria-labelledby="${esc(g.id)}">
        <h2 class="section__hed" id="${esc(g.id)}">${esc(g.title)}</h2>
        <dl class="deflist deflist--gloss">${g.terms.map((t) =>
          `<dt id="g-${esc(t.id)}">${esc(t.term)}</dt><dd>${esc(t.definition)}</dd>`).join("")}</dl>
      </section>`).join("");
    // Arriving from a link to a term or group: the target exists only now.
    // Later jumps within the page highlight the term they land on.
    const mark = (scroll) => {
      const el = location.hash.length > 1 && document.getElementById(decodeURIComponent(location.hash.slice(1)));
      if (!el || !box.contains(el)) return;
      if (scroll) el.scrollIntoView();
      box.querySelectorAll("dt.is-target").forEach((d) => d.classList.remove("is-target"));
      if (el.tagName === "DT") el.classList.add("is-target");
    };
    mark(true);
    window.addEventListener("hashchange", () => mark(false));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
  else wire();

  window.Gloss = {
    load, term, list,
    stage: (s) => STAGE[s] || "",
    type: (t) => TYPE[t] || "",
    permitKind: (t) => KIND[t] || "",
    permitStatus,
  };
})();
