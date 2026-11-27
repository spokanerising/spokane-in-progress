// Spokane in Progress — Stats & About page.
// Reads the same projects.json as the map and draws plain HTML charts, so the
// numbers here always match the map's. No chart library.

const STAGE_ORDER = ["Pre-Application", "Applied", "Approved", "Under Construction", "Complete", "Stalled"];
const PIPELINE = ["Applied", "Approved", "Under Construction"];

const MIDDLE_TYPES = ["Duplex", "Triplex or fourplex", "Fiveplex or sixplex", "Townhomes", "Cottage housing"];
const OTHER_TYPES = ["Apartments", "House + ADU", "Conversion or addition", "Senior & group living"];
const UNKNOWN_TYPE = "Not yet known";

const SIZES = [
  { label: "2–4 homes", test: (u) => u >= 2 && u <= 4 },
  { label: "5–19 homes", test: (u) => u >= 5 && u <= 19 },
  { label: "20–99 homes", test: (u) => u >= 20 && u <= 99 },
  { label: "100 or more homes", test: (u) => u >= 100 },
  { label: "Size not reported", test: (u) => !(u > 0) },
];

const AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];

let STAGES = STAGE_ORDER.map((name) => ({ name, color: "#999" }));
let projects = [];
let builtAt = null;

// --------------------------------------------------------------------------

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString("en-US");
const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;
const units = (p) => (p.units > 0 ? p.units : 0);
const sumUnits = (list) => list.reduce((s, p) => s + units(p), 0);
const colorOf = (stage) => (STAGES.find((s) => s.name === stage) || {}).color || "#999";
const typeOf = (p) => p.buildingType || UNKNOWN_TYPE;
const firstFiled = (p) => ((p.permits || []).map((x) => x.opened).filter(Boolean).sort()[0] || "");

function apDate(value) {
  if (!value) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(value);
  return isNaN(d) ? String(value) : `${AP_MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

const sourceLine = () =>
  `Source: City of Spokane permit records, compiled by Spokane in Progress. Data as of ${apDate(builtAt)}.`;

// --------------------------------------------------------------------------
// Stacked horizontal bars: one row per group, segments by stage, homes.

function stackedBars({ title, rows, note }) {
  const max = Math.max(1, ...rows.filter((r) => !r.header).map((r) => sumUnits(r.items)));
  const body = rows
    .map((r) => {
      if (r.header) {
        return `<div class="bars__group">${esc(r.label)}<span>${plural(sumUnits(r.items), "home", "homes")} · ${plural(r.items.length, "project", "projects")}</span></div>`;
      }
      const total = sumUnits(r.items);
      const segs = STAGES.map((s) => {
        const n = sumUnits(r.items.filter((p) => p.status === s.name));
        return n
          ? `<span class="bars__seg" style="width:${(100 * n) / max}%;background:${s.color}" title="${esc(r.label)}: ${fmt(n)} ${esc(s.name.toLowerCase())}"></span>`
          : "";
      }).join("");
      const missing = r.items.filter((p) => !(p.units > 0)).length;
      return `<div class="bars__row${r.indent ? " bars__row--indent" : ""}">
          <div class="bars__label">${esc(r.label)}</div>
          <div class="bars__track">${segs}<span class="bars__value"><b>${fmt(total)}</b>${missing ? `<small> +${missing} not reported</small>` : ""}</span></div>
          <div class="bars__n">${plural(r.items.length, "project", "projects")}</div>
        </div>`;
    })
    .join("");
  return `<figcaption class="chart__title">${esc(title)}</figcaption>
    <div class="bars" role="img" aria-label="${esc(title)}">${body}</div>
    <p class="source">${note ? `Note: ${esc(note)} ` : ""}${esc(sourceLine())}</p>`;
}

// Columns: projects first filed each quarter.
function quarterColumns() {
  const quarter = (iso) => `${iso.slice(0, 4)}-Q${Math.floor((+iso.slice(5, 7) - 1) / 3) + 1}`;
  const dated = projects.filter((p) => firstFiled(p));
  if (!dated.length) return "";
  const keys = [];
  const first = firstFiled(dated.reduce((a, b) => (firstFiled(a) < firstFiled(b) ? a : b)));
  let y = +first.slice(0, 4);
  let q = Math.floor((+first.slice(5, 7) - 1) / 3) + 1;
  const last = quarter(builtAt.toISOString().slice(0, 10));
  for (;;) {
    const k = `${y}-Q${q}`;
    keys.push(k);
    if (k === last || keys.length > 40) break;
    q += 1;
    if (q > 4) { q = 1; y += 1; }
  }
  const byQ = Object.fromEntries(keys.map((k) => [k, dated.filter((p) => quarter(firstFiled(p)) === k)]));
  const max = Math.max(1, ...keys.map((k) => byQ[k].length));
  const partialFirst = !/-(01|04|07|10)-0[1-7]$/.test(first) ? keys[0] : null;
  const cols = keys
    .map((k) => {
      const list = byQ[k];
      const mid = list.filter((p) => p.middleHousing).length;
      const partial = k === last || k === partialFirst;
      const [yy, qq] = k.split("-");
      return `<div class="cols__col${partial ? " cols__col--partial" : ""}" title="${qq} ${yy}: ${plural(list.length, "project", "projects")}, ${plural(sumUnits(list), "home", "homes")}${partial ? " (partial quarter)" : ""}">
          <span class="cols__n">${list.length || ""}</span>
          <span class="cols__bar" style="height:${(100 * list.length) / max}%">
            <span class="cols__mid" style="height:${list.length ? (100 * mid) / list.length : 0}%"></span>
          </span>
          <span class="cols__q">${qq}${qq === "Q1" || k === keys[0] ? `<br>${yy}` : ""}</span>
        </div>`;
    })
    .join("");
  return `<figcaption class="chart__title">Projects first filed with the city, by quarter</figcaption>
    <ul class="legend legend--small">
      <li><i style="background:var(--ink-2)"></i>Middle housing</li>
      <li><i style="background:#b9b2a5"></i>Other housing</li>
    </ul>
    <div class="cols" role="img" aria-label="Projects first filed with the city, by quarter">${cols}</div>
    <p class="source">Note: Counts projects still on the map, by the date of their earliest city record (a pre-development meeting counts). The city’s public permit map keeps about three years of records; the first and last quarters shown are partial, and ${plural(projects.length - dated.length, "project has", "projects have")} no filing date. ${esc(sourceLine())}</p>`;
}

function sizeTable() {
  const total = sumUnits(projects);
  const rows = SIZES.map((s) => {
    const list = projects.filter((p) => s.test(p.units));
    const homes = sumUnits(list);
    return `<tr><th scope="row">${esc(s.label)}</th><td>${fmt(list.length)}</td><td>${list.length && homes ? fmt(homes) : "–"}</td>
      <td class="share"><span style="width:${total ? (100 * homes) / total : 0}%"></span>${total && homes ? `${Math.round((100 * homes) / total)}%` : ""}</td></tr>`;
  }).join("");
  return `<figcaption class="chart__title">Projects and homes by project size</figcaption>
    <table class="table">
      <thead><tr><th scope="col">Size</th><th scope="col">Projects</th><th scope="col">Homes</th><th scope="col">Share of homes</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="source">Note: Size counts every home in a project, across all its buildings, at every stage. ${esc(sourceLine())}</p>`;
}

// --------------------------------------------------------------------------

function draw() {
  const inStages = (names) => projects.filter((p) => names.includes(p.status));
  const pipeline = sumUnits(inStages(PIPELINE));
  const building = sumUnits(inStages(["Under Construction"]));
  const proposed = sumUnits(inStages(["Pre-Application"]));
  const middle = sumUnits(inStages(PIPELINE).filter((p) => p.middleHousing));
  const missing = projects.filter((p) => !(p.units > 0)).length;

  document.getElementById("dek").innerHTML =
    `At least <b>${fmt(pipeline)}</b> homes are working their way through Spokane’s permit process, <b>${fmt(building)}</b> of them under construction. Developers have proposed <b>${fmt(proposed)}</b> more. Here is where they are, what kind of housing they are, and what the numbers leave out.`;
  document.getElementById("asof").textContent = `Data as of ${apDate(builtAt)}. Updated every morning from the city’s permit records.`;

  const stat = (n, label) => `<div class="stat"><b>${fmt(n)}</b><span>${label}</span></div>`;
  document.getElementById("stats").innerHTML =
    stat(pipeline, "homes in the permit pipeline") +
    stat(building, "under construction") +
    stat(proposed, "proposed in pre-application") +
    stat(middle, `in the pipeline are middle housing (${pipeline ? Math.round((100 * middle) / pipeline) : 0}%)`) +
    stat(projects.length, "projects tracked");

  STAGES.forEach((st, i) => document.body.style.setProperty(`--s${i}`, st.color));

  document.getElementById("legend").innerHTML = STAGES.filter((s) => projects.some((p) => p.status === s.name))
    .map((s) => `<li><i style="background:${s.color}"></i>${esc(s.name)}</li>`)
    .join("");

  // Building type, grouped.
  const typeRows = (list) => list.map((t) => ({ label: t, indent: true, items: projects.filter((p) => typeOf(p) === t) })).filter((r) => r.items.length);
  const middleItems = projects.filter((p) => p.middleHousing);
  const otherItems = projects.filter((p) => OTHER_TYPES.includes(typeOf(p)));
  document.getElementById("chart-type").innerHTML = stackedBars({
    title: "Homes by building type",
    rows: [
      { header: true, label: "Middle housing", items: middleItems },
      ...typeRows(MIDDLE_TYPES),
      { header: true, label: "Other housing", items: otherItems },
      ...typeRows(OTHER_TYPES),
      ...typeRows([UNKNOWN_TYPE]).map((r) => ({ ...r, label: "Type not yet known", indent: false })),
    ],
    note: `Bars count homes; ${plural(missing, "project", "projects")} with no reported unit count are listed as “not reported.” Building types are inferred from permit descriptions and unit counts.`,
  });

  // Council district.
  const districts = [...new Set(projects.map((p) => p.councilDistrict).filter((d) => d != null))].sort();
  document.getElementById("chart-district").innerHTML = stackedBars({
    title: "Homes by City Council district",
    rows: districts.map((d) => ({ label: `District ${d}`, items: projects.filter((p) => p.councilDistrict === d) })),
    note: "Districts are found from each project’s map point.",
  });

  // Neighborhood councils, top 12 by homes.
  const hoods = [...new Set(projects.map((p) => p.neighborhoodCouncil).filter(Boolean))]
    .map((h) => ({ label: h, items: projects.filter((p) => p.neighborhoodCouncil === h) }))
    .sort((a, b) => sumUnits(b.items) - sumUnits(a.items) || b.items.length - a.items.length);
  document.getElementById("chart-hood").innerHTML = stackedBars({
    title: "The 12 neighborhood councils with the most homes",
    rows: hoods.slice(0, 12),
    note: `${hoods.length} of the city’s 29 neighborhood councils have at least one project on the map.`,
  });

  document.getElementById("chart-quarter").innerHTML = quarterColumns();
  document.getElementById("chart-size").innerHTML = sizeTable();

  const unitsLimit = document.getElementById("limit-units");
  if (unitsLimit && missing) {
    unitsLimit.querySelector("strong").textContent = `${plural(missing, "project has", "projects have")} no unit count yet.`;
  }
}

// --------------------------------------------------------------------------
// CSV download, built in the browser from the same data.

function downloadCsv() {
  const cols = [
    ["id", (p) => p.id],
    ["name", (p) => p.name],
    ["address", (p) => p.address],
    ["neighborhood", (p) => p.neighborhood],
    ["neighborhood_council", (p) => p.neighborhoodCouncil],
    ["council_district", (p) => p.councilDistrict],
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
    ["lot_acres", (p) => p.acres ?? ""],
    ["homes_per_acre", (p) => p.homesPerAcre ?? ""],
    ["miles_to_frequent_transit", (p) => p.transitMiles ?? ""],
    ["lat", (p) => p.lat],
    ["lng", (p) => p.lng],
  ];
  Share.downloadText(
    Share.toCsv(projects, cols.map(([label, value]) => ({ label, value }))),
    Share.filename([], "csv", builtAt || new Date()),
    "text/csv"
  );
  Share.toast(`Downloaded ${projects.length} projects`);
}

// --------------------------------------------------------------------------

async function start() {
  try {
    const response = await fetch("projects.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`projects.json returned HTTP ${response.status}`);
    const payload = await response.json();
    if (Array.isArray(payload.stages) && payload.stages.length) STAGES = payload.stages;
    projects = payload.projects || [];
    builtAt = payload.builtAt ? new Date(payload.builtAt) : new Date();
    draw();
    document.getElementById("download").addEventListener("click", downloadCsv);
  } catch (error) {
    document.getElementById("dek").textContent = `Could not load the project data. ${error.message}`;
    console.error(error);
  }
}

start();
