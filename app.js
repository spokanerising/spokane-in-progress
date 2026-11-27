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
const ALL_TYPES = [...MIDDLE_TYPES, ...OTHER_TYPES, UNKNOWN_TYPE];

const typeOf = (p) => p.buildingType || UNKNOWN_TYPE;
const councilOf = (p) => p.neighborhoodCouncil ?? "";
const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// Project size, by every home in the project.
const SIZES = [
  { key: "2-4", label: "2–4 homes", test: (u) => u >= 2 && u <= 4 },
  { key: "5-19", label: "5–19 homes", test: (u) => u >= 5 && u <= 19 },
  { key: "20-99", label: "20–99 homes", test: (u) => u >= 20 && u <= 99 },
  { key: "100", label: "100 or more homes", test: (u) => u >= 100 },
  { key: "unknown", label: "Size not reported", test: (u) => !(u > 0) },
];

// ---- dates ----------------------------------------------------------------

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
  return Math.max(0, Math.floor((ref - t) / DAY));
}

// Age buckets that don't overlap, so ticking two of them never double-counts.
const ageOptions = (dateOf, buckets) =>
  buckets.map(([key, label, lo, hi]) => ({
    key,
    label,
    test: key === "unknown"
      ? (p) => ageInDays(dateOf(p)) === null
      : (p) => { const a = ageInDays(dateOf(p)); return a !== null && a >= lo && a <= hi; },
  }));

// ---- the filters -----------------------------------------------------------
//
// Every filter is a checklist. Each option has a key (used in the address
// bar) and a test. All options ticked means the filter is off; within one
// filter, options combine with OR; different filters combine with AND.
// Options that depend on the data (neighborhoods, zones) are filled in by
// setUpFilters() once projects.json has loaded.

const FILTERS = {
  stage: {
    param: "stage",
    options: () => STAGES.map((s) => ({ key: slug(s.name), label: s.name, test: (p) => p.status === s.name })),
  },
  type: {
    param: "type",
    noun: "types",
    groups: [
      { key: "middle", label: "Middle housing" },
      { key: "other", label: "Other housing" },
    ],
    options: () =>
      ALL_TYPES.map((t) => ({
        key: slug(t),
        label: t === UNKNOWN_TYPE ? "Type not yet known" : t,
        short: t === UNKNOWN_TYPE ? "Type unknown" : t,
        group: MIDDLE_TYPES.includes(t) ? "middle" : OTHER_TYPES.includes(t) ? "other" : null,
        test: (p) => typeOf(p) === t,
      })),
    // ?type=middle is how the site has always written "just middle housing".
    legacy: (values) => (values.includes("middle") ? MIDDLE_TYPES.map(slug) : null),
  },
  size: {
    param: "size",
    noun: "sizes",
    options: () => SIZES.map((s) => ({ key: s.key, label: s.label, test: (p) => s.test(p.units) })),
  },
  filed: {
    param: "filed",
    noun: "date ranges",
    short: "Filed",
    options: () =>
      ageOptions(firstFiled, [
        ["30", "In the past 30 days", 0, 30],
        ["90", "1 to 3 months ago", 31, 91],
        ["365", "3 to 12 months ago", 92, 365],
        ["730", "1 to 2 years ago", 366, 730],
        ["old", "More than 2 years ago", 731, Infinity],
        ["unknown", "Filing date not known"],
      ]),
  },
  since: {
    param: "since",
    noun: "date ranges",
    short: "New stage",
    options: () =>
      ageOptions((p) => p.statusUpdated, [
        ["30", "In the past 30 days", 0, 30],
        ["90", "1 to 3 months ago", 31, 91],
        ["365", "3 to 12 months ago", 92, 365],
        ["old", "More than a year ago", 366, Infinity],
        ["unknown", "Date not known"],
      ]),
  },
  district: {
    param: "district",
    noun: "districts",
    options: () => {
      const ds = [...new Set(state.projects.map((p) => p.councilDistrict).filter((d) => d != null))].sort();
      const opts = ds.map((d) => ({ key: String(d), label: `District ${d}`, test: (p) => p.councilDistrict === d }));
      if (state.projects.some((p) => p.councilDistrict == null)) {
        opts.push({ key: "outside", label: "Outside the city", test: (p) => p.councilDistrict == null });
      }
      return opts;
    },
  },
  hood: {
    param: "hood",
    noun: "neighborhoods",
    options: () => {
      const names = [...new Set(state.projects.map(councilOf).filter(Boolean))].sort((a, b) => a.localeCompare(b));
      const opts = names.map((n) => ({ key: slug(n), label: n, test: (p) => councilOf(p) === n }));
      if (state.projects.some((p) => !councilOf(p))) {
        opts.push({ key: "outside", label: "No neighborhood council", test: (p) => !councilOf(p) });
      }
      return opts;
    },
  },
  transit: {
    param: "transit",
    noun: "distances",
    needs: "transitMiles",
    options: () => {
      const mi = (p) => (Number.isFinite(p.transitMiles) ? p.transitMiles : null);
      return [
        { key: "quarter", label: "Within ¼ mile", test: (p) => mi(p) !== null && mi(p) <= 0.25 },
        { key: "half", label: "¼ to ½ mile", test: (p) => mi(p) !== null && mi(p) > 0.25 && mi(p) <= 0.5 },
        { key: "far", label: "More than ½ mile", test: (p) => mi(p) !== null && mi(p) > 0.5 },
        { key: "unknown", label: "Not known", test: (p) => mi(p) === null },
      ];
    },
  },
  zone: {
    param: "zone",
    noun: "zones",
    needs: "zone",
    groups: () => ZONE_GROUP_ORDER.filter((g) => state.projects.some((p) => p.zone && (p.zoneGroup || "Other") === g))
      .map((g) => ({ key: slug(g), label: g })),
    options: () => {
      const bases = new Map();
      state.projects.forEach((p) => {
        if (p.zone) bases.set(p.zoneBase || p.zone, { group: p.zoneGroup || "Other", name: p.zoneName || "" });
      });
      const order = (b) => ZONE_GROUP_ORDER.indexOf(bases.get(b).group);
      const opts = [...bases.keys()]
        .sort((a, b) => order(a) - order(b) || a.localeCompare(b, "en", { numeric: true }))
        .map((b) => ({
          key: slug(b),
          // "RMF · Residential Multifamily", but just "DTC" under a Downtown heading.
          label: bases.get(b).name && bases.get(b).name !== bases.get(b).group ? `${b} · ${bases.get(b).name}` : b,
          short: b,
          group: slug(bases.get(b).group),
          test: (p) => (p.zoneBase || p.zone) === b,
        }));
      if (state.projects.some((p) => !p.zone)) {
        opts.push({ key: "unknown", label: "Zoning not known", short: "Zoning unknown", test: (p) => !p.zone });
      }
      return opts;
    },
  },
  density: {
    param: "density",
    noun: "ranges",
    needs: "homesPerAcre",
    options: () => {
      const d = (p) => (Number.isFinite(p.homesPerAcre) ? p.homesPerAcre : null);
      const band = (lo, hi) => (p) => d(p) !== null && d(p) >= lo && d(p) < hi;
      return [
        { key: "under20", label: "Under 20 homes per acre", short: "Under 20/acre", test: band(0, 20) },
        { key: "20", label: "20 to 49", short: "20–49/acre", test: band(20, 50) },
        { key: "50", label: "50 to 99", short: "50–99/acre", test: band(50, 100) },
        { key: "100", label: "100 or more", short: "100+/acre", test: band(100, Infinity) },
        { key: "unknown", label: "Not known", short: "Density unknown", test: (p) => d(p) === null },
      ];
    },
  },
};

const ZONE_GROUP_ORDER = ["Residential", "Centers & Corridors", "Commercial & mixed use", "Downtown", "Industrial", "Other"];

// The dropdowns, in the order they appear. A dropdown can hold more than one
// filter (Timeline holds "first filed" and "reached its stage"; Where holds
// districts and neighborhoods), and those combine with AND.
const PICKERS = [
  { id: "type", label: "Building type", parts: [{ f: "type" }], all: "All building types",
    quick: [["All types", () => setAll("type", true)], ["Only middle housing", () => { state.sel.type = new Set(MIDDLE_TYPES.map(slug)); }]] },
  { id: "size", label: "Project size", parts: [{ f: "size" }], all: "All sizes" },
  { id: "time", label: "Timeline", parts: [{ f: "filed", head: "First filed with the city" }, { f: "since", head: "Reached its current stage" }], all: "Any time" },
  { id: "place", label: "Where", parts: [{ f: "district", head: "City Council district" }, { f: "hood", head: "Neighborhood council", search: "Find a neighborhood" }], all: "All of Spokane" },
  { id: "near", label: "Near", custom: true, all: "Anywhere" },
  { id: "transit", label: "Frequent transit", parts: [{ f: "transit", head: "Walk to a frequent bus stop", note: "Straight-line distance to the nearest stop with a bus every 15 minutes or better on weekdays." }], all: "Any distance" },
  { id: "zone", label: "Zoning", parts: [{ f: "zone" }], all: "All zones" },
  { id: "density", label: "Homes per acre", parts: [{ f: "density" }], all: "Any density" },
];

const state = {
  projects: [],
  sel: {},          // filter key -> Set of option keys that are ticked
  query: "",
  near: null,       // { lat, lng, miles, label } or null
  inViewOnly: false,
  selected: null,
  builtAt: null,
  measure: "homes", // what the stage bar is sized by: "homes" or "projects"
  sort: "recent",   // list order; see SORTS
};

// Fills in each filter's options from the data, ticks them all, and drops
// filters the data can't support yet (zoning before the first lookup, say).
function setUpFilters() {
  Object.entries(FILTERS).forEach(([key, f]) => {
    f.key = key;
    const available = !f.needs || state.projects.some((p) => p[f.needs] !== undefined && p[f.needs] !== null && p[f.needs] !== "");
    f.opts = available ? f.options() : [];
    f.groupList = typeof f.groups === "function" ? f.groups() : f.groups || [];
    state.sel[key] = new Set(f.opts.map((o) => o.key));
  });
}

const filterOn = (key) => FILTERS[key].opts.length > 0 && state.sel[key].size < FILTERS[key].opts.length;
const setAll = (key, on) => { state.sel[key] = new Set(on ? FILTERS[key].opts.map((o) => o.key) : []); };
const pickerOn = (pk) => (pk.custom ? !!state.near : pk.parts.some((part) => filterOn(part.f)));

function passes(p, key) {
  if (!filterOn(key)) return true;
  const sel = state.sel[key];
  return FILTERS[key].opts.some((o) => sel.has(o.key) && o.test(p));
}

// ---- the other narrowing tools: search, distance from a point, map view ----

const MILES_PER_DEG_LAT = 69.055;
function milesBetween(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad, dLng = (b.lng - a.lng) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * 3958.7613 * Math.asin(Math.sqrt(h));
}

const RADII = [[0.25, "¼ mile"], [0.5, "½ mile"], [1, "1 mile"], [2, "2 miles"]];
const radiusLabel = (mi) => (RADII.find((r) => r[0] === mi) || [mi, `${mi} miles`])[1];

const nearOk = (p) =>
  !state.near || (Number.isFinite(p.lat) && milesBetween(state.near, p) <= state.near.miles);

function inMapView(p) {
  if (!state.inViewOnly || !map || !map.getSource("projects")) return true;
  return Number.isFinite(p.lng) && map.getBounds().contains([p.lng, p.lat]);
}

// Does a project pass everything except `skip` (a filter key, or "q",
// "near", "inview")? Leaving one filter out is how each option's count is
// worked out: the number you'd get if you ticked it, given everything else.
function matches(p, skip = null) {
  for (const key in FILTERS) {
    if (key !== skip && !passes(p, key)) return false;
  }
  if (skip !== "near" && !nearOk(p)) return false;
  if (skip !== "inview" && !inMapView(p)) return false;
  const q = skip === "q" ? "" : state.query.trim().toLowerCase();
  return !q || searchText(p).includes(q);
}

const optionCount = (key, option) =>
  state.projects.filter((p) => matches(p, key) && option.test(p)).length;

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

// extra: pixels added at every zoom (the invisible tap ring uses +8). Zoom has
// to stay the outermost interpolate in a MapLibre expression, so the extra is
// added inside each stop rather than around the whole thing.
function radiusExpression(extra = 0) {
  const units = ["get", "units"];
  const at = (s) => [
    "+",
    extra,
    ["case", [">", units, 0], ["max", s[2], ["*", s[1], ["sqrt", units]]], s[2] + UNKNOWN_BOOST],
  ];
  return ["interpolate", ["linear"], ["zoom"], ...SIZE_STOPS.flatMap((s) => [s[0], at(s)])];
}

// Developer, architect, cost and the rest arrive inside fields[], not as
// top-level keys, so search reads the field values instead of naming keys that
// do not exist. Links are skipped so a query cannot match a bare URL.
const searchText = (p) =>
  [p.name, p.address, p.neighborhood, p.buildingType, p.middleHousing ? "middle housing" : "", p.zone]
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
  density: (a, b) => (b.homesPerAcre > 0 ? b.homesPerAcre : -1) - (a.homesPerAcre > 0 ? a.homesPerAcre : -1),
  name: (a, b) => a.name.localeCompare(b.name, "en", { numeric: true }),
};

const sorted = (list) => [...list].sort((a, b) => SORTS[state.sort](a, b) || a.name.localeCompare(b.name));

// Everything that passes the filters, before "only what's in map view": the
// map always draws these, so panning can reveal more.
const forMap = () => state.projects.filter((p) => matches(p, "inview"));
const visible = () => state.projects.filter((p) => matches(p));

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
  box.classList.remove("is-loading");
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

// ---- stage chips -------------------------------------------------------------
//
// Each chip toggles one stage. "Only" (shown on hover, or by double-clicking
// or long-pressing a chip) shows just that stage; using it again brings every
// stage back.

function drawChips() {
  el.chips.innerHTML = FILTERS.stage.opts
    .map((o, i) => {
      const s = STAGES[i];
      return `<span class="chipwrap">
          <button class="chip" type="button" aria-pressed="true" data-key="${escapeHtml(o.key)}" style="--stage:${s.color}">
            <i></i>${escapeHtml(s.name)}<span class="chip__n"></span>
          </button>
          <button type="button" class="only only--chip" data-only="${escapeHtml(o.key)}" aria-label="Show only ${escapeHtml(s.name)}">only</button>
        </span>`;
    })
    .join("");
}

function syncChips() {
  el.chips.querySelectorAll(".chip").forEach((chip) => {
    const o = FILTERS.stage.opts.find((x) => x.key === chip.dataset.key);
    if (!o) return;
    const n = optionCount("stage", o);
    chip.setAttribute("aria-pressed", String(state.sel.stage.has(o.key)));
    chip.querySelector(".chip__n").textContent = numberWithCommas(n);
    chip.classList.toggle("is-zero", n === 0);
  });
}

// Show only one option; if that is already the case, show them all again.
function only(key, optionKey) {
  const sel = state.sel[key];
  state.sel[key] = sel.size === 1 && sel.has(optionKey)
    ? new Set(FILTERS[key].opts.map((o) => o.key))
    : new Set([optionKey]);
}

function wireChips() {
  let pressTimer = null;
  let longPressed = false;
  el.chips.addEventListener("click", (e) => {
    const onlyBtn = e.target.closest("[data-only]");
    const chip = e.target.closest(".chip");
    if (onlyBtn) {
      only("stage", onlyBtn.dataset.only);
    } else if (chip) {
      if (longPressed) { longPressed = false; return; }
      const sel = state.sel.stage;
      sel.has(chip.dataset.key) ? sel.delete(chip.dataset.key) : sel.add(chip.dataset.key);
    } else return;
    render();
  });
  el.chips.addEventListener("dblclick", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    state.sel.stage = new Set([chip.dataset.key]);
    render();
  });
  // Phones: press and hold a chip for "only".
  el.chips.addEventListener("pointerdown", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip || e.pointerType === "mouse") return;
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {
      longPressed = true;
      only("stage", chip.dataset.key);
      render();
      if (navigator.vibrate) navigator.vibrate(10);
    }, 550);
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((t) =>
    el.chips.addEventListener(t, () => clearTimeout(pressTimer))
  );
  el.chips.addEventListener("contextmenu", (e) => { if (e.target.closest(".chip")) e.preventDefault(); });
}

// ---- dropdown checklists -----------------------------------------------------

const pickerAvailable = (pk) => pk.custom || pk.parts.some((part) => FILTERS[part.f].opts.length > 0);
const pickerEl = (id) => document.querySelector(`.picker[data-picker="${id}"]`);

function drawPickers() {
  const box = document.getElementById("pickers");
  box.innerHTML = PICKERS.filter(pickerAvailable)
    .map(
      (pk) => `<div class="select">
          <span class="select__label" id="${pk.id}-label">${escapeHtml(pk.label)}</span>
          <details class="picker" data-picker="${pk.id}">
            <summary class="picker__button" aria-describedby="${pk.id}-label"><span class="picker__summary">${escapeHtml(pk.all)}</span></summary>
            <div class="picker__panel" role="group" aria-labelledby="${pk.id}-label"></div>
          </details>
        </div>`
    )
    .join("");
}

function optionRow(key, o) {
  return `<label class="picker__item" data-text="${escapeHtml(o.label.toLowerCase())}">
      <input type="checkbox" data-f="${key}" data-o="${escapeHtml(o.key)}">
      <span class="picker__text">${escapeHtml(o.label)}</span>
      <button type="button" class="only" data-f="${key}" data-only="${escapeHtml(o.key)}" aria-label="Only ${escapeHtml(o.label)}">only</button>
      <span class="picker__n" data-n="${key}:${escapeHtml(o.key)}"></span>
    </label>`;
}

function partHtml(pk, part) {
  const F = FILTERS[part.f];
  if (!F.opts.length) return "";
  let body;
  if (F.groupList.length) {
    const grouped = F.groupList.map((g) => {
      const items = F.opts.filter((o) => o.group === g.key);
      if (!items.length) return "";
      return `<div class="picker__group">
          <label class="picker__item picker__item--group">
            <input type="checkbox" data-f="${part.f}" data-group="${escapeHtml(g.key)}">
            <span class="picker__text">${escapeHtml(g.label)}</span>
            <span class="picker__n" data-n="${part.f}:group:${escapeHtml(g.key)}"></span>
          </label>
          ${items.map((o) => optionRow(part.f, o)).join("")}
        </div>`;
    });
    const loose = F.opts.filter((o) => !o.group);
    if (loose.length) grouped.push(`<div class="picker__group">${loose.map((o) => optionRow(part.f, o)).join("")}</div>`);
    body = grouped.join("");
  } else {
    body = `<div class="picker__group">${F.opts.map((o) => optionRow(part.f, o)).join("")}</div>`;
  }
  return `<div class="picker__part" data-part="${part.f}">
      ${part.head && pk.parts.length > 1
        ? `<label class="picker__item picker__item--head"><input type="checkbox" data-f="${part.f}" data-all="1"><span class="picker__text">${escapeHtml(part.head)}</span></label>`
        : part.head ? `<p class="picker__head">${escapeHtml(part.head)}</p>` : ""}
      ${part.note ? `<p class="picker__note">${escapeHtml(part.note)}</p>` : ""}
      ${part.search ? `<input type="search" class="picker__search" data-search="${part.f}" placeholder="${escapeHtml(part.search)}" aria-label="${escapeHtml(part.search)}" autocomplete="off">` : ""}
      ${body}
      <p class="picker__nomatch" hidden>No neighborhood by that name.</p>
    </div>`;
}

function drawPanel(pk) {
  const details = pickerEl(pk.id);
  if (!details) return;
  const panel = details.querySelector(".picker__panel");
  if (pk.custom) {
    panel.innerHTML = nearPanelHtml();
    syncNearPanel();
    return;
  }
  const quick = [["All", () => pk.parts.forEach((part) => setAll(part.f, true))],
                 ["None", () => pk.parts.forEach((part) => setAll(part.f, false))], ...(pk.quick || [])];
  panel.innerHTML = `
    <div class="picker__quick">${quick.map(([label], i) => `<button type="button" data-quick="${i}">${escapeHtml(label)}</button>`).join("")}</div>
    ${pk.parts.map((part) => partHtml(pk, part)).join("")}`;
  panel._quick = quick;
  syncPanel(pk);
}

// Ticks, half-ticks and counts, updated in place so focus and scroll stay put.
function syncPanel(pk) {
  const details = pickerEl(pk.id);
  if (!details || !details.open || pk.custom) return;
  const panel = details.querySelector(".picker__panel");
  pk.parts.forEach((part) => {
    const F = FILTERS[part.f];
    const sel = state.sel[part.f];
    const others = state.projects.filter((p) => matches(p, part.f));
    const count = (test) => others.filter(test).length;
    F.opts.forEach((o) => {
      const input = panel.querySelector(`input[data-f="${part.f}"][data-o="${CSS.escape(o.key)}"]`);
      if (input) input.checked = sel.has(o.key);
      const n = count(o.test);
      const cell = panel.querySelector(`[data-n="${part.f}:${CSS.escape(o.key)}"]`);
      if (cell) {
        cell.textContent = numberWithCommas(n);
        cell.closest(".picker__item").classList.toggle("is-zero", n === 0);
      }
    });
    F.groupList.forEach((g) => {
      const items = F.opts.filter((o) => o.group === g.key);
      const box = panel.querySelector(`input[data-f="${part.f}"][data-group="${CSS.escape(g.key)}"]`);
      if (!box) return;
      const on = items.filter((o) => sel.has(o.key)).length;
      box.checked = on === items.length;
      box.indeterminate = on > 0 && on < items.length;
      const cell = panel.querySelector(`[data-n="${part.f}:group:${CSS.escape(g.key)}"]`);
      if (cell) cell.textContent = numberWithCommas(count((p) => items.some((o) => o.test(p))));
    });
    const head = panel.querySelector(`input[data-f="${part.f}"][data-all]`);
    if (head) {
      head.checked = sel.size === F.opts.length;
      head.indeterminate = sel.size > 0 && sel.size < F.opts.length;
    }
  });
}

function partSummary(key) {
  const F = FILTERS[key];
  if (!filterOn(key)) return "";
  const on = F.opts.filter((o) => state.sel[key].has(o.key));
  if (!on.length) return "None";
  const same = (keys) => keys.length === on.length && keys.every((k) => state.sel[key].has(k));
  if (key === "type" && same(MIDDLE_TYPES.map(slug))) return "Middle housing";
  if (key === "type" && same(OTHER_TYPES.map(slug))) return "Other housing";
  const group = F.groupList.find((g) => same(F.opts.filter((o) => o.group === g.key).map((o) => o.key)));
  if (group) return group.label;
  if (on.length <= 2) return on.map((o) => o.short || o.label).join(", ");
  return `${on.length} ${F.noun || "selected"}`;
}

function pickerSummary(pk) {
  if (pk.custom) return state.near ? `Within ${radiusLabel(state.near.miles)} of ${state.near.label}` : pk.all;
  const parts = pk.parts.filter((part) => filterOn(part.f));
  if (!parts.length) return pk.all;
  return parts
    .map((part) => {
      const s = partSummary(part.f);
      return pk.parts.length > 1 && FILTERS[part.f].short ? `${FILTERS[part.f].short}: ${s.toLowerCase()}` : s;
    })
    .join(" · ");
}

function syncPickers() {
  PICKERS.filter(pickerAvailable).forEach((pk) => {
    const details = pickerEl(pk.id);
    if (!details) return;
    details.querySelector(".picker__summary").textContent = pickerSummary(pk);
    details.classList.toggle("is-on", pickerOn(pk));
    syncPanel(pk);
  });
}

// Keeps a panel inside the filter column: a dropdown on the right-hand side
// opens leftwards.
function placePanel(details) {
  const panel = details.querySelector(".picker__panel");
  details.classList.remove("picker--right");
  const bound = document.getElementById("panel").getBoundingClientRect();
  const r = panel.getBoundingClientRect();
  if (r.right > Math.min(bound.right, window.innerWidth) - 4) details.classList.add("picker--right");
}

function wirePickers() {
  const box = document.getElementById("pickers");

  box.addEventListener("toggle", (e) => {
    const details = e.target;
    if (!details.classList || !details.classList.contains("picker")) return;
    if (details.open) {
      box.querySelectorAll(".picker[open]").forEach((d) => { if (d !== details) d.open = false; });
      const pk = PICKERS.find((x) => x.id === details.dataset.picker);
      drawPanel(pk);
      placePanel(details);
    }
  }, true);

  box.addEventListener("change", (e) => {
    const input = e.target;
    const key = input.dataset.f;
    if (!key || input.type !== "checkbox") return;
    const sel = state.sel[key];
    if (input.dataset.o !== undefined) {
      input.checked ? sel.add(input.dataset.o) : sel.delete(input.dataset.o);
    } else if (input.dataset.group !== undefined) {
      FILTERS[key].opts.filter((o) => o.group === input.dataset.group)
        .forEach((o) => (input.checked ? sel.add(o.key) : sel.delete(o.key)));
    } else if (input.dataset.all) {
      setAll(key, input.checked);
    }
    afterFilterChange(key);
  });

  box.addEventListener("click", (e) => {
    const onlyBtn = e.target.closest("button[data-only]");
    if (onlyBtn) {
      e.preventDefault();
      only(onlyBtn.dataset.f, onlyBtn.dataset.only);
      afterFilterChange(onlyBtn.dataset.f);
      return;
    }
    const quick = e.target.closest("button[data-quick]");
    if (quick) {
      const panel = quick.closest(".picker__panel");
      panel._quick[+quick.dataset.quick][1]();
      const pk = PICKERS.find((x) => x.id === quick.closest(".picker").dataset.picker);
      afterFilterChange(pk.parts[pk.parts.length - 1].f);
    }
  });

  // Type-to-find in long lists (neighborhoods).
  box.addEventListener("input", (e) => {
    const input = e.target.closest("[data-search]");
    if (!input) return;
    const q = input.value.trim().toLowerCase();
    const part = input.closest(".picker__part");
    let shown = 0;
    part.querySelectorAll(".picker__item:not(.picker__item--head)").forEach((item) => {
      const hit = !q || (item.dataset.text || "").includes(q);
      item.hidden = !hit;
      if (hit) shown++;
    });
    part.querySelector(".picker__nomatch").hidden = shown > 0;
  });

  // Close on a click outside or Escape, like a normal dropdown.
  document.addEventListener("click", (e) => {
    // composedPath() still lists the picker when the clicked element has just
    // been redrawn and detached, so a click inside never counts as outside.
    const path = e.composedPath();
    box.querySelectorAll(".picker[open]").forEach((d) => { if (!path.includes(d)) d.open = false; });
  });
  box.addEventListener("keydown", (e) => {
    const details = e.target.closest(".picker[open]");
    if (e.key === "Escape" && details) {
      e.stopPropagation();
      details.open = false;
      details.querySelector("summary").focus();
    }
  });
}

function afterFilterChange(key) {
  render();
  if (key === "district" || key === "hood") drawOutlines(true);
}

// ---- "Near": a distance from an address, your location or a spot on the map --

let nearMiles = 0.5;   // remembered between uses, even before a point is set

function nearPanelHtml() {
  return `<form class="near" data-near-form novalidate>
      <label class="picker__head" for="near-address">Address or intersection</label>
      <div class="near__row">
        <input type="search" id="near-address" class="picker__search" placeholder="e.g. 10 N Post St" autocomplete="off" enterkeyhint="search">
        <button type="submit" class="near__find">Find</button>
      </div>
      <div class="near__alt">
        <button type="button" data-near="me">Use my location</button>
        <button type="button" data-near="pick">Pick a spot on the map</button>
      </div>
      <fieldset class="near__radius">
        <legend class="picker__head">Within</legend>
        <div class="seg" role="radiogroup">
          ${RADII.map(([mi, label]) => `<label><input type="radio" name="near-miles" value="${mi}"><span>${label}</span></label>`).join("")}
        </div>
      </fieldset>
      <p class="near__status" aria-live="polite"></p>
      <button type="button" class="near__clear" data-near="clear">Remove this filter</button>
    </form>`;
}

function syncNearPanel(message) {
  const form = document.querySelector("[data-near-form]");
  if (!form) return;
  const miles = state.near ? state.near.miles : nearMiles;
  form.querySelectorAll('input[name="near-miles"]').forEach((r) => (r.checked = +r.value === miles));
  form.querySelector(".near__clear").hidden = !state.near;
  const status = form.querySelector(".near__status");
  if (message !== undefined) status.textContent = message;
  else status.textContent = state.near
    ? `Showing projects within ${radiusLabel(state.near.miles)} of ${state.near.label}.`
    : "";
}

function setNear(point, fit = true) {
  state.near = point ? { ...point, miles: point.miles || nearMiles } : null;
  render();
  drawNear(fit);
  syncNearPanel();
}

const titleCase = (s) =>
  String(s).toLowerCase().replace(/\b([a-z])/g, (c) => c.toUpperCase())
    .replace(/\b(Ne|Nw|Se|Sw)\b/g, (c) => c.toUpperCase()).replace(/, Spokane.*$/i, "");

async function fetchJson(url, ms = 8000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// The city's own address locators first (they know every Spokane address),
// then OpenStreetMap's search, held to the Spokane area, for intersections
// and landmarks.
async function geocode(text) {
  const q = encodeURIComponent(text);
  const city = (name) =>
    `https://services.spokanegis.org/arcgis/rest/services/Locator/${name}/GeocodeServer/findAddressCandidates?SingleLine=${q}&outSR=4326&maxLocations=1&f=json`;
  for (const url of [city("AddressPoint"), city("CompositeAddress")]) {
    try {
      const c = ((await fetchJson(url)).candidates || [])[0];
      if (c && c.score >= 85 && c.location) return { lat: c.location.y, lng: c.location.x, label: titleCase(c.address) };
    } catch (error) {
      /* try the next one */
    }
  }
  try {
    const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=us&bounded=1&viewbox=-117.62,47.80,-117.24,47.55&q=${encodeURIComponent(`${text}, Spokane, WA`)}`;
    const hit = (await fetchJson(url))[0];
    if (hit) return { lat: +hit.lat, lng: +hit.lon, label: text.trim() };
  } catch (error) {
    /* nothing found anywhere */
  }
  return null;
}

let picking = false;
let pickedAt = 0;   // when a spot was last picked for "Near"

function setPicking(on) {
  picking = on;
  document.body.dataset.picking = on ? "on" : "off";
  const hint = document.getElementById("pickhint");
  if (hint) hint.hidden = !on;
  if (map) map.getCanvas().style.cursor = on ? "crosshair" : "";
}

function wireNear() {
  const box = document.getElementById("pickers");
  box.addEventListener("submit", async (e) => {
    const form = e.target.closest("[data-near-form]");
    if (!form) return;
    e.preventDefault();
    const text = form.querySelector("#near-address").value.trim();
    if (!text) return;
    syncNearPanel("Looking that up…");
    const hit = await geocode(text);
    if (hit) setNear(hit);
    else syncNearPanel("Couldn’t find that address. Try adding N, S, E or W, or pick a spot on the map.");
  });
  box.addEventListener("change", (e) => {
    if (e.target.name !== "near-miles") return;
    nearMiles = +e.target.value;
    if (state.near) setNear({ ...state.near, miles: nearMiles });
  });
  box.addEventListener("click", (e) => {
    const b = e.target.closest("[data-near]");
    if (!b) return;
    const what = b.dataset.near;
    if (what === "clear") setNear(null, false);
    if (what === "me") {
      if (!navigator.geolocation) return syncNearPanel("This browser can’t share your location.");
      syncNearPanel("Finding you…");
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const point = { lat: pos.coords.latitude, lng: pos.coords.longitude, label: "your location" };
          setNear(point);
          if (milesBetween(point, { lat: 47.6588, lng: -117.426 }) > 25) {
            syncNearPanel("You seem to be outside Spokane, so nothing may be close by.");
          }
        },
        () => syncNearPanel("Couldn’t get your location. Check that location access is allowed for this site."),
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
      );
    }
    if (what === "pick") {
      b.closest(".picker").open = false;
      setView("map");
      writeUrl();
      setPicking(true);
    }
  });
  document.getElementById("pickhint-cancel").addEventListener("click", () => setPicking(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && picking) setPicking(false); });
}

// ---- active-filter pills -------------------------------------------------------
//
// One removable pill per filter that's on, so you can see what's narrowing
// the list without opening every dropdown (on phones they're behind "More
// filters"). The × puts that one filter back to everything.

function stageSummary() {
  const on = FILTERS.stage.opts.filter((o) => state.sel.stage.has(o.key)).map((o) => o.label);
  const off = FILTERS.stage.opts.filter((o) => !state.sel.stage.has(o.key)).map((o) => o.label);
  if (!on.length) return "None";
  return on.length <= 3 ? on.join(", ") : `All but ${off.join(", ")}`;
}

function drawPills() {
  const box = document.getElementById("pills");
  const pills = [];
  if (state.query.trim()) pills.push(["q", "Search", `“${state.query.trim()}”`]);
  if (filterOn("stage")) pills.push(["stage", "Stage", stageSummary()]);
  PICKERS.filter((pk) => pickerAvailable(pk) && pickerOn(pk)).forEach((pk) =>
    pk.custom
      ? pills.push([`picker:${pk.id}`, "Within", `${radiusLabel(state.near.miles)} of ${state.near.label}`])
      : pills.push([`picker:${pk.id}`, pk.label, pickerSummary(pk)])
  );
  if (state.inViewOnly) pills.push(["inview", "Map", "Only what’s in view"]);
  box.innerHTML = pills
    .map(([key, label, value]) =>
      `<li><button type="button" class="pill" data-pill="${escapeHtml(key)}" aria-label="Remove filter: ${escapeHtml(label)}, ${escapeHtml(value)}">
          <span><b>${escapeHtml(label)}</b> ${escapeHtml(value)}</span><span class="pill__x" aria-hidden="true">×</span>
        </button></li>`)
    .join("");
  box.hidden = !pills.length;
}

function wirePills() {
  document.getElementById("pills").addEventListener("click", (e) => {
    const pill = e.target.closest("[data-pill]");
    if (!pill) return;
    const key = pill.dataset.pill;
    if (key === "q") { state.query = ""; el.search.value = ""; }
    else if (key === "stage") setAll("stage", true);
    else if (key === "inview") setInViewOnly(false);
    else if (key.startsWith("picker:")) {
      const pk = PICKERS.find((x) => x.id === key.slice(7));
      if (pk.custom) { setNear(null, false); return; }
      pk.parts.forEach((part) => setAll(part.f, true));
      if (pk.id === "place") drawOutlines(false);
    }
    render();
    // Keep keyboard focus in the row after the pill disappears.
    const next = document.querySelector("#pills .pill") || el.search;
    next.focus();
  });
}

function setInViewOnly(on) {
  state.inViewOnly = on;
  const box = document.getElementById("inview-only");
  if (box) box.checked = on;
}

// Phones: label the "More filters" button with how many hidden filters are on.
function drawMoreFilters() {
  const button = document.getElementById("more-filters");
  if (!button) return;
  const on = PICKERS.filter((pk) => pickerAvailable(pk) && pickerOn(pk)).length;
  const open = document.body.dataset.filters === "open";
  button.textContent = `${open ? "Fewer" : "More"} filters${on ? ` · ${on} on` : ""}`;
  button.setAttribute("aria-expanded", String(open));
}

const filtersActive = () =>
  Object.keys(FILTERS).some(filterOn) || !!state.near || state.inViewOnly || state.query.trim() !== "";

function clearFilters() {
  Object.keys(FILTERS).forEach((key) => setAll(key, true));
  state.query = "";
  el.search.value = "";
  setInViewOnly(false);
  state.near = null;
  render();
  drawNear(false);
  drawOutlines(false);
  syncNearPanel();
}

function drawCards(list) {
  el.cards.removeAttribute("aria-busy");
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
          <div class="card__stage"><i style="background:${colorOf(p.status)}"></i>${escapeHtml(p.status)}${stageInferred(p) ? ` ${est()}` : ""}</div>
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
  drawMoreFilters();
}

let lastMapKey = "";

function render() {
  const onMap = forMap();
  const list = sorted(state.inViewOnly ? onMap.filter(inMapView) : onMap);
  state.list = list;
  state.onMap = onMap;
  drawCards(list);
  drawSpine();
  syncChips();
  syncPickers();
  drawPills();

  // setData() redraws every dot and clears hover rings, so only when the set
  // of dots actually changed (not on every pan with "only in view" on).
  const key = onMap.map((p) => p.id).join("|");
  if (map && map.getSource("projects") && key !== lastMapKey) {
    lastMapKey = key;
    map.getSource("projects").setData(toGeoJson(onMap));
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
// ---- provenance: which numbers are estimates ------------------------------

const EST_TITLE = "Estimated from permit records. See Stats & About for how.";
const est = (title = EST_TITLE) => `<abbr class="est" title="${escapeHtml(title)}">est.</abbr>`;

// Under Construction from the city's records is inferred from trade permits;
// a stage typed into the sheet is not.
const stageInferred = (p) => p.status === "Under Construction" && /trade permit/i.test(p.stageSource || "");

function unitsNote(p) {
  const src = (p.unitsSource || "").toLowerCase();
  if (src.includes("weekly")) return { text: "From the city’s weekly permit report", estimated: false };
  if (src.includes("monthly")) {
    const asOf = /as of (\d{4}-\d{2}-\d{2})/.exec(p.unitsSource || "");
    return {
      text: `From the city’s monthly report${asOf ? `, last updated ${apDate(asOf[1])}` : ""}; may have changed`,
      estimated: true,
    };
  }
  if (src.includes("description")) return { text: "From the permit description", estimated: false };
  return null;
}

function renderField(field, project) {
  const body =
    field.kind === "link"
      ? `<a href="${escapeHtml(field.value)}" target="_blank" rel="noopener">View application</a>`
      : escapeHtml(field.value);
  let note = "";
  if (project && field.label === "Housing units") {
    const n = unitsNote(project);
    if (n) note = `<small class="prov">${n.estimated ? est(n.text) + " " : ""}${escapeHtml(n.text)}</small>`;
  }
  if (project && field.label === "Building type" && project.buildingTypeInferred) {
    note = `<small class="prov">Worked out from permit descriptions and unit counts</small>`;
  }
  if (project && field.label === "Stage" && stageInferred(project)) {
    note = `<small class="prov">${est()} From trade permits; the city’s public records don’t include inspections</small>`;
  }
  return `<dt>${escapeHtml(field.label)}</dt><dd>${body}${note}</dd>`;
}

// The project's dated events, oldest first, ending with where it stands now.
function timeline(p) {
  const items = (p.milestones || []).map(
    (m) => `<li${m.estimated ? ' class="is-est"' : ""}>
        <time datetime="${escapeHtml(m.date)}">${escapeHtml(apDate(m.date))}</time>
        <span>${escapeHtml(m.label)}${m.estimated ? ` ${est()}` : ""}</span>
      </li>`
  );
  if (p.statusUpdated) {
    items.push(`<li class="is-now" style="--stage:${colorOf(p.status)}">
        <time datetime="${escapeHtml(p.statusUpdated)}">${escapeHtml(apDate(p.statusUpdated))}</time>
        <span>${escapeHtml(p.status)}${stageInferred(p) || !p.stageSinceExact ? ` ${est(stageInferred(p) ? EST_TITLE : "This date comes from permit records, not from a build that saw the change happen.")}` : ""} <em>(current stage)</em></span>
      </li>`);
  }
  if (!items.length) return "";
  return `<section class="timeline" aria-label="Timeline">
      <h3 class="timeline__hed">Timeline</h3>
      <ol>${items.join("")}</ol>
      <p class="timeline__note">Dates come from the city’s permit records. <span class="est">est.</span> marks an estimate. <a href="about.html#h-limits">What the records can’t tell us</a></p>
    </section>`;
}

// Zoning, lot size and transit, when the build found them (site_facts.py).
function siteFacts(p) {
  const rows = [];
  if (p.zone) rows.push(["Zoning", `${p.zone}${p.zoneName ? ` · ${p.zoneName}` : ""}`]);
  if (p.acres > 0) {
    const acres = p.acres < 1 ? p.acres.toFixed(2) : p.acres < 10 ? p.acres.toFixed(1) : Math.round(p.acres);
    const lots = (p.parcels || []).length > 1 ? ` across ${p.parcels.length} parcels` : "";
    rows.push(["Lot size", `${acres} ${+acres === 1 ? "acre" : "acres"}${lots}${p.homesPerAcre ? ` · ${p.homesPerAcre >= 10 ? numberWithCommas(Math.round(p.homesPerAcre)) : p.homesPerAcre.toFixed(1)} homes per acre` : ""}`]);
  }
  if (Number.isFinite(p.transitMiles)) {
    const m = p.transitMiles;
    const dist = m < 0.1 ? "Under 0.1 mile" : `${m.toFixed(1)} ${m.toFixed(1) === "1.0" ? "mile" : "miles"}`;
    const routes = (p.transitRoutes || []).length
      ? ` (${p.transitRoutes.length === 1 ? "route" : "routes"} ${p.transitRoutes.join(", ")})` : "";
    rows.push(["Frequent transit", `${dist} to ${p.transitStop || "the nearest frequent stop"}${routes}`]);
  }
  return rows.map(([dt, dd]) => `<dt>${escapeHtml(dt)}</dt><dd>${escapeHtml(dd)}</dd>`).join("");
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

// Share, copy link and report a correction: icon buttons in the project's top bar.
function correctionMail(p) {
  const url = Share.projectUrl(p.id);
  const subject = `Correction: ${p.name} (${p.id})`;
  const body = [
    `Project: ${p.name}`,
    `Page: ${url}`,
    state.builtAt ? `Data as of: ${apDate(state.builtAt)}` : "",
    "",
    "What's wrong:",
    "",
    "What it should say:",
    "",
    "Source, if you have one:",
    "",
  ].filter((line, i, all) => line !== "" || all[i - 1] !== "").join("\n");
  return `mailto:spokanerising@gmail.com?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function drawDetailTools(p) {
  const box = document.getElementById("detail-tools");
  if (!box) return;
  box.innerHTML = `
    <button type="button" class="iconbtn" data-share-project aria-label="Share this project" aria-haspopup="menu" aria-expanded="false">${Share.icon("share")}</button>
    <button type="button" class="iconbtn" data-copy-project aria-label="Copy link to this project">${Share.icon("link")}</button>
    <a class="iconbtn" data-correction href="${escapeHtml(correctionMail(p))}" aria-label="Report a correction">${Share.icon("mail")}</a>`;
  box.querySelector("[data-share-project]").addEventListener("click", (e) => Share.share(e.currentTarget, projectShare(p)));
  box.querySelector("[data-copy-project]").addEventListener("click", async () => {
    const url = Share.projectUrl(p.id);
    if (await Share.copyText(url)) Share.toast(`Link to ${p.name} copied`);
    else Share.toast(`Copy this link: ${url}`, 8000);
  });
}

function select(id, flyTo, fromHistory = false) {
  const project = state.projects.find((p) => p.id === id);
  if (!project) return;

  const wasOpen = !!state.selected;
  // Where focus goes back to when the project closes (a list row, the map).
  const from = document.activeElement;
  if (!wasOpen || !el.detail.contains(from)) {
    detailOpener = from && from !== document.body && !el.detail.contains(from) ? from : null;
  }
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

    <div class="track" style="--stage:${color}" role="img" aria-label="Stage: ${escapeHtml(project.status)}">
      ${STAGES.slice(0, 5).map((_, i) => `<span class="${i <= stage && stage < 5 ? "on" : ""}"></span>`).join("")}
    </div>
    <p class="track__label"><b>${escapeHtml(project.status)}</b>${project.statusUpdated ? ` since ${escapeHtml(apDate(project.statusUpdated))}` : ""}${
      stageInferred(project) || (project.statusUpdated && !project.stageSinceExact)
        ? ` ${est(stageInferred(project) ? EST_TITLE : "This date comes from permit records, not from a build that saw the change happen.")}`
        : ""
    }</p>

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
      ${project.fields.map((f) => renderField(f, project)).join("")}
    </dl>

    ${timeline(project)}

    ${
      project.drbFile || project.permitNumbers.length || project.parcelId || project.lastVerified || councilOf(project) || siteFacts(project)
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
             ${siteFacts(project)}
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

  drawDetailTools(project);

  el.detail.hidden = false;
  el.detail.dataset.url = Share.projectUrl(project.id);   // printed at the foot
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

let detailOpener = null;

// Close from the × or Escape, and put focus back where it came from: the row
// (redrawn rows are found again by id) or the map.
function closeDetailAndReturn() {
  const id = state.selected;
  closeDetail();
  let target = detailOpener && document.contains(detailOpener) ? detailOpener : null;
  if (!target && id) target = el.cards.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  detailOpener = null;
  if (target) target.focus({ preventScroll: false });
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
//   &size=20-99,100  &filed=30,90  &since=30  &district=2  &hood=logan,riverside
//   &transit=quarter  &zone=rmf,cc2  &density=50,100  &near=47.65750,-117.42330,0.5
//   &nearlabel=10 N Post St  &sort=homes  &view=list
// Each filter lists the options that are ticked ("none" if none are).
// Anything at its default is left out. Opening a project adds a history step
// (so Back closes it); filter changes just replace the current address.
//
// Links shared before the filters became checklists still work: ?time=filed:90
// and ?place=district:2 / ?place=hood:Logan are read and rewritten.

const FILTER_ORDER = ["stage", "type", "size", "filed", "since", "district", "hood", "transit", "zone", "density"];

function urlFromState() {
  const params = new URLSearchParams();
  if (state.selected) params.set("p", state.selected);
  if (state.query.trim()) params.set("q", state.query.trim());
  FILTER_ORDER.forEach((key) => {
    if (!filterOn(key)) return;
    const on = FILTERS[key].opts.filter((o) => state.sel[key].has(o.key)).map((o) => o.key);
    const middle = MIDDLE_TYPES.map(slug);
    const isMiddle = key === "type" && on.length === middle.length && middle.every((k) => on.includes(k));
    params.set(FILTERS[key].param, isMiddle ? "middle" : on.join(",") || "none");
  });
  if (state.near) {
    params.set("near", `${state.near.lat.toFixed(5)},${state.near.lng.toFixed(5)},${state.near.miles}`);
    if (state.near.label) params.set("nearlabel", state.near.label);
  }
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

// Old single-choice links, as ticks in the new checklists.
const LEGACY_TIME = {
  "filed:30": ["filed", ["30"]], "filed:90": ["filed", ["30", "90"]], "filed:365": ["filed", ["30", "90", "365"]],
  "filed:old": ["filed", ["730", "old"]], "filed:none": ["filed", ["unknown"]],
  "stage:30": ["since", ["30"]], "stage:90": ["since", ["30", "90"]], "stage:365": ["since", ["30", "90", "365"]],
};

function readUrl() {
  const params = new URLSearchParams(location.search);
  const list = (key) => (params.get(key) || "").split(",").map((v) => v.trim()).filter(Boolean);

  state.query = params.get("q") || "";
  el.search.value = state.query;

  const wanted = {};
  FILTER_ORDER.forEach((key) => {
    const F = FILTERS[key];
    if (params.has(F.param)) wanted[key] = list(F.param);
  });
  const legacyTime = LEGACY_TIME[params.get("time")];
  if (legacyTime && !wanted[legacyTime[0]]) wanted[legacyTime[0]] = legacyTime[1];
  const place = /^(district|hood):(.*)$/s.exec(params.get("place") || "");
  if (place && !wanted[place[1]]) wanted[place[1]] = [place[2] ? (place[1] === "hood" ? slug(place[2]) : place[2]) : "outside"];

  Object.keys(FILTERS).forEach((key) => {
    setAll(key, true);
    const values = wanted[key];
    if (!values || !FILTERS[key].opts.length) return;
    if (values[0] === "none") return setAll(key, false);
    const known = new Set(FILTERS[key].opts.map((o) => o.key));
    const keys = (FILTERS[key].legacy && FILTERS[key].legacy(values)) || values;
    const on = keys.filter((k) => known.has(k));
    if (on.length) state.sel[key] = new Set(on); // nothing recognisable: leave the filter off
  });

  state.near = null;
  const near = list("near").map(Number);
  if (near.length >= 2 && near.slice(0, 2).every(Number.isFinite) && Math.abs(near[0]) <= 90) {
    const miles = RADII.some((r) => r[0] === near[2]) ? near[2] : 0.5;
    nearMiles = miles;
    state.near = { lat: near[0], lng: near[1], miles, label: (params.get("nearlabel") || "a point on the map").slice(0, 80) };
  }

  state.sort = SORTS[params.get("sort")] ? params.get("sort") : "recent";
  document.getElementById("sort").value = state.sort;

  if (params.get("view") === "list") setView("list");
  return params.get("p");
}

// ---- sharing and downloads (share.js does the work) -------------------------

// How each stage reads in a sentence: "96 homes, under construction in Riverside".
const STAGE_PHRASE = {
  "Pre-Application": "proposed",
  "Applied": "in permit review",
  "Approved": "approved",
  "Under Construction": "under construction",
  "Complete": "complete",
  "Stalled": "stalled",
};

function projectShare(p) {
  const place = p.neighborhood || councilOf(p);
  const what = [
    p.units > 0 ? plural(p.units, "home", "homes") : "",
    [STAGE_PHRASE[p.status] || (p.status || "").toLowerCase(), place ? `in ${place}` : ""].filter(Boolean).join(" "),
  ].filter(Boolean).join(", ");
  return {
    url: Share.projectUrl(p.id),
    copied: p.name,
    title: `${p.name} · ${Share.SITE_NAME}`,
    text: `${p.name}${what ? `: ${what}` : ""}. Via ${Share.SITE_NAME}`,
  };
}

// The filters in words, from the pills: "Riverside, Middle housing".
function filtersInWords() {
  const bits = [];
  if (state.query.trim()) bits.push(`“${state.query.trim()}”`);
  if (filterOn("stage")) bits.push(stageSummary());
  PICKERS.filter((pk) => pickerAvailable(pk) && pickerOn(pk)).forEach((pk) =>
    bits.push(pk.custom ? `within ${radiusLabel(state.near.miles)} of ${state.near.label}` : pickerSummary(pk))
  );
  if (state.inViewOnly) bits.push("in one part of the map");
  return bits.join(", ");
}

// When the only thing narrowing the map is one neighborhood council or one
// council district, share that area's own page, which previews with its name
// and numbers. Anything else shares the full address of the view.
function areaPageUrl() {
  const others = Object.keys(FILTERS).filter((k) => k !== "hood" && k !== "district" && filterOn(k));
  if (others.length || state.query.trim() || state.near || state.inViewOnly) return null;
  const one = (key) => (filterOn(key) && state.sel[key].size === 1 ? [...state.sel[key]][0] : null);
  const hood = one("hood"), district = one("district");
  if (hood && hood !== "outside" && !filterOn("district")) return Share.hoodUrl(hood);
  if (district && district !== "outside" && !filterOn("hood")) return Share.districtUrl(district);
  return null;
}

function viewShare() {
  const list = state.list || [];
  const homes = unitsOf(list);
  const tally = `${plural(list.length, "project", "projects")}${homes ? `, ${plural(homes, "home", "homes")}` : ""}`;
  const filters = filtersInWords();
  return {
    url: areaPageUrl() || new URL(urlFromState(), location.href).href,
    copied: "this view",
    title: Share.SITE_NAME,
    text: filters
      ? `Spokane housing projects, ${filters}: ${tally}. Via ${Share.SITE_NAME}`
      : `Spokane’s housing pipeline: ${tally}. Via ${Share.SITE_NAME}`,
  };
}

// Download what the list is showing now: every filter, and "only what's in
// map view" too.
function downloadList(anchor) {
  const list = state.list || [];
  const filtered = list.length !== state.projects.length;
  const date = state.builtAt || new Date();
  const label = `${filtered ? "these " : "all "}${plural(list.length, "project", "projects")}`;
  Share.menu(anchor, [
    { id: "csv", label: "Spreadsheet (CSV)", note: label, onSelect: () => {
        Share.downloadText(Share.projectsCsv(list), Share.filename(filtered ? ["filtered"] : [], "csv", date), "text/csv");
        Share.toast(`Downloaded ${label}`);
      } },
    { id: "geojson", label: "Map data (GeoJSON)", note: "For GIS tools", onSelect: () => {
        const meta = {
          dataAsOf: state.builtAt ? state.builtAt.toISOString() : null,
          view: new URL(urlFromState(), location.href).href,
          filters: filtersInWords() || "none",
        };
        Share.downloadText(Share.projectsGeoJson(list, meta), Share.filename(filtered ? ["filtered"] : [], "geojson", date), "application/geo+json");
        Share.toast(`Downloaded ${label}`);
      } },
  ], { label: "Download" });
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

// ---- map overlays: the "Near" circle and neighborhood outlines --------------

function circlePolygon(center, miles, steps = 72) {
  const dLat = miles / MILES_PER_DEG_LAT;
  const dLng = dLat / Math.cos((center.lat * Math.PI) / 180);
  const ring = [];
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    ring.push([center.lng + dLng * Math.cos(a), center.lat + dLat * Math.sin(a)]);
  }
  return ring;
}

const EMPTY = { type: "FeatureCollection", features: [] };

function boundsOf(features) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const walk = (c) => {
    if (typeof c[0] === "number") {
      minX = Math.min(minX, c[0]); maxX = Math.max(maxX, c[0]);
      minY = Math.min(minY, c[1]); maxY = Math.max(maxY, c[1]);
    } else c.forEach(walk);
  };
  features.forEach((f) => walk(f.geometry.coordinates));
  return Number.isFinite(minX) ? [[minX, minY], [maxX, maxY]] : null;
}

function fitTo(bounds) {
  if (!map || !bounds) return;
  const wide = window.matchMedia("(min-width: 861px)").matches;
  map.fitBounds(bounds, { padding: wide ? 48 : 28, maxZoom: 15.5, duration: 600 });
}

function drawNear(fit = false) {
  if (!map || !map.getSource("near")) return;
  if (!state.near) {
    map.getSource("near").setData(EMPTY);
    return;
  }
  const ring = circlePolygon(state.near, state.near.miles);
  map.getSource("near").setData({
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: { part: "circle" } },
      { type: "Feature", geometry: { type: "Point", coordinates: [state.near.lng, state.near.lat] }, properties: { part: "center" } },
    ],
  });
  if (fit) fitTo(boundsOf([{ geometry: { coordinates: ring } }]));
}

let outlines = null;          // boundaries.geojson, once loaded
let outlinesLoading = null;

function loadOutlines() {
  if (!outlinesLoading) {
    outlinesLoading = fetch("boundaries.geojson")
      .then((r) => (r.ok ? r.json() : EMPTY))
      .catch(() => EMPTY)
      .then((data) => (outlines = data));
  }
  return outlinesLoading;
}

// Draws the edges of the neighborhoods (or, failing that, the council
// districts) the Where filter is narrowed to.
function selectedAreas() {
  if (!outlines) return [];
  const pick = (kind, key) =>
    outlines.features.filter((f) => f.properties.kind === kind && state.sel[key].has(kind === "hood" ? slug(f.properties.name) : String(f.properties.name)));
  if (filterOn("hood")) return pick("hood", "hood");
  if (filterOn("district")) return pick("district", "district");
  return [];
}

async function drawOutlines(fit = false) {
  if (!map || !map.getSource("areas")) return;
  if (!filterOn("hood") && !filterOn("district")) {
    map.getSource("areas").setData(EMPTY);
    return;
  }
  await loadOutlines();
  const features = selectedAreas();
  map.getSource("areas").setData({ type: "FeatureCollection", features });
  if (fit && features.length) fitTo(boundsOf(features));
}

function addOverlayLayers() {
  map.addSource("areas", { type: "geojson", data: EMPTY });
  map.addSource("near", { type: "geojson", data: EMPTY });
  const below = "project-dot";
  map.addLayer({ id: "areas-fill", type: "fill", source: "areas", paint: { "fill-color": "#121212", "fill-opacity": 0.035 } }, below);
  map.addLayer({ id: "areas-line", type: "line", source: "areas", paint: { "line-color": "#121212", "line-width": 1.6, "line-dasharray": [3, 2] } }, below);
  map.addLayer({ id: "near-fill", type: "fill", source: "near", filter: ["==", ["get", "part"], "circle"],
    paint: { "fill-color": "#275b84", "fill-opacity": 0.06 } }, below);
  map.addLayer({ id: "near-line", type: "line", source: "near", filter: ["==", ["get", "part"], "circle"],
    paint: { "line-color": "#275b84", "line-width": 1.6 } }, below);
  map.addLayer({ id: "near-center", type: "circle", source: "near", filter: ["==", ["get", "part"], "center"],
    paint: { "circle-radius": 4, "circle-color": "#275b84", "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
}

// ---- saving the map as an image ------------------------------------------------
//
// "Save image" offers the current view or three sizes made for social posts.
// The picture is drawn by a hidden second map of exactly that size (the
// visible map's WebGL drawing is cleared after every frame, and resizing it
// would make the page jump), using the visible map's style: same dots,
// filters, outlines and Near circle. Always the plain map: Esri's terms for
// saving satellite imagery haven't been checked. Then a title band, a key
// and the required map credits are drawn around it, and it's saved as a
// JPEG (on phones, offered to the share sheet so it can go to Photos).

const EXPORT_SIZES = [
  { id: "view", label: "Current view", note: "The map as you see it" },
  { id: "square", label: "Square", note: "1080 × 1080, for Instagram", w: 1080, h: 1080 },
  { id: "landscape", label: "Landscape", note: "1200 × 630, for links and X", w: 1200, h: 630 },
  { id: "portrait", label: "Portrait", note: "1080 × 1350, for Instagram", w: 1080, h: 1350 },
];

// Required credits for the base map (OpenFreeMap's tiles, built from
// OpenMapTiles and OpenStreetMap data).
const MAP_CREDIT = "Map: OpenFreeMap, © OpenMapTiles, data © OpenStreetMap contributors";

// Room the title band and the key take, in output pixels per 1,000 pixels of
// width; the hidden map leaves that much padding so no dot hides under them.
const BAND = { top: 112, bottom: 78 };

function waitForIdle(m, ms = 9000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    m.once("idle", finish);
    setTimeout(finish, ms); // a tile that never arrives shouldn't block the save
  });
}

// Draws the visible map's style into a hidden map of cssW x cssH at the given
// pixel ratio, covering the visible map's view. Returns its canvas, the area
// it shows, and a function to clean up.
async function renderMapCopy(cssW, cssH, ratio, pad) {
  const box = document.createElement("div");
  box.style.cssText = `position:fixed;left:-10000px;top:0;width:${cssW}px;height:${cssH}px;`;
  document.body.appendChild(box);
  const style = map.getStyle();
  style.layers = style.layers.map((l) =>
    l.id === "satellite" ? { ...l, layout: { ...(l.layout || {}), visibility: "none" } } : l
  );
  const copy = new maplibregl.Map({
    container: box, style, interactive: false, attributionControl: false,
    preserveDrawingBuffer: true, pixelRatio: ratio, fadeDuration: 0,
    bounds: map.getBounds(), fitBoundsOptions: { padding: pad },
  });
  await new Promise((resolve, reject) => {
    copy.once("load", resolve);
    setTimeout(() => reject(new Error("the map copy didn't load")), 15000);
  });
  // Plain-map label halos, in case the visible map is on satellite.
  labelLayers.forEach((layer) => {
    try {
      copy.setPaintProperty(layer.id, "text-halo-width", layer.haloWidth);
      copy.setPaintProperty(layer.id, "text-halo-color", layer.haloColor);
    } catch (error) { /* not every label has a halo */ }
  });
  if (state.selected && copy.getSource("projects")) {
    copy.setFeatureState({ source: "projects", id: state.selected }, { selected: true });
  }
  await waitForIdle(copy);
  return { canvas: copy.getCanvas(), bounds: copy.getBounds(), done: () => { copy.remove(); box.remove(); } };
}

function fitText(ctx, text, maxW) {
  if (ctx.measureText(text).width <= maxW) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(`${t}…`).width > maxW) t = t.slice(0, -1);
  return `${t.trimEnd()}…`;
}

// Title band, key and credits around the map picture.
function composeMapImage(mapCanvas, outW, outH, inView) {
  const out = document.createElement("canvas");
  out.width = outW;
  out.height = outH;
  const ctx = out.getContext("2d");
  const u = outW / 1000; // layout unit: everything scales with the width
  ctx.fillStyle = "#faf8f3";
  ctx.fillRect(0, 0, outW, outH);
  ctx.drawImage(mapCanvas, 0, 0, outW, outH);

  const top = BAND.top * u, bottom = BAND.bottom * u, side = 32 * u;
  ctx.fillStyle = "rgba(250, 248, 243, 0.95)";
  ctx.fillRect(0, 0, outW, top);
  ctx.fillRect(0, outH - bottom, outW, bottom);
  ctx.fillStyle = "#121212";
  ctx.fillRect(0, top - Math.max(1, u), outW, Math.max(1, u));
  ctx.fillRect(0, outH - bottom, outW, Math.max(1, u));

  // Title: "Spokane in Progress", then what's shown.
  ctx.textBaseline = "alphabetic";
  ctx.font = `600 ${34 * u}px Newsreader, Georgia, serif`;
  ctx.fillText("Spokane ", side, 48 * u);
  const w1 = ctx.measureText("Spokane ").width;
  ctx.font = `italic 500 ${34 * u}px Newsreader, Georgia, serif`;
  ctx.fillText("in Progress", side + w1, 48 * u);

  const homes = unitsOf(inView);
  const tally = `${plural(inView.length, "housing project", "housing projects")}${homes ? `, at least ${plural(homes, "home", "homes")}` : ""}`;
  const filters = filtersInWords();
  const line = filters ? `${filters[0].toUpperCase()}${filters.slice(1)}: ${tally}` : `${tally[0].toUpperCase()}${tally.slice(1)} on this map`;
  ctx.font = `500 ${21 * u}px "Libre Franklin", Arial, sans-serif`;
  ctx.fillStyle = "#3a3936";
  ctx.fillText(fitText(ctx, line, outW - 2 * side), side, 84 * u);

  // Key: the stages on this map.
  const present = STAGES.filter((s) => inView.some((p) => p.status === s.name));
  ctx.font = `500 ${15 * u}px "Libre Franklin", Arial, sans-serif`;
  let x = side;
  const ky = outH - bottom + 28 * u;
  present.forEach((s) => {
    const label = s.name;
    const w = 14 * u + ctx.measureText(label).width + 18 * u;
    if (x + w > outW - side) return;
    ctx.fillStyle = s.color;
    ctx.beginPath();
    ctx.arc(x + 5 * u, ky - 5 * u, 5 * u, 0, 2 * Math.PI);
    ctx.fill();
    ctx.fillStyle = "#121212";
    ctx.fillText(label, x + 14 * u, ky);
    x += w;
  });

  // Credits: the site and data date, then the map's required credit.
  ctx.fillStyle = "#6b6964";
  ctx.font = `500 ${12.5 * u}px "Libre Franklin", Arial, sans-serif`;
  ctx.fillText(fitText(ctx, `${Share.creditLine(state.builtAt)} · Circle size shows homes`, outW - 2 * side), side, outH - 30 * u);
  ctx.fillText(fitText(ctx, MAP_CREDIT, outW - 2 * side), side, outH - 13 * u);
  return out;
}

async function saveMapImage(size, button) {
  // Only the style needs to be in; the copy waits for its own tiles.
  if (!map || !map.isStyleLoaded() || !map.getSource("projects")) {
    return Share.toast("The map is still loading. Try again in a moment.");
  }
  button.setAttribute("aria-busy", "true");
  button.dataset.tip = "Saving…";
  Share.retip(button);
  let copy = null;
  try {
    await Share.fontsReady();
    const container = map.getContainer();
    const outW = size.w || Math.round(container.clientWidth * Math.min(2, window.devicePixelRatio || 1));
    const outH = size.h || Math.round(container.clientHeight * Math.min(2, window.devicePixelRatio || 1));
    // Draw the map at a size where labels read naturally: a 1080-wide image
    // gets a ~540-wide map at twice the detail.
    const ratio = size.w ? 2 : Math.min(2, window.devicePixelRatio || 1);
    const cssW = Math.round(outW / ratio), cssH = Math.round(outH / ratio);
    const pad = { top: (BAND.top * outW / 1000) / ratio + 8, bottom: (BAND.bottom * outW / 1000) / ratio + 8, left: 12, right: 12 };
    copy = await renderMapCopy(cssW, cssH, ratio, pad);
    const inView = (state.onMap || []).filter((p) => Number.isFinite(p.lng) && copy.bounds.contains([p.lng, p.lat]));
    const image = composeMapImage(copy.canvas, outW, outH, inView);
    const name = Share.filename(["map", size.id === "view" ? "" : size.id], "jpg", state.builtAt || new Date());
    const blob = await new Promise((resolve, reject) =>
      image.toBlob((b) => (b ? resolve(b) : reject(new Error("no image"))), "image/jpeg", 0.92)
    );
    // Phones: the share sheet, which can save to Photos. Elsewhere: a download.
    const file = new File([blob], name, { type: "image/jpeg" });
    if (Share.prefersNativeShare() && navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: Share.SITE_NAME });
        return;
      } catch (error) {
        if (error && error.name === "AbortError") return;
      }
    }
    Share.downloadBlob(blob, name);
    Share.toast("Map image saved");
  } catch (error) {
    console.warn(error);
    Share.toast("Couldn’t save the map image. Please try again.");
  } finally {
    if (copy) copy.done();
    button.removeAttribute("aria-busy");
    delete button.dataset.tip;
    Share.retip(button);
  }
}

function wireSaveMap() {
  const button = document.getElementById("save-map");
  if (!button) return;
  button.addEventListener("click", () => {
    if (button.getAttribute("aria-busy") === "true") return;
    Share.menu(button, EXPORT_SIZES.map((s) => ({
      id: s.id, label: s.label, note: s.note, onSelect: () => saveMapImage(s, button),
    })), { label: "Save the map as an image" });
  });
}

// ---- whole city, and getting around the map by keyboard ----------------------

// The city's outer edge, from the council districts in boundaries.geojson;
// the fixed box until (or unless) that file loads.
function cityBounds() {
  const districts = outlines ? outlines.features.filter((f) => f.properties.kind === "district") : [];
  if (!districts.length) return CITY_BOUNDS;
  const b = new maplibregl.LngLatBounds();
  districts.forEach((f) => {
    const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    polys.forEach((poly) => poly[0].forEach((pt) => b.extend(pt)));
  });
  return b.toArray();
}

function showWholeCity() {
  if (!map) return;
  loadOutlines().then(() => map.fitBounds(cityBounds(), { padding: 24, duration: 700 }));
}

// A map button under + and −: zoom out to the whole city.
class WholeCityControl {
  onAdd() {
    this.box = document.createElement("div");
    this.box.className = "maplibregl-ctrl maplibregl-ctrl-group";
    this.box.innerHTML = `<button type="button" class="iconbtn citybtn" id="whole-city" aria-label="Show the whole city">${Share.icon("city")}</button>`;
    this.box.querySelector("button").addEventListener("click", showWholeCity);
    return this.box;
  }
  onRemove() { this.box.remove(); }
}

// On the focused map: arrows pan and + / − zoom (MapLibre's own), [ and ]
// step through the projects in view from the middle outward, Enter opens the
// one stepped to, 0 shows the whole city. A hint shows while the map has
// keyboard focus, and a hidden live line reads out each project.
let stepList = [], stepAt = -1;
const stepTip = () => (stepTip.popup ||= new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: "tip" }));

function projectsInView() {
  const b = map.getBounds(), c = map.project(map.getCenter());
  return (state.onMap || [])
    .filter((p) => Number.isFinite(p.lng) && b.contains([p.lng, p.lat]))
    .map((p) => ({ p, d: map.project([p.lng, p.lat]).dist(c) }))
    .sort((a, z) => a.d - z.d)
    .map((x) => x.p);
}

function step(by) {
  if (stepAt < 0 || !stepList.length) { stepList = projectsInView(); stepAt = by > 0 ? -1 : 0; }
  if (!stepList.length) return announce("No projects in this part of the map. Zoom out with the minus key, or press 0 for the whole city.");
  stepAt = (stepAt + by + stepList.length) % stepList.length;
  const p = stepList[stepAt];
  setHover(p.id, "map");
  stepTip().setLngLat([p.lng, p.lat]).setText(p.name).addTo(map);
  const homes = p.units > 0 ? `, ${plural(p.units, "home", "homes")}` : "";
  announce(`${p.name}${homes}, ${p.status}. ${stepAt + 1} of ${stepList.length} in view. Press Enter to open.`);
}

function stopStepping() {
  stepList = []; stepAt = -1;
  if (stepTip.popup) stepTip.popup.remove();
}

function announce(text) {
  const box = document.getElementById("map-live");
  if (box) box.textContent = text;
}

function wireMapKeys() {
  const canvas = map.getCanvas();
  canvas.setAttribute("aria-label", "Map of projects. Arrow keys move, plus and minus zoom, square brackets step through projects, Enter opens one, 0 shows the whole city.");
  canvas.setAttribute("aria-describedby", "map-live");
  canvas.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === "]" || e.key === "[") { e.preventDefault(); step(e.key === "]" ? 1 : -1); }
    else if (e.key === "Enter" && stepAt >= 0 && stepList[stepAt]) { e.preventDefault(); const p = stepList[stepAt]; stopStepping(); select(p.id, true); }
    else if (e.key === "0") { e.preventDefault(); showWholeCity(); }
    else if (e.key === "Escape" && stepAt >= 0) { e.stopPropagation(); stopStepping(); setHover(null, "map"); announce(""); }
  });
  canvas.addEventListener("focus", () => { if (canvas.matches(":focus-visible")) document.body.dataset.mapkeys = "on"; });
  canvas.addEventListener("blur", () => { delete document.body.dataset.mapkeys; stopStepping(); setHover(null, "map"); });
  map.on("movestart", () => { if (stepAt >= 0) { stopStepping(); setHover(null, "map"); } });
}

// Skip links: past the filters to the list, or straight to the map.
function wireSkipLinks() {
  document.getElementById("skip-list").addEventListener("click", (e) => {
    e.preventDefault();
    if (window.matchMedia("(max-width: 860px)").matches) setView("list");
    const first = el.cards.querySelector(".card");
    (first || el.cards).focus();
  });
  document.getElementById("skip-map").addEventListener("click", (e) => {
    e.preventDefault();
    if (window.matchMedia("(max-width: 860px)").matches) setView("map");
    if (map) map.getCanvas().focus();
  });
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
  map.addControl(new WholeCityControl(), "top-right");
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "imperial" }), "bottom-right");
  wireMapKeys();

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
    // An invisible ring 8px wider than each dot, so small dots are easy to tap.
    map.addLayer({
      id: "project-hit",
      type: "circle",
      source: "projects",
      paint: { "circle-radius": radiusExpression(8), "circle-opacity": 0 },
    });
    addOverlayLayers();
    lastMapKey = "";
    markSelected();
    drawInView();
    drawNear(false);
    drawOutlines(false);
    // With "only what's in map view" on, the list follows the map.
    map.on("moveend", () => (state.inViewOnly ? render() : drawInView()));

    // Picking a spot for "Near".
    map.on("click", (e) => {
      if (!picking) return;
      // The same click also reaches the dot layer's handler; pickedAt tells
      // it to ignore this one, so picking a spot never opens a project.
      pickedAt = Date.now();
      setPicking(false);
      setNear({ lat: e.lngLat.lat, lng: e.lngLat.lng, label: "the spot you picked" });
    });

    map.on("zoomend", drawMapKey);
    drawMapKey();

    document.querySelectorAll(".basemap button").forEach((button) => {
      button.addEventListener("click", () => setBasemap(button.dataset.basemap));
    });
    setBasemap(savedBasemap());

    // A dot under the pointer wins; otherwise the nearest ring around one.
    const pick = (e) => {
      const dots = map.queryRenderedFeatures(e.point, { layers: ["project-dot"] });
      if (dots.length) return dots[0];
      const near = (f) => map.project(f.geometry.coordinates).dist(e.point);
      return [...e.features].sort((a, b) => near(a) - near(b))[0];
    };
    map.on("click", "project-hit", (e) => {
      if (picking || Date.now() - pickedAt < 400) return;
      select(pick(e).properties.id, false);
    });
    // Hovering a dot rings it, highlights its row and shows its name.
    const tip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: "tip" });
    map.on("mousemove", "project-hit", (e) => {
      const f = pick(e);
      map.getCanvas().style.cursor = "pointer";
      setHover(f.properties.id, "map");
      tip.setLngLat(f.geometry.coordinates).setText(f.properties.name).addTo(map);
    });
    map.on("mouseleave", "project-hit", () => {
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
  el.cards.innerHTML = "";
  el.cards.removeAttribute("aria-busy");
  const lede = document.getElementById("lede");
  if (lede) { lede.classList.remove("is-loading"); lede.textContent = ""; }
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

  document.getElementById("detail-close").addEventListener("click", () => closeDetailAndReturn());
  wireSkipLinks();
  document.getElementById("sort").addEventListener("change", (e) => {
    state.sort = e.target.value;
    render();
  });
  document.getElementById("share-view").addEventListener("click", (e) => Share.share(e.currentTarget, viewShare()));
  document.getElementById("download-list").addEventListener("click", (e) => downloadList(e.currentTarget));
  window.addEventListener("popstate", () => {
    const id = readUrl();
    if (id) select(id, true, true);
    else if (!el.detail.hidden) closeDetail(true);
    render();
  });

  wirePickers();
  wireNear();
  wirePills();
  wireChips();
  wireSaveMap();
  document.getElementById("inview-only").addEventListener("change", (e) => {
    setInViewOnly(e.target.checked);
    render();
  });
  document.getElementById("clear-filters").addEventListener("click", clearFilters);
  wirePanelToggle();
  document.getElementById("more-filters").addEventListener("click", () => {
    document.body.dataset.filters = document.body.dataset.filters === "open" ? "closed" : "open";
    drawMoreFilters();
  });

  document.querySelectorAll("#measure button").forEach((button) => {
    button.addEventListener("click", () => {
      state.measure = button.dataset.measure;
      drawSpine();
    });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.detail.hidden && !document.querySelector(".menu")) closeDetailAndReturn();
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

  setUpFilters();
  drawChips();
  drawPickers();
  if (!FILTERS.density.opts.length) document.querySelector('#sort option[value="density"]')?.remove();

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
