// Spokane in Progress — map, list, filters, detail panel.
// Reads projects.json, which build.py generates from your sheet.

// Stages are defined in build.py and travel with the data, so this list is only
// a fallback for when the data fails to load. Edit build.py, not this.
// The five live stages are one hue stepping from light to dark, so the order
// reads in the color itself. Stalled sits off the ramp in neutral gray.
let STAGES = [
  { name: "Pre-Application",     color: "#ea957a" },
  { name: "Applied",             color: "#d66a48" },
  { name: "Approved",            color: "#b6451f" },
  { name: "Under Construction",  color: "#8a2f10" },
  { name: "Complete",            color: "#592211" },
  { name: "Stalled",             color: "#8f8c86" },
];

// Roughly the City of Spokane limits. The map opens here.
const CITY_BOUNDS = [[-117.545, 47.598], [-117.300, 47.748]];

// Aerial imagery for the satellite view. Esri's World Imagery needs no key or
// account and covers Spokane to z19. The attribution is required and rides on
// the source, so MapLibre shows it whenever the layer is drawn.
const SATELLITE_TILES =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const SATELLITE_CREDIT =
  'Imagery &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a>, Maxar, Earthstar Geographics';

const colorOf = (status) =>
  (STAGES.find((s) => s.name === status) || STAGES[STAGES.length - 1]).color;
const indexOf = (status) => STAGES.findIndex((s) => s.name === status);

// Building types, in the order the filter lists them. These names come from
// housing_types.py, which assigns them during the build.
const MIDDLE_TYPES = ["Duplex", "Triplex or fourplex", "Fiveplex or sixplex", "Townhomes", "Cottage housing"];
const OTHER_TYPES = ["Apartments", "House + ADU", "Conversion or addition", "Senior & group living"];
const UNKNOWN_TYPE = "Not yet known";

// Project size, by every home in the project.
const SIZES = [
  { key: "2-4", label: "2–4 homes", test: (u) => u >= 2 && u <= 4 },
  { key: "5-19", label: "5–19 homes", test: (u) => u >= 5 && u <= 19 },
  { key: "20-99", label: "20–99 homes", test: (u) => u >= 20 && u <= 99 },
  { key: "100", label: "100 or more homes", test: (u) => u >= 100 },
  { key: "unknown", label: "Size not reported", test: (u) => !(u > 0) },
];

const typeOf = (p) => p.buildingType || UNKNOWN_TYPE;

const ALL_TYPES = [...MIDDLE_TYPES, ...OTHER_TYPES, UNKNOWN_TYPE];

// state.types holds every building type currently switched on.
const allTypesOn = () => ALL_TYPES.every((t) => state.types.has(t));
const matchesType = (p) => allTypesOn() || state.types.has(typeOf(p));

function matchesSize(p, size) {
  if (size === "all") return true;
  const bucket = SIZES.find((s) => s.key === size);
  return bucket ? bucket.test(p.units) : true;
}

// ---- timeline -----------------------------------------------------------

const DAY = 24 * 60 * 60 * 1000;
const isoToTime = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : null;
};

// The earliest city record for the project (a pre-development meeting counts).
function firstFiled(p) {
  const dates = (p.permits || []).map((x) => x.opened).filter(Boolean).sort();
  return dates.length ? dates[0] : "";
}

// Ages are measured from the day the data was built, not today, so the
// filter means the same thing however long a page sits open.
function ageInDays(iso) {
  const t = isoToTime(iso);
  if (t === null) return null;
  const ref = state.builtAt ? state.builtAt.getTime() : Date.now();
  return Math.floor((ref - t) / DAY);
}

const TIMES = [
  { key: "filed:30", group: "First filed with the city", label: "Filed in the past 30 days", test: (p) => within(firstFiled(p), 30) },
  { key: "filed:90", group: "First filed with the city", label: "Filed in the past 3 months", test: (p) => within(firstFiled(p), 91) },
  { key: "filed:365", group: "First filed with the city", label: "Filed in the past 12 months", test: (p) => within(firstFiled(p), 365) },
  { key: "filed:old", group: "First filed with the city", label: "Filed more than a year ago", test: (p) => { const a = ageInDays(firstFiled(p)); return a !== null && a > 365; } },
  { key: "filed:none", group: "First filed with the city", label: "Filing date not known", test: (p) => !firstFiled(p) },
  { key: "stage:30", group: "Reached its current stage", label: "New stage in the past 30 days", test: (p) => within(p.statusUpdated, 30) },
  { key: "stage:90", group: "Reached its current stage", label: "New stage in the past 3 months", test: (p) => within(p.statusUpdated, 91) },
  { key: "stage:365", group: "Reached its current stage", label: "New stage in the past 12 months", test: (p) => within(p.statusUpdated, 365) },
];

function within(iso, days) {
  const a = ageInDays(iso);
  return a !== null && a >= 0 && a <= days;
}

const matchesTime = (p) => {
  if (state.time === "all") return true;
  const t = TIMES.find((x) => x.key === state.time);
  return t ? t.test(p) : true;
};

// ---- place --------------------------------------------------------------

const councilOf = (p) => p.neighborhoodCouncil ?? "";

const matchesPlace = (p) => {
  const [kind, value] = state.place.split(/:(.*)/s);
  if (kind === "all") return true;
  if (kind === "district") return String(p.councilDistrict ?? "") === value;
  if (kind === "hood") return councilOf(p) === value;
  return true;
};

const state = {
  projects: [],
  hidden: new Set(),
  query: "",
  types: new Set([...MIDDLE_TYPES, ...OTHER_TYPES, UNKNOWN_TYPE]),
  size: "all",
  time: "all",
  place: "all",
  selected: null,
  builtAt: null,
  measure: "homes", // what the stage bar is sized by: "homes" or "projects"
  sort: "recent",   // list order; see SORTS
};

// Stages that count toward "in the pipeline": filed, not finished, not stalled.
// Pre-Application is reported separately as "proposed".
const PIPELINE = ["Applied", "Approved", "Under Construction"];

const unitsOf = (list) => list.reduce((sum, p) => sum + (p.units > 0 ? p.units : 0), 0);
const unknownUnits = (list) => list.filter((p) => !(p.units > 0)).length;

const el = {
  cards: document.getElementById("cards"),
  chips: document.getElementById("status-chips"),
  spine: document.getElementById("spine"),
  spineKey: document.getElementById("spine-key"),
  tally: document.getElementById("tally"),
  empty: document.getElementById("empty"),
  search: document.getElementById("search"),
  detail: document.getElementById("detail"),
  detailBody: document.getElementById("detail-body"),
  countStamp: document.getElementById("count-stamp"),
};

let map;

// Positron's label layers, with the halo they ship with, captured at load so
// the satellite view can thicken them and the map view can put them back.
let labelLayers = [];

// --------------------------------------------------------------------------

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

const numberWithCommas = (n) => n.toLocaleString("en-US");

// "Address · Neighborhood", without a stray dot when either is missing.
const where = (p) => [p.address, p.neighborhood].filter(Boolean).join(" · ");

const plural = (n, one, many) => `${numberWithCommas(n)} ${n === 1 ? one : many}`;

// Dates in newspaper (AP) style: "Nov. 18, 2026", "March 4, 2026".
const AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
function apDate(value) {
  if (!value) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(value);
  if (isNaN(d)) return String(value);
  return `${AP_MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

// Circle area is proportional to housing units. The same numbers drive the map
// layer (as a MapLibre expression) and the map key (as plain JavaScript), so
// the key always matches the map. Each stop: [zoom, pixels per sqrt(unit), smallest radius].
const SIZE_STOPS = [
  [10, 0.75, 3],
  [13, 1.1, 4.5],
  [17, 1.8, 7],
];
const UNKNOWN_BOOST = 0.5; // hollow rings get a touch more radius so they read as rings

function radiusAt(zoom, units) {
  const stops = SIZE_STOPS;
  let lo = stops[0], hi = stops[stops.length - 1];
  if (zoom <= lo[0]) hi = lo;
  else if (zoom >= hi[0]) lo = hi;
  else {
    for (let i = 0; i < stops.length - 1; i++) {
      if (zoom >= stops[i][0] && zoom <= stops[i + 1][0]) { lo = stops[i]; hi = stops[i + 1]; break; }
    }
  }
  const at = (s) => (units > 0 ? Math.max(s[2], s[1] * Math.sqrt(units)) : s[2] + UNKNOWN_BOOST);
  if (lo === hi) return at(lo);
  const t = (zoom - lo[0]) / (hi[0] - lo[0]);
  return at(lo) + t * (at(hi) - at(lo));
}

function radiusExpression() {
  const units = ["get", "units"];
  const at = (s) => [
    "case",
    [">", units, 0],
    ["max", s[2], ["*", s[1], ["sqrt", units]]],
    s[2] + UNKNOWN_BOOST,
  ];
  return ["interpolate", ["linear"], ["zoom"], ...SIZE_STOPS.flatMap((s) => [s[0], at(s)])];
}

// Developer, architect, cost and the rest arrive inside fields[], not as
// top-level keys, so search reads the field values instead of naming keys that
// do not exist. Links are skipped so a query cannot match a bare URL.
const searchText = (p) =>
  [p.name, p.address, p.neighborhood, p.buildingType, p.middleHousing ? "middle housing" : ""]
    .concat((p.fields || []).filter((f) => f.kind !== "link").map((f) => f.value))
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

// ---- list order -------------------------------------------------------------

const SORTS = {
  recent: (a, b) => (b.statusUpdated || "").localeCompare(a.statusUpdated || ""),
  homes: (a, b) => (b.units > 0 ? b.units : -1) - (a.units > 0 ? a.units : -1),
  stage: (a, b) => {
    // Furthest along first; Stalled sorts last rather than past Complete.
    const rank = (p) => (p.status === "Stalled" ? -1 : indexOf(p.status));
    return rank(b) - rank(a) || (b.units || 0) - (a.units || 0);
  },
  filed: (a, b) => (firstFiled(b) || "").localeCompare(firstFiled(a) || ""),
  name: (a, b) => a.name.localeCompare(b.name, "en", { numeric: true }),
};

const sorted = (list) => [...list].sort((a, b) => SORTS[state.sort](a, b) || a.name.localeCompare(b.name));

function visible() {
  const q = state.query.trim().toLowerCase();
  return state.projects.filter((p) => {
    if (state.hidden.has(p.status)) return false;
    if (!matchesType(p)) return false;
    if (!matchesSize(p, state.size)) return false;
    if (!matchesTime(p)) return false;
    if (!matchesPlace(p)) return false;
    if (!q) return true;
    return searchText(p).includes(q);
  });
}

// --------------------------------------------------------------------------

function drawSpine() {
  const homes = state.measure === "homes";
  const counts = STAGES.map((s) => {
    const inStage = state.projects.filter((p) => p.status === s.name);
    return { ...s, projects: inStage.length, homes: unitsOf(inStage) };
  });
  const value = (s) => (homes ? s.homes : s.projects);
  const noun = homes ? "homes" : "projects";

  el.countStamp.textContent = homes
    ? `${numberWithCommas(unitsOf(state.projects))} homes, by stage`
    : `${numberWithCommas(state.projects.length)} projects, by stage`;
  el.spine.setAttribute("aria-label", homes ? "Homes by stage" : "Projects by stage");

  el.spine.innerHTML = counts
    .filter((s) => value(s) > 0)
    .map(
      (s) =>
        `<div class="spine__seg" style="flex-grow:${value(s)};background:${s.color}" title="${numberWithCommas(value(s))} ${noun}: ${escapeHtml(s.name.toLowerCase())}"></div>`
    )
    .join("");

  el.spineKey.innerHTML = counts
    .map(
      (s) =>
        `<li><i style="background:${s.color}"></i><b>${numberWithCommas(value(s))}</b> ${escapeHtml(s.name.toLowerCase())}</li>`
    )
    .join("");

  document.querySelectorAll("#measure button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.measure === state.measure))
  );
}

// The headline sentence. "At least" because projects with no reported unit
// count add nothing to the totals.
function drawLede() {
  const box = document.getElementById("lede");
  if (!box || !state.projects.length) return;
  const inStages = (names) => state.projects.filter((p) => names.includes(p.status));
  const pipeline = unitsOf(inStages(PIPELINE));
  const building = unitsOf(inStages(["Under Construction"]));
  const proposed = unitsOf(inStages(["Pre-Application"]));
  const n = (x) => `<b>${numberWithCommas(x)}</b>`;
  box.innerHTML =
    `At least ${n(pipeline)} homes are working their way through Spokane’s permit process, ` +
    `${n(building)} of them under construction.` +
    (proposed ? ` Developers have proposed ${n(proposed)} more.` : "");
}

function drawNote() {
  const note = document.getElementById("spine-source");
  if (!note) return;
  const missing = unknownUnits(state.projects);
  note.textContent =
    "Note: " +
    (missing ? `Home totals leave out ${plural(missing, "project", "projects")} with no reported unit count. ` : "") +
    `Construction status is estimated from permit activity. ${sourceLine()}`;
}

function drawChips() {
  el.chips.innerHTML = STAGES.map(
    (s) =>
      `<button class="chip" type="button" aria-pressed="true" data-status="${escapeHtml(s.name)}" style="--stage:${s.color}">
         <i></i>${escapeHtml(s.name)}
       </button>`
  ).join("");

  el.chips.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const status = chip.dataset.status;
      if (state.hidden.has(status)) state.hidden.delete(status);
      else state.hidden.add(status);
      chip.setAttribute("aria-pressed", String(!state.hidden.has(status)));
      render();
    });
  });
}

// The two dropdowns. Counts are for the whole map, so they don't jump around
// as other filters change.
function drawSelects() {
  const all = state.projects;
  const count = (fn) => all.filter(fn).length;
  const opt = (value, label, n) =>
    `<option value="${escapeHtml(value)}">${escapeHtml(label)}${n === undefined ? "" : ` (${n})`}</option>`;

  drawTypePicker();

  const sizeSelect = document.getElementById("size-filter");
  sizeSelect.innerHTML =
    opt("all", "All sizes") + SIZES.map((s) => opt(s.key, s.label, count((p) => s.test(p.units)))).join("");
  sizeSelect.value = state.size;

  const timeSelect = document.getElementById("time-filter");
  const groups = [...new Set(TIMES.map((t) => t.group))];
  timeSelect.innerHTML =
    opt("all", "Any time") +
    groups
      .map(
        (g) =>
          `<optgroup label="${escapeHtml(g)}">${TIMES.filter((t) => t.group === g)
            .map((t) => opt(t.key, t.label, count(t.test)))
            .join("")}</optgroup>`
      )
      .join("");
  timeSelect.value = state.time;

  const placeSelect = document.getElementById("place-filter");
  const districts = [...new Set(all.map((p) => p.councilDistrict).filter((d) => d != null))].sort();
  const hoods = [...new Set(all.map(councilOf).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const outside = count((p) => !councilOf(p));
  placeSelect.innerHTML =
    opt("all", "All of Spokane") +
    `<optgroup label="City Council district">${districts
      .map((d) => opt(`district:${d}`, `District ${d}`, count((p) => p.councilDistrict === d)))
      .join("")}</optgroup>` +
    `<optgroup label="Neighborhood council">${hoods
      .map((h) => opt(`hood:${h}`, h, count((p) => councilOf(p) === h)))
      .join("")}</optgroup>` +
    (outside ? opt("hood:", "No neighborhood council", outside) : "");
  placeSelect.value = state.place;
}

// ---- building type checklist ----------------------------------------------

function typeSummary() {
  const on = ALL_TYPES.filter((t) => state.types.has(t));
  if (on.length === ALL_TYPES.length) return "All building types";
  if (on.length === 0) return "No types selected";
  const sameAs = (list) => list.length === on.length && list.every((t) => on.includes(t));
  if (sameAs(MIDDLE_TYPES)) return "Middle housing";
  if (sameAs(OTHER_TYPES)) return "Other housing";
  if (on.length <= 2) return on.join(", ");
  return `${on.length} types`;
}

function drawTypePicker() {
  const panel = document.getElementById("type-panel");
  const count = (t) => state.projects.filter((p) => typeOf(p) === t).length;
  const groupCount = (list) => state.projects.filter((p) => list.includes(typeOf(p))).length;
  const box = (type) =>
    `<label class="picker__item">
       <input type="checkbox" data-type="${escapeHtml(type)}"${state.types.has(type) ? " checked" : ""}>
       <span>${escapeHtml(type === UNKNOWN_TYPE ? "Type not yet known" : type)}</span>
       <span class="picker__n">${count(type)}</span>
     </label>`;
  const group = (key, label, list) =>
    `<div class="picker__group">
       <label class="picker__item picker__item--group">
         <input type="checkbox" data-group="${key}">
         <span>${label}</span>
         <span class="picker__n">${groupCount(list)}</span>
       </label>
       ${list.map(box).join("")}
     </div>`;

  panel.innerHTML = `
    <div class="picker__quick">
      <button type="button" data-quick="all">All types</button>
      <button type="button" data-quick="middle">Only middle housing</button>
    </div>
    ${group("middle", "Middle housing", MIDDLE_TYPES)}
    ${group("other", "Other housing", OTHER_TYPES)}
    <div class="picker__group">${box(UNKNOWN_TYPE)}</div>`;

  syncGroupBoxes();
  document.getElementById("type-summary").textContent = typeSummary();
}

// A group box is checked when all its types are on, half-checked when some are.
function syncGroupBoxes() {
  const groups = { middle: MIDDLE_TYPES, other: OTHER_TYPES };
  document.querySelectorAll("#type-panel input[data-group]").forEach((input) => {
    const list = groups[input.dataset.group];
    const on = list.filter((t) => state.types.has(t)).length;
    input.checked = on === list.length;
    input.indeterminate = on > 0 && on < list.length;
  });
}

function wireTypePicker() {
  const panel = document.getElementById("type-panel");
  const picker = document.getElementById("type-picker");
  const groups = { middle: MIDDLE_TYPES, other: OTHER_TYPES };

  panel.addEventListener("change", (e) => {
    const input = e.target;
    if (input.dataset.type) {
      if (input.checked) state.types.add(input.dataset.type);
      else state.types.delete(input.dataset.type);
    } else if (input.dataset.group) {
      groups[input.dataset.group].forEach((t) =>
        input.checked ? state.types.add(t) : state.types.delete(t)
      );
    }
    drawTypePicker();
    render();
  });

  panel.addEventListener("click", (e) => {
    const quick = e.target.closest("button[data-quick]");
    if (!quick) return;
    state.types = new Set(quick.dataset.quick === "middle" ? MIDDLE_TYPES : ALL_TYPES);
    drawTypePicker();
    render();
  });

  // Close on a click outside or Escape, like a normal dropdown.
  document.addEventListener("click", (e) => {
    // composedPath() still lists the picker when the clicked element has just
    // been redrawn and detached, so a click inside never counts as outside.
    if (picker.open && !e.composedPath().includes(picker)) picker.open = false;
  });
  picker.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && picker.open) {
      e.stopPropagation();
      picker.open = false;
      picker.querySelector("summary").focus();
    }
  });
}

const filtersActive = () =>
  state.hidden.size > 0 || !allTypesOn() || state.size !== "all" || state.time !== "all" ||
  state.place !== "all" || state.query.trim() !== "";

function clearFilters() {
  state.hidden.clear();
  state.types = new Set(ALL_TYPES);
  state.size = "all";
  state.time = "all";
  state.place = "all";
  state.query = "";
  el.search.value = "";
  el.chips.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "true"));
  drawSelects();
  render();
}

function drawCards(list) {
  el.cards.innerHTML = list
    .map((p) => {
      const facts = [
        p.units ? `<b>${numberWithCommas(p.units)}</b> ${p.units === 1 ? "unit" : "units"}` : null,
        typeOf(p) !== UNKNOWN_TYPE ? escapeHtml(typeOf(p)) : null,
        p.stories ? escapeHtml(plural(p.stories, "story", "stories")) : null,
      ].filter(Boolean);
      const tag = p.middleHousing ? `<small class="tag">Middle housing</small>` : "";

      return `<li>
        <button class="card" data-id="${escapeHtml(p.id)}">
          <div class="card__stage"><i style="background:${colorOf(p.status)}"></i>${escapeHtml(p.status)}</div>
          <h3 class="card__name">${escapeHtml(p.name)}</h3>
          <div class="card__where">${escapeHtml(where(p))}</div>
          ${facts.length || tag ? `<div class="card__facts">${facts.map((f) => `<span>${f}</span>`).join("")}${tag}</div>` : ""}
        </button>
      </li>`;
    })
    .join("");

  el.cards.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", () => select(card.dataset.id, true));
    card.addEventListener("mouseenter", () => setHover(card.dataset.id, "list"));
    card.addEventListener("mouseleave", () => setHover(null, "list"));
    card.addEventListener("focus", () => setHover(card.dataset.id, "list"));
    card.addEventListener("blur", () => setHover(null, "list"));
  });
  if (state.selected) {
    const active = el.cards.querySelector(`.card[data-id="${CSS.escape(state.selected)}"]`);
    if (active) active.classList.add("is-active");
  }

  el.empty.hidden = list.length > 0;
  const homes = unitsOf(list);
  el.tally.textContent =
    (list.length === state.projects.length
      ? plural(list.length, "project", "projects")
      : `${numberWithCommas(list.length)} of ${plural(state.projects.length, "project", "projects")}`) +
    (homes ? ` · ${plural(homes, "home", "homes")}` : "");
  document.getElementById("clear-filters").hidden = !filtersActive();
}

function render() {
  const list = sorted(visible());
  state.list = list;
  drawCards(list);
  drawSpine();

  if (map && map.getSource("projects")) {
    map.getSource("projects").setData(toGeoJson(list));
    markSelected();
  }
  drawInView();
  writeUrl();
}

// ---- map <-> list highlighting --------------------------------------------

let hovered = null;

function setHover(id, from) {
  if (hovered === id) return;
  if (map && map.getSource("projects")) {
    if (hovered) map.setFeatureState({ source: "projects", id: hovered }, { hover: false });
    if (id) map.setFeatureState({ source: "projects", id }, { hover: true });
  }
  if (from === "map") {
    el.cards.querySelectorAll(".card.is-hover").forEach((c) => c.classList.remove("is-hover"));
    if (id) {
      const card = el.cards.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
      if (card) card.classList.add("is-hover");
    }
  }
  hovered = id;
}

// The open project keeps a dark ring on the map. setData() clears feature
// state, so this runs after every redraw.
function markSelected() {
  if (!map || !map.getSource("projects")) return;
  map.removeFeatureState({ source: "projects" });
  if (state.selected) map.setFeatureState({ source: "projects", id: state.selected }, { selected: true });
  hovered = null;
}

// ---- "N projects in view" ---------------------------------------------------

function drawInView() {
  const box = document.getElementById("inview");
  if (!box) return;
  if (!map || !map.getSource("projects") || !state.list) {
    box.textContent = "";
    return;
  }
  const bounds = map.getBounds();
  const inView = state.list.filter((p) => Number.isFinite(p.lng) && bounds.contains([p.lng, p.lat]));
  const homes = unitsOf(inView);
  box.textContent =
    inView.length === state.list.length
      ? `All ${plural(inView.length, "project", "projects")} in view`
      : `${plural(inView.length, "project", "projects")}${homes ? ` · ${plural(homes, "home", "homes")}` : ""} in view`;
}

// --------------------------------------------------------------------------

function toGeoJson(list) {
  return {
    type: "FeatureCollection",
    features: list.map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lng, p.lat] },
      id: p.id,
      properties: {
        id: p.id,
        name: p.name,
        color: colorOf(p.status),
        status: p.status,
        units: p.units > 0 ? p.units : 0,
      },
    })),
  };
}

// build.py leaves out fields with no value, so every field here has one.
function renderField(field) {
  const body =
    field.kind === "link"
      ? `<a href="${escapeHtml(field.value)}" target="_blank" rel="noopener">View application</a>`
      : escapeHtml(field.value);
  return `<dt>${escapeHtml(field.label)}</dt><dd>${body}</dd>`;
}

// Google Maps, Street View and the county's parcel record. Maps searches the
// first street address when there is one (a pin with a place card), and falls
// back to the map point. Street View always opens at the map point.
function placeLinks(p) {
  const hasPoint = Number.isFinite(p.lat) && Number.isFinite(p.lng);
  const firstAddress = (p.address || "").split(/\s*&\s*|\s+and\s+/)[0].trim();
  const links = [];
  if (firstAddress || hasPoint) {
    const query = firstAddress ? `${firstAddress}, Spokane, WA` : `${p.lat},${p.lng}`;
    links.push(["Google Maps", `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`]);
  }
  if (hasPoint) {
    links.push(["Street View", `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${p.lat},${p.lng}`]);
  }
  if (/^\d{5}\.\d{4}$/.test(p.parcelId || "")) {
    links.push([
      "County parcel record",
      `https://cp.spokanecounty.org/scout/propertyinformation/Summary.aspx?PID=${encodeURIComponent(p.parcelId)}`,
    ]);
  }
  if (!links.length) return "";
  return `<p class="placelinks">${links
    .map(([label, url]) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(label)}<span aria-hidden="true"> ↗</span></a>`)
    .join("")}</p>`;
}

function select(id, flyTo, fromHistory = false) {
  const project = state.projects.find((p) => p.id === id);
  if (!project) return;

  const wasOpen = !!state.selected;
  state.selected = id;
  markSelected();
  if (!fromHistory) writeUrl(!wasOpen); // a new history step when a project opens, so Back closes it

  el.cards.querySelectorAll(".card").forEach((card) => {
    card.classList.toggle("is-active", card.dataset.id === id);
  });

  const stage = indexOf(project.status);
  const color = colorOf(project.status);

  el.detailBody.innerHTML = `
    <h2>${escapeHtml(project.name)}</h2>
    <p class="detail__where">${escapeHtml(where(project))}</p>
    ${placeLinks(project)}
    <p class="detail__share"><button type="button" class="sharebtn" data-copy-project>Copy link to this project</button></p>

    <div class="track" style="--stage:${color}" role="img" aria-label="Stage: ${escapeHtml(project.status)}">
      ${STAGES.slice(0, 5).map((_, i) => `<span class="${i <= stage && stage < 5 ? "on" : ""}"></span>`).join("")}
    </div>
    <p class="track__label"><b>${escapeHtml(project.status)}</b>${project.statusUpdated ? ` since ${escapeHtml(apDate(project.statusUpdated))}` : ""}</p>

    ${
      project.imageUrl
        ? `<figure>
             <img src="${escapeHtml(project.imageUrl)}" alt="Rendering of ${escapeHtml(project.name)}" loading="lazy">
             ${project.imageCredit ? `<figcaption>Image: ${escapeHtml(project.imageCredit)}</figcaption>` : ""}
           </figure>`
        : ""
    }

    ${
      project.docUrl
        ? `<a class="doc" href="${escapeHtml(project.docUrl)}" target="_blank" rel="noopener">
             <span class="doc__icon" aria-hidden="true">PDF</span>
             <span>${escapeHtml(project.docLabel)}</span>
           </a>`
        : ""
    }

    ${project.description ? `<p>${escapeHtml(project.description)}</p>` : ""}

    <dl class="specs">
      ${project.fields.map(renderField).join("")}
    </dl>

    ${
      project.drbFile || project.permitNumbers.length || project.parcelId || project.lastVerified || councilOf(project)
        ? `<dl class="specs specs--quiet">
             ${project.drbFile ? `<dt>Design review</dt><dd>${escapeHtml(project.drbFile)}</dd>` : ""}
             ${
               project.permits && project.permits.length
                 ? `<dt>Permits</dt><dd><ul class="permits">${project.permits
                     .map(
                       (p) =>
                         `<li>${
                           p.url
                             ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">${escapeHtml(p.id)}</a>`
                             : escapeHtml(p.id)
                         }${p.type ? ` · ${escapeHtml(p.type)}` : ""}${p.status ? ` · <span class="permits__status">${escapeHtml(p.status)}</span>` : ""}</li>`
                     )
                     .join("")}</ul></dd>`
                 : project.permitNumbers.length
                 ? `<dt>Permit numbers</dt><dd>${escapeHtml(project.permitNumbers.join(", "))}</dd>`
                 : ""
             }
             ${firstFiled(project) ? `<dt>First filed</dt><dd>${escapeHtml(apDate(firstFiled(project)))}</dd>` : ""}
             ${councilOf(project) ? `<dt>Neighborhood council</dt><dd>${escapeHtml(councilOf(project))}</dd>` : ""}
             ${project.councilDistrict ? `<dt>Council district</dt><dd>District ${escapeHtml(project.councilDistrict)}</dd>` : ""}
             ${project.parcelId ? `<dt>Parcel</dt><dd>${/^\d{5}\.\d{4}$/.test(project.parcelId) ? `<a href="https://cp.spokanecounty.org/scout/propertyinformation/Summary.aspx?PID=${encodeURIComponent(project.parcelId)}" target="_blank" rel="noopener">${escapeHtml(project.parcelId)}</a>` : escapeHtml(project.parcelId)}</dd>` : ""}
             ${project.lastVerified ? `<dt>Verified</dt><dd>${escapeHtml(apDate(project.lastVerified))}</dd>` : ""}
           </dl>`
        : ""
    }

    <p class="detail__note">This page displays available information at the time of project entry.${
      project.lastVerified ? ` Last checked ${escapeHtml(apDate(project.lastVerified))}.` : ""
    }</p>

    ${
      project.sourceUrls.length
        ? `<div class="detail__sources">Sources
             <ul>${project.sourceUrls
               .map((u) => `<li><a href="${escapeHtml(u)}" rel="noopener">${escapeHtml(u.replace(/^https?:\/\//, "").slice(0, 60))}</a></li>`)
               .join("")}</ul>
           </div>`
        : ""
    }
  `;

  el.detailBody.querySelector("[data-copy-project]").addEventListener("click", (e) =>
    copyLink(e.currentTarget, `${location.origin}${location.pathname}?p=${encodeURIComponent(project.id)}`)
  );

  el.detail.hidden = false;
  el.detail.scrollTop = 0;
  document.body.dataset.detail = "open";
  document.getElementById("detail-close").focus();

  if (flyTo) flyToProject(project);
}

// Fly after the layout settles: on wide screens the detail column opens and the
// map narrows, and flying first would leave the project off-center.
function flyToProject(project) {
  if (!map || !Number.isFinite(project.lng)) return;
  const go = () =>
    map.flyTo({ center: [project.lng, project.lat], zoom: Math.max(map.getZoom(), 15), speed: 0.9 });
  requestAnimationFrame(() => requestAnimationFrame(() => {
    map.resize();
    go();
  }));
}

// ---- collapsible project list (wide screens) -------------------------------

function setPanel(open, remember = true) {
  document.body.dataset.panel = open ? "open" : "closed";
  const button = document.getElementById("panel-toggle");
  const label = open ? "Hide project list" : "Show project list";
  button.setAttribute("aria-expanded", String(open));
  button.setAttribute("aria-label", label);
  button.title = label;
  if (remember) {
    try {
      localStorage.setItem("panel", open ? "open" : "closed");
    } catch (error) {
      /* the choice just does not persist */
    }
  }
}

function wirePanelToggle() {
  let saved = "open";
  try {
    saved = localStorage.getItem("panel") || "open";
  } catch (error) {
    /* private browsing */
  }
  setPanel(saved !== "closed", false);
  document.getElementById("panel-toggle").addEventListener("click", () =>
    setPanel(document.body.dataset.panel === "closed")
  );
}

function closeDetail(fromHistory = false) {
  el.detail.hidden = true;
  document.body.dataset.detail = "closed";
  state.selected = null;
  el.cards.querySelectorAll(".card").forEach((c) => c.classList.remove("is-active"));
  markSelected();
  if (!fromHistory) writeUrl();
}

// ---- shareable links ---------------------------------------------------------
//
// The address bar always describes the current view, so copying it shares it:
//   ?p=<project id>  &q=<search>  &stage=applied,approved  &type=middle | duplex,townhomes
//   &size=20-99  &time=filed:90  &place=district:2 | hood:East Central  &sort=homes  &view=list
// Anything at its default is left out. Opening a project adds a history step
// (so Back closes it); filter changes just replace the current address.

const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

function urlFromState() {
  const params = new URLSearchParams();
  if (state.selected) params.set("p", state.selected);
  if (state.query.trim()) params.set("q", state.query.trim());
  if (state.hidden.size) {
    params.set("stage", STAGES.filter((s) => !state.hidden.has(s.name)).map((s) => slug(s.name)).join(",") || "none");
  }
  if (!allTypesOn()) {
    const on = ALL_TYPES.filter((t) => state.types.has(t));
    const isMiddle = on.length === MIDDLE_TYPES.length && MIDDLE_TYPES.every((t) => on.includes(t));
    params.set("type", isMiddle ? "middle" : on.map(slug).join(",") || "none");
  }
  if (state.size !== "all") params.set("size", state.size);
  if (state.time !== "all") params.set("time", state.time);
  if (state.place !== "all") params.set("place", state.place);
  if (state.sort !== "recent") params.set("sort", state.sort);
  if (document.body.dataset.view === "list") params.set("view", "list");
  const query = params.toString().replace(/%3A/g, ":").replace(/%2C/g, ",");
  return `${location.pathname}${query ? `?${query}` : ""}`;
}

let urlReady = false; // don't write the address until it has been read

function writeUrl(push = false) {
  if (!urlReady) return;
  const next = urlFromState();
  if (next === `${location.pathname}${location.search}`) return;
  history[push ? "pushState" : "replaceState"]({}, "", next);
}

function readUrl() {
  const params = new URLSearchParams(location.search);
  const list = (key) => (params.get(key) || "").split(",").map((v) => v.trim()).filter(Boolean);

  state.query = params.get("q") || "";
  el.search.value = state.query;

  state.hidden = new Set();
  if (params.has("stage")) {
    const on = list("stage");
    STAGES.forEach((s) => { if (!on.includes(slug(s.name))) state.hidden.add(s.name); });
  }

  state.types = new Set(ALL_TYPES);
  if (params.has("type")) {
    const on = list("type");
    state.types = new Set(on.includes("middle") ? MIDDLE_TYPES : ALL_TYPES.filter((t) => on.includes(slug(t))));
  }

  const pick = (key, allowed) => (allowed.includes(params.get(key)) ? params.get(key) : "all");
  state.size = pick("size", SIZES.map((x) => x.key));
  state.time = pick("time", TIMES.map((x) => x.key));
  const place = params.get("place") || "all";
  state.place = /^(district:\d+|hood:.*)$/.test(place) ? place : "all";
  state.sort = SORTS[params.get("sort")] ? params.get("sort") : "recent";
  document.getElementById("sort").value = state.sort;

  if (params.get("view") === "list") setView("list");

  el.chips.querySelectorAll(".chip").forEach((c) =>
    c.setAttribute("aria-pressed", String(!state.hidden.has(c.dataset.status)))
  );
  drawSelects();
  return params.get("p");
}

async function copyLink(button, url = location.href) {
  const label = button.textContent;
  try {
    await navigator.clipboard.writeText(url);
    button.textContent = "Link copied";
  } catch (error) {
    window.prompt("Copy this link:", url);
  }
  setTimeout(() => (button.textContent = label), 1800);
}

function setView(view) {
  document.querySelectorAll(".viewswitch button").forEach((t) =>
    t.setAttribute("aria-selected", String(t.dataset.view === view))
  );
  document.body.dataset.view = view;
}

// --------------------------------------------------------------------------

function savedBasemap() {
  try {
    return localStorage.getItem("basemap") === "satellite" ? "satellite" : "map";
  } catch (error) {
    return "map"; // private browsing, or storage turned off
  }
}

// The imagery sits above the vector fills and roads but below the labels, so a
// switch is one layer's visibility and street names keep drawing on top. Those
// labels are tuned for a pale background, so over imagery they get a heavier
// halo to stay readable.
function setBasemap(mode) {
  if (!map || !map.getLayer("satellite")) return;
  const on = mode === "satellite";

  map.setLayoutProperty("satellite", "visibility", on ? "visible" : "none");

  labelLayers.forEach((layer) => {
    try {
      map.setPaintProperty(layer.id, "text-halo-width", on ? 1.8 : layer.haloWidth);
      map.setPaintProperty(
        layer.id,
        "text-halo-color",
        on ? "rgba(255,255,255,0.95)" : layer.haloColor
      );
    } catch (error) {
      /* a label layer without a halo is not worth failing the switch over */
    }
  });

  document.querySelectorAll(".basemap button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.basemap === mode))
  );

  try {
    localStorage.setItem("basemap", mode);
  } catch (error) {
    /* the choice just does not persist */
  }
}

// The key's sample circles are drawn at the map's current zoom, so they are
// the same size as the circles on screen.
function drawMapKey() {
  const box = document.getElementById("mapkey");
  if (!box) return;
  const zoom = map ? map.getZoom() : 12;
  const samples = [10, 50, 200];
  const dot = (r, cls = "") =>
    `<span class="mapkey__dot ${cls}" style="width:${(2 * r).toFixed(1)}px;height:${(2 * r).toFixed(1)}px"></span>`;
  box.innerHTML = `
    <p class="mapkey__title">Circle size shows housing units</p>
    <ul class="mapkey__sizes">
      ${samples.map((n) => `<li>${dot(radiusAt(zoom, n))}<span>${n}</span></li>`).join("")}
      <li>${dot(radiusAt(zoom, 0), "mapkey__dot--unknown")}<span>Not reported</span></li>
    </ul>
    <p class="source">${escapeHtml(sourceLine())}</p>`;
}

function sourceLine() {
  return `Source: City of Spokane permit records${state.builtAt ? `. Data as of ${apDate(state.builtAt)}` : ""}.`;
}

function startMap() {
  map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/positron",
    bounds: CITY_BOUNDS,
    fitBoundsOptions: { padding: 24 },
    attributionControl: { compact: true },
  });

  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  map.on("load", () => {
    const styleLayers = map.getStyle().layers || [];
    const firstSymbol = styleLayers.find((l) => l.type === "symbol");

    labelLayers = styleLayers
      .filter((l) => l.type === "symbol" && map.getLayoutProperty(l.id, "text-field"))
      .map((l) => ({
        id: l.id,
        haloWidth: map.getPaintProperty(l.id, "text-halo-width"),
        haloColor: map.getPaintProperty(l.id, "text-halo-color"),
      }));

    map.addSource("satellite", {
      type: "raster",
      tiles: [SATELLITE_TILES],
      tileSize: 256,
      maxzoom: 19,
      attribution: SATELLITE_CREDIT,
    });

    map.addLayer(
      { id: "satellite", type: "raster", source: "satellite", layout: { visibility: "none" } },
      firstSymbol && firstSymbol.id
    );

    map.addSource("projects", { type: "geojson", data: toGeoJson(state.list || visible()), promoteId: "id" });

    // One layer. Filled circles sized by units; projects with no unit count
    // are hollow rings at the smallest size rather than a guessed size.
    // Bigger projects draw first so small ones on top stay clickable.
    const known = [">", ["get", "units"], 0];
    map.addLayer({
      id: "project-dot",
      type: "circle",
      source: "projects",
      layout: { "circle-sort-key": ["-", 0, ["get", "units"]] },
      paint: {
        "circle-radius": radiusExpression(),
        "circle-color": ["case", known, ["get", "color"], "#faf8f3"],
        "circle-opacity": ["case", known, 0.9, 1],
        "circle-stroke-color": [
          "case",
          ["any", ["boolean", ["feature-state", "selected"], false], ["boolean", ["feature-state", "hover"], false]],
          "#121212",
          known, "#ffffff",
          ["get", "color"],
        ],
        "circle-stroke-width": [
          "case",
          ["boolean", ["feature-state", "selected"], false], 3,
          ["boolean", ["feature-state", "hover"], false], 2.5,
          known, 1,
          1.8,
        ],
      },
    });
    markSelected();
    drawInView();
    map.on("moveend", drawInView);

    map.on("zoomend", drawMapKey);
    drawMapKey();

    document.querySelectorAll(".basemap button").forEach((button) => {
      button.addEventListener("click", () => setBasemap(button.dataset.basemap));
    });
    setBasemap(savedBasemap());

    map.on("click", "project-dot", (e) => select(e.features[0].properties.id, false));
    // Hovering a dot rings it, highlights its row and shows its name.
    const tip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: "tip" });
    map.on("mousemove", "project-dot", (e) => {
      const f = e.features[0];
      map.getCanvas().style.cursor = "pointer";
      setHover(f.properties.id, "map");
      tip.setLngLat(f.geometry.coordinates).setText(f.properties.name).addTo(map);
    });
    map.on("mouseleave", "project-dot", () => {
      map.getCanvas().style.cursor = "";
      setHover(null, "map");
      tip.remove();
    });

    // A shared link that opened a project: center on it now the map exists.
    if (state.selected) {
      const p = state.projects.find((x) => x.id === state.selected);
      if (p) map.jumpTo({ center: [p.lng, p.lat], zoom: 15 });
    }
  });
}

// --------------------------------------------------------------------------

function showProblem(message) {
  el.countStamp.textContent = "Something is wrong";
  el.tally.textContent = "";
  el.empty.hidden = false;
  el.empty.textContent = message;
  console.error(message);
}

async function loadData() {
  const response = await fetch("projects.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(
      `projects.json returned HTTP ${response.status}. The file is probably missing from the deployment.`
    );
  }
  return response.json();
}

async function start() {
  el.search.addEventListener("input", (e) => {
    state.query = e.target.value;
    render();
  });

  document.getElementById("detail-close").addEventListener("click", () => closeDetail());
  document.getElementById("sort").addEventListener("change", (e) => {
    state.sort = e.target.value;
    render();
  });
  document.getElementById("share-view").addEventListener("click", (e) => copyLink(e.currentTarget));
  window.addEventListener("popstate", () => {
    const id = readUrl();
    if (id) select(id, true, true);
    else if (!el.detail.hidden) closeDetail(true);
    render();
  });

  wireTypePicker();
  document.getElementById("size-filter").addEventListener("change", (e) => {
    state.size = e.target.value;
    render();
  });
  document.getElementById("time-filter").addEventListener("change", (e) => {
    state.time = e.target.value;
    render();
  });
  document.getElementById("place-filter").addEventListener("change", (e) => {
    state.place = e.target.value;
    render();
  });
  document.getElementById("clear-filters").addEventListener("click", clearFilters);
  wirePanelToggle();

  document.querySelectorAll("#measure button").forEach((button) => {
    button.addEventListener("click", () => {
      state.measure = button.dataset.measure;
      drawSpine();
    });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.detail.hidden) closeDetail();
  });

  document.querySelectorAll(".viewswitch button").forEach((tab) => {
    tab.addEventListener("click", () => {
      setView(tab.dataset.view);
      writeUrl();
    });
  });
  document.body.dataset.view = "map";
  document.body.dataset.detail = "closed";

  // MapLibre measures its container once, when the map is constructed, and does
  // not follow it afterwards. Every later change to the map box has to say so:
  // the cards rendering below, the detail column opening on wide screens, the
  // view switch on narrow ones, window resizes and rotation. One observer on the
  // box covers all of them.
  const mapBox = document.querySelector(".mapwrap");
  if (mapBox && window.ResizeObserver) {
    let pending;
    new ResizeObserver(() => {
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(() => map && map.resize());
    }).observe(mapBox);
  } else {
    let resizeTimer;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => map && map.resize(), 120);
    });
  }

  // Data and map are loaded separately, so a failure in one does not look like
  // a failure in the other.
  let payload = null;
  try {
    payload = await loadData();
    if (Array.isArray(payload.stages) && payload.stages.length) STAGES = payload.stages;
    state.projects = payload.projects || [];
  } catch (error) {
    showProblem(`Could not load the project data. ${error.message}`);
  }

  drawChips();
  drawSelects();

  try {
    if (typeof maplibregl === "undefined") {
      throw new Error("The map library did not load. Check your connection or an ad blocker.");
    }
    startMap();
  } catch (error) {
    document.getElementById("map").innerHTML =
      `<p class="maperror">${error.message}</p>`;
    console.error(error);
  }

  if (payload) {
    state.builtAt = payload.builtAt ? new Date(payload.builtAt) : null;
    drawLede();
    drawNote();
    drawMapKey();
    const openId = readUrl();
    urlReady = true;
    render();
    if (openId && state.projects.some((p) => p.id === openId)) select(openId, false, true);
    else if (openId) writeUrl(); // drop a link to a project that no longer exists
  }
}

start();
