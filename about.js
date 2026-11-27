// Spokane in Progress — About page (about.html).
// The page reads fine without this script. It adds three live touches:
//   - the "Data as of" date and the stage colors, from projects.json
//   - the count in "N projects have no unit count yet", from projects.json
//   - the stage definitions, from glossary.json, so they always match the
//     Glossary page and the map's popovers (the HTML holds a copy as a fallback)

(function () {
  "use strict";

  const STAGE_IDS = ["pre-application", "applied", "approved", "under-construction", "complete", "stalled"];
  const AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];

  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n).toLocaleString("en-US");

  function apDate(value) {
    const d = new Date(value);
    return isNaN(d) ? "" : `${AP_MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
  }

  async function projectFacts() {
    try {
      const response = await fetch("projects.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`projects.json returned HTTP ${response.status}`);
      const payload = await response.json();
      (payload.stages || []).forEach((st, i) => document.body.style.setProperty(`--s${i}`, st.color));
      const when = apDate(payload.builtAt);
      if (when) document.getElementById("asof").textContent = `Data as of ${when}. Updated every morning from the city’s permit records.`;
      const missing = (payload.projects || []).filter((p) => !(p.units > 0)).length;
      const unitsLimit = document.getElementById("limit-units");
      if (unitsLimit && missing) {
        unitsLimit.querySelector("strong").textContent =
          `${fmt(missing)} ${missing === 1 ? "project has" : "projects have"} no unit count yet.`;
      }
    } catch (error) {
      console.warn(error);   // the page still reads fine with its default text
    }
  }

  async function stageList() {
    const box = document.getElementById("stage-list");
    if (!box || !window.Gloss) return;
    try {
      const data = await Gloss.load();
      const group = data.groups.find((g) => g.id === "stages");
      if (!group) return;
      box.innerHTML = group.terms.map((t) => {
        const i = STAGE_IDS.indexOf(t.id);
        const dot = i >= 0 ? `<i style="--c:var(--s${i})"></i>` : "";
        return `<dt id="stage-${esc(t.id)}">${dot}${esc(t.term)}</dt><dd>${esc(t.definition)}</dd>`;
      }).join("");
    } catch (error) {
      console.warn(error);   // keep the copy in the HTML
    }
  }

  projectFacts();
  stageList();
})();
