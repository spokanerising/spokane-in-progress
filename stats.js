// Spokane in Progress — Stats page (stats.html).
// Reads the same projects.json as the map and draws plain HTML charts, so the
// numbers here always match the map's. No chart library.

const STAGE_ORDER = ["Pre-Application", "Applied", "Approved", "Under Construction", "Complete", "Stalled"];
const PIPELINE = ["Applied", "Approved", "Under Construction"];

const MIDDLE_TYPES = ["Duplex", "Triplex or fourplex", "Fiveplex or sixplex", "Townhomes", "Cottage housing"];
const OTHER_TYPES = ["Apartments", "House + ADU", "Conversion or addition", "Senior & group living"];
const UNKNOWN_TYPE = "Not yet known";
// Same order as the map's zoning filter (app.js).
const ZONE_GROUPS = ["Residential", "Centers & Corridors", "Commercial & mixed use", "Downtown", "Industrial", "Other"];

const SIZES = [
  { label: "2–4 homes", test: (u) => u >= 2 && u <= 4 },
  { label: "5–19 homes", test: (u) => u >= 5 && u <= 19 },
  { label: "20–99 homes", test: (u) => u >= 20 && u <= 99 },
  { label: "100 or more homes", test: (u) => u >= 100 },
  { label: "Size not reported", test: (u) => !(u > 0) },
];

const AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];

// Replaced by the stages in projects.json once it loads; until then, the brand.css copies.
let STAGES = STAGE_ORDER.map((name, i) => ({ name, color: getComputedStyle(document.documentElement).getPropertyValue(`--stage-${i}`).trim() }));
let projects = [];
let builtAt = null;

// --------------------------------------------------------------------------

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString("en-US");
const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;
const units = (p) => (p.units > 0 ? p.units : 0);
const sumUnits = (list) => list.reduce((s, p) => s + units(p), 0);
// An unknown stage falls back to the last stage color (Stalled's gray), as on the map.
const colorOf = (stage) => (STAGES.find((s) => s.name === stage) || {}).color || getComputedStyle(document.documentElement).getPropertyValue("--stage-5").trim();
const typeOf = (p) => p.buildingType || UNKNOWN_TYPE;
const firstFiled = (p) => ((p.permits || []).map((x) => x.opened).filter(Boolean).sort()[0] || "");

function apDate(value) {
  if (!value) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(value);
  return isNaN(d) ? String(value) : `${AP_MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

// A chart's numbers as a table for screen readers; the drawing beside it is
// marked aria-hidden. (WCAG 1.1.1: a picture's text alternative carries its data.)
function srTable(caption, head, rows) {
  // Wrapped: a table ignores the 1px width of .visually-hidden and would widen the page.
  return `<div class="visually-hidden"><table><caption>${esc(caption)}</caption>
    <thead><tr>${head.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr><th scope="row">${esc(r[0])}</th>${r.slice(1).map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

const sourceLine = () =>
  `Source: City of Spokane permit records, compiled by Spokane in Progress. Data as of ${apDate(builtAt)}.`;

// --------------------------------------------------------------------------
// Stacked horizontal bars: one row per group, segments by stage, homes.

function stackedBars({ id, slug, title, rows, note, counts = true }) {
  if (id) {
    // Each row's group, for the data download ("Middle housing" for a duplex).
    let group = "";
    const tagged = rows.map((r) => { if (r.header) group = r.label; return { ...r, group: r.indent ? group : "" }; });
    CHARTS[id] = { kind: "stacked", slug, title, rows: tagged, note, counts, csv: stackedCsv(tagged) };
  }
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
      const split = STAGES.map((st) => [st.name, sumUnits(r.items.filter((p) => p.status === st.name))]).filter(([, n]) => n)
        .map(([name, n]) => `${fmt(n)} ${name.toLowerCase()}`).join(", ");
      const missing = r.items.filter((p) => !(p.units > 0)).length;
      const label = r.href ? `<a href="${esc(r.href)}">${esc(r.label)}</a>` : esc(r.label);
      return `<div class="bars__row${r.indent ? " bars__row--indent" : ""}${counts ? "" : " bars__row--nocount"}">
          <div class="bars__label">${label}${r.sub ? `<small>${esc(r.sub)}</small>` : ""}</div>
          <div class="bars__track">${segs}<span class="bars__value"><b>${fmt(total)}</b><span class="visually-hidden"> ${total === 1 ? "home" : "homes"}${split ? ` (${split})` : ""}</span>${missing ? `<small> +${missing} not reported</small>` : ""}</span></div>
          ${counts ? `<div class="bars__n">${plural(r.items.length, "project", "projects")}</div>` : ""}
        </div>`;
    })
    .join("");
  return `<figcaption class="chart__title">${esc(title)}</figcaption>
    <div class="bars">${body}</div>
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
  const missingDates = projects.length - dated.length;
  CHARTS.quarter = {
    kind: "quarter", slug: "filings-by-quarter",
    title: "Projects first filed with the city, by quarter",
    note: `Counts projects still on the map, by the date of their earliest city record (a pre-development meeting counts). The city’s public permit map keeps about three years of records; the first and last quarters shown are partial (lighter), and ${plural(missingDates, "project has", "projects have")} no filing date.`,
    cols: keys.map((k) => {
      const [yy, qq] = k.split("-");
      const list = byQ[k];
      return { key: k, q: qq, year: yy, showYear: qq === "Q1" || k === keys[0], projects: list.length,
               middle: list.filter((p) => p.middleHousing).length, homes: sumUnits(list), partial: k === last || k === partialFirst };
    }),
  };
  CHARTS.quarter.csv = { rows: CHARTS.quarter.cols, columns: [
    { label: "quarter", value: (c) => c.key }, { label: "projects", value: (c) => c.projects },
    { label: "middle_housing_projects", value: (c) => c.middle }, { label: "homes", value: (c) => c.homes },
    { label: "partial_quarter", value: (c) => (c.partial ? "yes" : "no") }] };
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
      <li><i style="background:var(--chart)"></i>Middle housing</li>
      <li><i style="background:var(--other)"></i>Other housing</li>
    </ul>
    <div class="cols" aria-hidden="true">${cols}</div>
    ${srTable("Projects first filed with the city, by quarter", ["Quarter", "Projects", "Middle housing projects", "Homes"],
      CHARTS.quarter.cols.map((c) => [`${c.q} ${c.year}${c.partial ? " (partial)" : ""}`, fmt(c.projects), fmt(c.middle), fmt(c.homes)]))}
    <p class="source">Note: Counts projects still on the map, by the date of their earliest city record (a pre-development meeting counts). The city’s public permit map keeps about three years of records; the first and last quarters shown are partial, and ${plural(projects.length - dated.length, "project has", "projects have")} no filing date. ${esc(sourceLine())}</p>`;
}

function sizeTable() {
  const total = sumUnits(projects);
  CHARTS.size = {
    kind: "size", slug: "by-size", title: "Projects and homes by project size",
    note: "Size counts every home in a project, across all its buildings, at every stage.",
    rows: SIZES.map((s) => {
      const list = projects.filter((p) => s.test(p.units));
      const homes = sumUnits(list);
      return { label: s.label, projects: list.length, homes, share: total ? homes / total : 0 };
    }),
  };
  CHARTS.size.csv = { rows: CHARTS.size.rows, columns: [
    { label: "size", value: (r) => r.label }, { label: "projects", value: (r) => r.projects },
    { label: "homes", value: (r) => r.homes }, { label: "share_of_homes", value: (r) => r.share.toFixed(4) }] };
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

// "Residential zones hold 49% of the homes; commercial and mixed-use zones, 34%"
function zoneTitle(groupHomes, total) {
  const pct = (n) => Math.round((100 * n) / Math.max(1, total));
  const name = (g) => g.replace(" & ", " and ").replace(/^[A-Z]/, (c) => c).replace(/(?<=.)\b([A-Z])/g, (c) => c.toLowerCase());
  const [a, b] = groupHomes.filter(([, n]) => n > 0);
  if (!a) return "Homes by zoning";
  if (pct(a[1]) > 50 || !b) return `${pct(a[1])}% of the homes are in ${name(a[0]).toLowerCase()} zones`;
  return `${name(a[0])} zones hold ${pct(a[1])}% of the homes; ${name(b[0]).toLowerCase()} zones, ${pct(b[1])}%`;
}

// --------------------------------------------------------------------------
// Density: one dot per project on a log scale of homes per acre.

const DENSITY_TICKS = [2, 5, 10, 20, 50, 100, 200, 500, 1000];

function densityScale(values) {
  const lo = Math.min(...values), hi = Math.max(...values);
  const min = [...DENSITY_TICKS].reverse().find((v) => v <= lo) || DENSITY_TICKS[0];
  const max = DENSITY_TICKS.find((v) => v >= hi) || DENSITY_TICKS[DENSITY_TICKS.length - 1];
  const a = Math.log(min), b = Math.log(max);
  return { min, max, x: (v) => (Math.log(Math.min(Math.max(v, min), max)) - a) / (b - a),
           ticks: DENSITY_TICKS.filter((v) => v >= min && v <= max) };
}

// Dots that would overlap stack up and down from the center line.
function beeswarm(items, x, binW) {
  const bins = new Map();
  return items.map((it) => {
    const pos = x(it.value);
    const k = Math.round(pos / binW);
    const n = bins.get(k) || 0;
    bins.set(k, n + 1);
    return { ...it, pos, row: n === 0 ? 0 : (n % 2 ? 1 : -1) * Math.ceil(n / 2) };
  });
}

const median = (list) => {
  const v = [...list].sort((a, b) => a - b), m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
};

function densityStrip() {
  const list = projects.filter((p) => Number.isFinite(p.homesPerAcre) && p.homesPerAcre > 0)
    .sort((a, b) => a.homesPerAcre - b.homesPerAcre);
  if (list.length < 5) return "";
  const values = list.map((p) => p.homesPerAcre);
  const sc = densityScale(values);
  const med = median(values);
  const round = (v) => (v >= 20 ? Math.round(v) : Math.round(v * 10) / 10);
  const title = `Half of these projects build fewer than ${fmt(round(med))} homes per acre`;
  const note = `One dot per project with both a unit count and a known site size (${plural(list.length, "project", "projects")} of ${fmt(projects.length)}). Site size is the combined area of the project’s county parcels. The scale is logarithmic: each step is a multiple, not an equal amount.`;
  const dots = beeswarm(list.map((p) => ({ p, value: p.homesPerAcre })), sc.x, 0.012);
  CHARTS.density = { kind: "strip", slug: "homes-per-acre", title, note, dots, scale: sc, median: med,
    csv: { rows: list, columns: [
      { label: "project", value: (p) => p.name }, { label: "id", value: (p) => p.id },
      { label: "stage", value: (p) => p.status }, { label: "homes", value: (p) => p.units },
      { label: "acres", value: (p) => p.acres }, { label: "homes_per_acre", value: (p) => p.homesPerAcre },
      { label: "zone", value: (p) => p.zoneBase || "" }] } };
  const rows = Math.max(1, ...dots.map((d) => Math.abs(d.row)));
  const step = 9;
  const height = Math.max(60, (2 * rows + 1) * step + 12);
  const pts = dots.map((d) => `<a class="strip__dot" href="p/${encodeURIComponent(d.p.id)}/" tabindex="-1" style="left:${(100 * d.pos).toFixed(2)}%;top:calc(50% + ${d.row * step}px);background:${colorOf(d.p.status)}" title="${esc(d.p.name)}: ${fmt(round(d.value))} homes per acre (${fmt(d.p.units)} homes on ${d.p.acres} acres)"></a>`).join("");
  // The same projects as a list of links: the way in for keyboards and screen
  // readers, and a full-size target for every dot (WCAG 2.5.8).
  const listing = `<details class="explain strip__list"><summary>All ${plural(list.length, "project", "projects")}, by homes per acre</summary>
    <ol>${list.map((p) => `<li><a href="p/${encodeURIComponent(p.id)}/">${esc(p.name)}</a> <span>${fmt(round(p.homesPerAcre))} homes per acre · ${plural(p.units, "home", "homes")} on ${fmt(p.acres)} acres</span></li>`).join("")}</ol>
  </details>`;
  const ticks = sc.ticks.map((v) => `<span class="strip__tick" style="left:${(100 * sc.x(v)).toFixed(2)}%">${fmt(v)}</span>`).join("");
  return `<figcaption class="chart__title">${esc(title)}</figcaption>
    <p class="visually-hidden">Median: ${fmt(round(med))} homes per acre, across ${plural(list.length, "project", "projects")}, from ${fmt(round(values[0]))} to ${fmt(round(values[values.length - 1]))}. The projects are listed below.</p>
    <div class="strip" aria-hidden="true">
      <div class="strip__plot" style="height:${height}px">
        <span class="strip__median" style="left:${(100 * sc.x(med)).toFixed(2)}%"><span>Median ${fmt(round(med))}</span></span>
        ${pts}
      </div>
      <div class="strip__axis">${ticks}</div>
      <p class="strip__unit">Homes per acre</p>
    </div>
    ${listing}
    <p class="source">Note: ${esc(note)} ${esc(sourceLine())}</p>`;
}

function stripSvg(spec) {
  const w = SVG_W - 2 * PAD - 20, x0 = PAD + 10;
  const rows = Math.max(1, ...spec.dots.map((d) => Math.abs(d.row)));
  const step = 15, r = 6.5;
  const plotH = Math.max(90, (2 * rows + 1) * step + 30);
  return frame(spec, (parts, y) => {
    const present = STAGES.filter((s) => spec.dots.some((d) => d.p.status === s.name));
    y = legendRow(parts, y, present.map((s) => ({ label: s.name, color: s.color }))) + 16;
    const mid = y + plotH / 2;
    const mx = x0 + w * spec.scale.x(spec.median);
    parts.push(`<rect x="${mx.toFixed(1)}" y="${y}" width="1.5" height="${plotH}" fill="${INK}"/>`);
    parts.push(t(mx + 6, y + 14, `Median ${fmt(Math.round(spec.median))}`, { size: 15, weight: 600 }));
    spec.dots.forEach((d) => {
      parts.push(`<circle cx="${(x0 + w * d.pos).toFixed(1)}" cy="${(mid + d.row * step).toFixed(1)}" r="${r}" fill="${colorOf(d.p.status)}" stroke="${PAPER}" stroke-width="1"/>`);
    });
    const base = y + plotH;
    parts.push(`<rect x="${PAD}" y="${base}" width="${SVG_W - 2 * PAD}" height="1.5" fill="${INK}"/>`);
    spec.scale.ticks.forEach((v) => {
      const tx = x0 + w * spec.scale.x(v);
      parts.push(`<rect x="${tx.toFixed(1)}" y="${base}" width="1" height="7" fill="${INK}"/>`);
      parts.push(t(tx, base + 26, fmt(v), { size: 15, fill: MUTED, anchor: "middle" }));
    });
    parts.push(t(x0 + w / 2, base + 50, "Homes per acre", { size: 15, fill: MUTED, anchor: "middle" }));
    return base + 56;
  });
}

// --------------------------------------------------------------------------
// Middle housing: its share of projects against its share of homes.

function middleShare() {
  const counted = projects.filter((p) => p.units > 0);
  if (!counted.length) return "";
  const mid = counted.filter((p) => p.middleHousing);
  const shareP = mid.length / counted.length, shareH = sumUnits(mid) / Math.max(1, sumUnits(counted));
  const pct = (v) => Math.round(100 * v);
  const title = `Middle housing is ${pct(shareP)}% of projects but ${pct(shareH)}% of homes`;
  const note = `Counts the ${plural(counted.length, "project", "projects")} with a unit count, at every stage. Middle housing follows Washington’s definition: duplexes through sixplexes, townhouses, stacked flats, courtyard apartments and cottage housing.`;
  const rows = [
    { label: "Share of projects", part: mid.length, whole: counted.length, share: shareP, unit: ["project", "projects"] },
    { label: "Share of homes", part: sumUnits(mid), whole: sumUnits(counted), share: shareH, unit: ["home", "homes"] },
  ];
  CHARTS.middle = { kind: "share", slug: "middle-housing-share", title, note, rows,
    csv: { rows, columns: [
      { label: "measure", value: (r) => r.label }, { label: "middle_housing", value: (r) => r.part },
      { label: "total", value: (r) => r.whole }, { label: "share", value: (r) => r.share.toFixed(4) }] } };
  const body = rows.map((r) => `<div class="share__row">
      <div class="share__label">${esc(r.label)}</div>
      <div class="share__track"><span class="share__part" style="width:${(100 * r.share).toFixed(1)}%"></span></div>
      <div class="share__value"><b>${pct(r.share)}%</b> <small>${fmt(r.part)} of ${plural(r.whole, ...r.unit)}</small></div>
    </div>`).join("");
  return `<figcaption class="chart__title">${esc(title)}</figcaption>
    <ul class="legend legend--small">
      <li><i style="background:var(--chart)"></i>Middle housing</li>
      <li><i style="background:var(--other)"></i>Other housing</li>
    </ul>
    <div class="share">${body}</div>
    <p class="source">Note: ${esc(note)} ${esc(sourceLine())}</p>`;
}

function shareSvg(spec) {
  const labelW = 260, valueW = 300, barW = SVG_W - 2 * PAD - labelW - valueW;
  return frame(spec, (parts, y) => {
    y = legendRow(parts, y, [{ label: "Middle housing", color: CHART, square: true }, { label: "Other housing", color: OTHER, square: true }]) + 12;
    spec.rows.forEach((r) => {
      parts.push(t(PAD, y + 24, r.label, { size: 18 }));
      const x = PAD + labelW, w = barW * r.share;
      parts.push(`<rect x="${x}" y="${y + 4}" width="${barW}" height="28" fill="${OTHER}"/>`);
      parts.push(`<rect x="${x}" y="${y + 4}" width="${w.toFixed(1)}" height="28" fill="${CHART}"/>`);
      parts.push(t(x + barW + 14, y + 25, `${Math.round(100 * r.share)}%`, { size: 20, weight: 700 }));
      parts.push(t(x + barW + 70, y + 25, `${fmt(r.part)} of ${plural(r.whole, ...r.unit)}`, { size: 15, fill: MUTED }));
      y += 46;
    });
    return y;
  });
}

// --------------------------------------------------------------------------
// The pipeline over time, from the daily log (data/pipeline-history.csv).
// Hidden until the log covers HISTORY_MIN_DAYS, so it never shows a stub.

const HISTORY_MIN_DAYS = 30;
const HISTORY_SERIES = [
  { key: "pipeline", label: "In the permit process", value: (r) => r.applied_homes + r.approved_homes + r.under_construction_homes, color: "ink" },
  { key: "building", label: "Under construction", stage: "Under Construction", value: (r) => r.under_construction_homes },
  { key: "proposed", label: "Proposed (pre-application)", stage: "Pre-Application", value: (r) => r.pre_application_homes },
];

function parseHistory(text) {
  const lines = text.trim().split(/\r?\n/);
  const head = lines.shift().split(",");
  return lines.map((line) => {
    const cells = line.split(",");
    const row = {};
    head.forEach((h, i) => { row[h] = h === "date" ? cells[i] : Number(cells[i]) || 0; });
    return row;
  }).filter((r) => /^\d{4}-\d{2}-\d{2}$/.test(r.date)).sort((a, b) => (a.date < b.date ? -1 : 1));
}

const seriesColor = (s) => (s.stage ? colorOf(s.stage) : "var(--ink)");

async function historyLine() {
  const fig = document.getElementById("chart-history");
  if (!fig) return;
  let rows = [];
  try {
    const res = await fetch("data/pipeline-history.csv", { cache: "no-store" });
    if (res.ok) rows = parseHistory(await res.text());
  } catch (error) { /* no log, no chart */ }
  const days = rows.length ? (new Date(rows[rows.length - 1].date) - new Date(rows[0].date)) / 864e5 + 1 : 0;
  if (days < HISTORY_MIN_DAYS) { fig.hidden = true; return; }
  const first = rows[0], last = rows[rows.length - 1];
  const p0 = HISTORY_SERIES[0].value(first), p1 = HISTORY_SERIES[0].value(last);
  const change = p1 - p0;
  const title = change === 0
    ? `Homes in the permit process have held at ${fmt(p1)} since ${apDate(first.date)}`
    : `Homes in the permit process have ${change > 0 ? "risen" : "fallen"} by ${fmt(Math.abs(change))} since ${apDate(first.date)}`;
  const note = "Counted each morning from the map. Homes without a reported unit count aren’t included. A jump can mean a large project changed stage or was added, or a change in how the map reads the city’s records.";
  CHARTS.history = { kind: "line", slug: "pipeline-over-time", title, note, rows,
    csv: { rows, columns: [{ label: "date", value: (r) => r.date },
      ...HISTORY_SERIES.map((s) => ({ label: `homes_${s.key}`, value: (r) => s.value(r) }))] } };
  fig.hidden = false;
  fig.innerHTML = `<figcaption class="chart__title">${esc(title)}</figcaption>
    <ul class="legend legend--small">${HISTORY_SERIES.map((s) => `<li><i style="background:${seriesColor(s)}"></i>${esc(s.label)}</li>`).join("")}</ul>
    <div class="linechart" aria-hidden="true">${lineSvgInner(rows, 640, 240, 13, true)}</div>
    ${srTable(`${title} (weekly)`, ["Date", ...HISTORY_SERIES.map((x) => x.label)],
      rows.filter((r, i) => i % 7 === 0 || i === rows.length - 1).map((r) => [apDate(r.date), ...HISTORY_SERIES.map((x) => fmt(x.value(r)))]))}
    <p class="source">Note: ${esc(note)} ${esc(sourceLine())}</p>`;
  chartTools("history");
}

// The plot itself: shared by the page (viewBox scales it) and the download.
function lineSvgInner(rows, w, h, size, standalone) {
  const left = 52, right = 16, top = 10, bottom = 28;
  const pw = w - left - right, ph = h - top - bottom;
  const max = Math.max(10, ...rows.flatMap((r) => HISTORY_SERIES.map((s) => s.value(r))));
  const stepY = [10, 20, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000].find((v) => max / v <= 5) || 10000;
  const yMax = Math.ceil(max / stepY) * stepY;
  const t0 = +new Date(rows[0].date), t1 = Math.max(t0 + 864e5, +new Date(rows[rows.length - 1].date));
  const X = (d) => left + (pw * (+new Date(d) - t0)) / (t1 - t0);
  const Y = (v) => top + ph - (ph * v) / yMax;
  const parts = [];
  for (let v = 0; v <= yMax; v += stepY) {
    parts.push(`<line x1="${left}" x2="${w - right}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="${v ? RULE : INK}" stroke-width="${v ? 1 : 1.5}"/>`);
    parts.push(`<text x="${left - 8}" y="${(Y(v) + size / 3).toFixed(1)}" font-family="${esc(SANS)}" font-size="${size}" fill="${MUTED}" text-anchor="end">${fmt(v)}</text>`);
  }
  // Month ticks.
  const d = new Date(rows[0].date); d.setDate(1); d.setMonth(d.getMonth() + 1);
  for (; +d <= t1; d.setMonth(d.getMonth() + 1)) {
    const iso = d.toISOString().slice(0, 10), x = X(iso);
    const lab = d.getMonth() === 0 ? `${AP_MONTHS[0]} ${d.getFullYear()}` : AP_MONTHS[d.getMonth()];
    parts.push(`<text x="${x.toFixed(1)}" y="${h - 8}" font-family="${esc(SANS)}" font-size="${size}" fill="${MUTED}" text-anchor="middle">${esc(lab)}</text>`);
  }
  HISTORY_SERIES.forEach((s) => {
    const color = s.stage ? colorOf(s.stage) : INK;
    const path = rows.map((r, i) => `${i ? "L" : "M"}${X(r.date).toFixed(1)},${Y(s.value(r)).toFixed(1)}`).join("");
    parts.push(`<path d="${path}" fill="none" stroke="${color}" stroke-width="${s.stage ? 2 : 2.5}" stroke-linejoin="round"/>`);
  });
  const body = parts.join("");
  return standalone ? `<svg viewBox="0 0 ${w} ${h}" width="100%" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${body}</svg>` : body;
}

function lineSvg(spec) {
  return frame(spec, (parts, y) => {
    y = legendRow(parts, y, HISTORY_SERIES.map((s) => ({ label: s.label, color: s.stage ? colorOf(s.stage) : INK, square: true }))) + 8;
    parts.push(`<g transform="translate(${PAD - 10},${y})">${lineSvgInner(spec.rows, SVG_W - 2 * PAD + 10, 380, 16, false)}</g>`);
    return y + 380;
  });
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
    `At least <b>${fmt(pipeline)}</b> homes are working their way through Spokane’s permit process, <b>${fmt(building)}</b> of them under construction. Developers have proposed <b>${fmt(proposed)}</b> more. Here is where they are and what kind of housing they are.`;
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
    id: "type", slug: "by-building-type",
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
    id: "district", slug: "by-council-district",
    title: "Homes by City Council district",
    rows: districts.map((d) => ({ label: `District ${d}`, items: projects.filter((p) => p.councilDistrict === d) })),
    note: "Districts are found from each project’s map point.",
  });

  // Neighborhood councils, top 12 by homes.
  const hoods = [...new Set(projects.map((p) => p.neighborhoodCouncil).filter(Boolean))]
    .map((h) => ({ label: h, items: projects.filter((p) => p.neighborhoodCouncil === h) }))
    .sort((a, b) => sumUnits(b.items) - sumUnits(a.items) || b.items.length - a.items.length);
  document.getElementById("chart-hood").innerHTML = stackedBars({
    id: "hood", slug: "top-neighborhoods",
    title: "The 12 neighborhood councils with the most homes",
    rows: hoods.slice(0, 12),
    note: `${hoods.length} of the city’s 29 neighborhood councils have at least one project on the map.`,
  });

  document.getElementById("chart-quarter").innerHTML = quarterColumns();
  document.getElementById("chart-size").innerHTML = sizeTable();

  // Where things stand: every stage as its own bar.
  const byStage = (name) => projects.filter((p) => p.status === name);
  const permitted = sumUnits([...byStage("Approved"), ...byStage("Under Construction")]);
  const stageRow = (name, label, sub) => ({ label, sub, indent: true, items: byStage(name) });
  const stageRows = [
    { header: true, label: "Only proposed", items: byStage("Pre-Application") },
    stageRow("Pre-Application", "Pre-application", "A meeting with the city, no permit yet"),
    { header: true, label: "In the permit process", items: inStages(PIPELINE) },
    stageRow("Applied", "Applied", "Plans in city review"),
    stageRow("Approved", "Approved", "Permit issued, no sign of work yet"),
    stageRow("Under Construction", "Under construction", "Estimated from trade permits"),
    { header: true, label: "Finished or stopped", items: [...byStage("Complete"), ...byStage("Stalled")] },
    stageRow("Complete", "Complete"),
    stageRow("Stalled", "Stalled"),
  ].filter((r) => r.items.length);
  document.getElementById("chart-stage").innerHTML = stackedBars({
    id: "stage", slug: "by-stage",
    title: `${fmt(permitted)} homes are approved or under construction; ${fmt(proposed)} more are only proposed`,
    rows: stageRows,
    note: "“Complete” undercounts finished housing: projects already done when the map first found them are left off.",
  });

  // The ten largest projects, each linked to its page.
  const biggest = projects.filter((p) => p.units > 0).sort((a, b) => b.units - a.units || a.name.localeCompare(b.name)).slice(0, 10);
  const topShare = sumUnits(projects) ? Math.round((100 * sumUnits(biggest)) / sumUnits(projects)) : 0;
  document.getElementById("chart-top").innerHTML = stackedBars({
    id: "top", slug: "largest-projects",
    title: `The 10 largest projects hold ${topShare}% of the homes on the map`,
    rows: biggest.map((p) => ({ label: p.name, href: `p/${encodeURIComponent(p.id)}/`, sub: p.neighborhood || p.neighborhoodCouncil || "", items: [p] })),
    counts: false,
    note: "Counts every home in a project, at every stage, including proposals.",
  });

  // Zoning, grouped by family, one row per zone.
  const zoned = projects.filter((p) => p.zoneBase);
  const zoneRows = [];
  ZONE_GROUPS.forEach((g) => {
    const inGroup = zoned.filter((p) => (p.zoneGroup || "Other") === g);
    if (!inGroup.length) return;
    zoneRows.push({ header: true, label: g, items: inGroup });
    [...new Set(inGroup.map((p) => p.zoneBase))]
      .map((z) => ({ z, items: inGroup.filter((p) => p.zoneBase === z) }))
      .sort((a, b) => sumUnits(b.items) - sumUnits(a.items) || b.items.length - a.items.length)
      .forEach(({ z, items }) => {
        const name = items[0].zoneName || "";
        zoneRows.push({ label: name && name !== g ? `${z} · ${name}` : z, indent: true, items });
      });
  });
  const groupHomes = ZONE_GROUPS.map((g) => [g, sumUnits(zoned.filter((p) => (p.zoneGroup || "Other") === g))]).sort((a, b) => b[1] - a[1]);
  const zonedHomes = sumUnits(zoned);
  document.getElementById("chart-zone").innerHTML = stackedBars({
    id: "zone", slug: "by-zoning",
    title: zoneTitle(groupHomes, zonedHomes),
    rows: zoneRows,
    note: "Each project’s zone is the city zoning at its map point. Zone codes are the city’s own; see the Spokane Municipal Code for what each allows.",
  });

  // Distance to frequent transit.
  const nearT = projects.filter((p) => Number.isFinite(p.transitMiles));
  const bands = [
    { label: "Within ¼ mile", test: (m) => m <= 0.25 },
    { label: "¼ to ½ mile", test: (m) => m > 0.25 && m <= 0.5 },
    { label: "½ to 1 mile", test: (m) => m > 0.5 && m <= 1 },
    { label: "More than 1 mile", test: (m) => m > 1 },
  ];
  const halfMile = sumUnits(nearT.filter((p) => p.transitMiles <= 0.5));
  document.getElementById("chart-transit").innerHTML = stackedBars({
    id: "transit", slug: "distance-to-frequent-transit",
    title: `${sumUnits(nearT) ? Math.round((100 * halfMile) / sumUnits(nearT)) : 0}% of the homes are within half a mile of a frequent bus stop`,
    rows: bands.map((b) => ({ label: b.label, items: nearT.filter((p) => b.test(p.transitMiles)) })),
    note: "Straight-line distance from each project’s map point to the nearest stop where at least one route runs every 15 minutes or better, 10 a.m. to 2 p.m. on weekdays, from Spokane Transit’s schedules.",
  });

  document.getElementById("chart-middle").innerHTML = middleShare();
  document.getElementById("chart-density").innerHTML = densityStrip();
  ["stage", "top", "size", "type", "middle", "density", "district", "hood", "zone", "transit", "quarter"].forEach(chartTools);
  historyLine();
}

// --------------------------------------------------------------------------
// Charts as images and data.
//
// Each chart on this page gets "Download: image · SVG · data". The page's
// charts are HTML that rearranges itself on phones, so the downloads are
// drawn separately: a fixed 1200-wide SVG from the same numbers, with the
// chart's title, key, note and source and the site's address, in the site's
// typefaces (embedded, so the PNG doesn't fall back to a system font).
// CHARTS holds what each chart shows; draw() fills it.

const CHARTS = {};
const SVG_W = 1200;
const PAD = 48;
// Colors come from brand.css (written by tools/make_brand.py from brand/brand.json).
const brandColor = (name) => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
const INK = brandColor("ink"), INK2 = brandColor("ink-2"), MUTED = brandColor("muted"), RULE = brandColor("rule"), OTHER = brandColor("other"), PAPER = brandColor("paper"), CHART = brandColor("chart"), ACCENT = brandColor("accent");

// The Spokane Rising logo, fetched once and drawn into downloaded charts.
let LOGO_INNER = "";
const LOGO_SRC = brandColor("logo-src").replace(/^["']|["']$/g, "");
if (LOGO_SRC) {
  fetch(LOGO_SRC).then((r) => (r.ok ? r.text() : "")).then((svg) => {
    LOGO_INNER = svg.trim().replace(/^<svg[^>]*>/, "").replace(/<\/svg>$/, "");
  }).catch(() => {});
}
// Type from brand.css (brand/brand.json), via share.js.
const TYPE = Share.brandFonts();
const SANS = TYPE.sans;

const measurer = document.createElement("canvas").getContext("2d");
function textWidth(text, size, weight = 400, family = SANS, stretchWord = "") {
  measurer.font = `${stretchWord ? stretchWord + " " : ""}${weight} ${size}px ${family}`;
  return measurer.measureText(text).width;
}
function wrap(text, size, maxW, weight = 400) {
  const lines = [];
  let line = "";
  String(text).split(/\s+/).forEach((word) => {
    const next = line ? `${line} ${word}` : word;
    if (line && textWidth(next, size, weight) > maxW) { lines.push(line); line = word; }
    else line = next;
  });
  if (line) lines.push(line);
  return lines;
}
const t = (x, y, text, { size = 16, weight = 400, fill = INK, anchor = "start", family = SANS, style = "", stretch = "" } = {}) =>
  `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" font-family="${esc(family)}" font-size="${size}" font-weight="${weight}"${style ? ` font-style="${style}"` : ""}${stretch ? ` style="font-stretch:${stretch}"` : ""} fill="${fill}" text-anchor="${anchor}">${esc(text)}</text>`;

// Title at the top; note, source and the site's name at the bottom. body()
// draws the chart from y and returns the y where it ends.
function frame(spec, body) {
  let y = PAD + 6;
  const parts = [];
  wrap(spec.title, 30, SVG_W - 2 * PAD, 700).forEach((line) => {
    y += 30;
    parts.push(t(PAD, y, line, { size: 30, weight: 700 }));
    y += 6;
  });
  y += 30;
  y = body(parts, y);
  y += 26;
  const note = `${spec.note ? `Note: ${spec.note} ` : ""}${sourceLine()}`;
  wrap(note, 16, SVG_W - 2 * PAD).forEach((line) => {
    parts.push(t(PAD, y, line, { size: 16, fill: MUTED }));
    y += 22;
  });
  y += 18;
  parts.push(`<rect x="${PAD}" y="${y}" width="${SVG_W - 2 * PAD}" height="1.5" fill="${INK}"/>`);
  y += 40;
  // The logo, then the site's name, as on the site's header.
  let x = PAD;
  if (LOGO_INNER) {
    parts.push(`<svg x="${PAD}" y="${y - 29}" width="38" height="38" viewBox="0 0 1000 1000">${LOGO_INNER}</svg>`);
    x += 50;
  }
  const head = { size: 22, weight: TYPE.displayWeight, family: TYPE.display, stretch: TYPE.displayStretch };
  parts.push(t(x, y, "Spokane ", head));
  parts.push(t(x + textWidth("Spokane ", 22, TYPE.displayWeight, TYPE.display, TYPE.stretchWord), y, "in Progress",
    { ...head, weight: TYPE.emWeight, style: TYPE.emStyle === "normal" ? "" : TYPE.emStyle }));
  parts.push(t(SVG_W - PAD, y, "PROJECTS.SPOKANERISING.COM", { size: 15, weight: 600, fill: INK2, anchor: "end" }));
  const h = Math.ceil(y + PAD - 8);
  return { h, body: parts.join("") };
}

// Shorten a label with an ellipsis so it fits maxW.
function fitText(text, size, maxW, weight = 400) {
  let out = String(text);
  if (textWidth(out, size, weight) <= maxW) return out;
  while (out.length > 1 && textWidth(`${out}…`, size, weight) > maxW) out = out.slice(0, -1);
  return `${out.trimEnd()}…`;
}

function legendRow(parts, y, items) {
  let x = PAD;
  items.forEach(({ label, color, square }) => {
    parts.push(square
      ? `<rect x="${x}" y="${y - 12}" width="13" height="13" fill="${color}"/>`
      : `<circle cx="${x + 6.5}" cy="${y - 5.5}" r="6.5" fill="${color}"/>`);
    parts.push(t(x + 20, y, label, { size: 17, fill: INK2 }));
    x += 20 + textWidth(label, 17) + 26;
  });
  return y + 26;
}

function stackedSvg(spec) {
  const labelW = 300, countW = 140, valueW = 150;
  const barW = SVG_W - 2 * PAD - labelW - countW - valueW;
  const plain = spec.rows.filter((r) => !r.header);
  const max = Math.max(1, ...plain.map((r) => sumUnits(r.items)));
  return frame(spec, (parts, y) => {
    const present = STAGES.filter((s) => spec.rows.some((r) => r.items.some((p) => p.status === s.name)));
    y = legendRow(parts, y, present.map((s) => ({ label: s.name, color: s.color }))) + 8;
    spec.rows.forEach((r) => {
      if (r.header) {
        y += 14;
        parts.push(t(PAD, y + 14, r.label.toUpperCase(), { size: 14, weight: 700, fill: MUTED }));
        parts.push(t(PAD + textWidth(r.label.toUpperCase(), 14, 700) + 12, y + 14,
          `${plural(sumUnits(r.items), "home", "homes")} · ${plural(r.items.length, "project", "projects")}`, { size: 14, fill: MUTED }));
        y += 28;
        return;
      }
      const rowY = y;
      parts.push(t(PAD + (r.indent ? 18 : 0), rowY + 19, fitText(r.label, 18, labelW - 16 - (r.indent ? 18 : 0)), { size: 18 }));
      let x = PAD + labelW;
      STAGES.forEach((s) => {
        const n = sumUnits(r.items.filter((p) => p.status === s.name));
        if (!n) return;
        const w = Math.max(2, (barW * n) / max);
        parts.push(`<rect x="${x.toFixed(1)}" y="${rowY + 2}" width="${w.toFixed(1)}" height="22" fill="${s.color}"/>`);
        x += w + 2;
      });
      const split = STAGES.map((st) => [st.name, sumUnits(r.items.filter((p) => p.status === st.name))]).filter(([, n]) => n)
        .map(([name, n]) => `${fmt(n)} ${name.toLowerCase()}`).join(", ");
      const missing = r.items.filter((p) => !(p.units > 0)).length;
      parts.push(t(x + 8, rowY + 19, fmt(sumUnits(r.items)), { size: 17, weight: 700 }));
      if (missing) {
        parts.push(t(x + 14 + textWidth(fmt(sumUnits(r.items)), 17, 700), rowY + 19, `+${missing} not reported`, { size: 14, fill: MUTED }));
      }
      if (spec.counts !== false) parts.push(t(SVG_W - PAD, rowY + 19, plural(r.items.length, "project", "projects"), { size: 15, fill: MUTED, anchor: "end" }));
      y += 34;
    });
    return y;
  });
}

function quarterSvg(spec) {
  const chartH = 300, n = spec.cols.length;
  const gap = 6, colW = (SVG_W - 2 * PAD - gap * (n - 1)) / n;
  const max = Math.max(1, ...spec.cols.map((c) => c.projects));
  return frame(spec, (parts, y) => {
    y = legendRow(parts, y, [{ label: "Middle housing", color: CHART, square: true }, { label: "Other housing", color: OTHER, square: true }]) + 22;
    const base = y + chartH;
    spec.cols.forEach((c, i) => {
      const x = PAD + i * (colW + gap);
      const bw = Math.min(colW, 64), bx = x + (colW - bw) / 2;
      const h = (chartH * c.projects) / max, hm = c.projects ? (h * c.middle) / c.projects : 0;
      const op = c.partial ? ' opacity="0.45"' : "";
      if (h) {
        parts.push(`<rect x="${bx.toFixed(1)}" y="${(base - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${(h - hm).toFixed(1)}" fill="${OTHER}"${op}/>`);
        parts.push(`<rect x="${bx.toFixed(1)}" y="${(base - hm).toFixed(1)}" width="${bw.toFixed(1)}" height="${hm.toFixed(1)}" fill="${CHART}"${op}/>`);
        parts.push(t(x + colW / 2, base - h - 8, String(c.projects), { size: 16, weight: 600, anchor: "middle" }));
      }
      parts.push(t(x + colW / 2, base + 24, c.q, { size: 15, fill: MUTED, anchor: "middle" }));
      if (c.showYear) parts.push(t(x + colW / 2, base + 44, c.year, { size: 15, fill: MUTED, anchor: "middle" }));
    });
    parts.push(`<rect x="${PAD}" y="${base}" width="${SVG_W - 2 * PAD}" height="1.5" fill="${INK}"/>`);
    return base + 52;
  });
}

function sizeSvg(spec) {
  const cols = [PAD, PAD + 420, PAD + 590, PAD + 760];
  return frame(spec, (parts, y) => {
    ["Size", "Projects", "Homes", "Share of homes"].forEach((h, i) =>
      parts.push(t(cols[i] + (i === 1 || i === 2 ? 110 : 0), y + 14, h.toUpperCase(), { size: 14, weight: 700, fill: MUTED, anchor: i === 1 || i === 2 ? "end" : "start" })));
    y += 26;
    parts.push(`<rect x="${PAD}" y="${y}" width="${SVG_W - 2 * PAD}" height="1.5" fill="${INK}"/>`);
    spec.rows.forEach((r) => {
      y += 40;
      parts.push(t(cols[0], y, r.label, { size: 18 }));
      parts.push(t(cols[1] + 110, y, fmt(r.projects), { size: 18, anchor: "end" }));
      parts.push(t(cols[2] + 110, y, r.homes ? fmt(r.homes) : "–", { size: 18, anchor: "end" }));
      const w = (SVG_W - PAD - cols[3] - 70) * r.share;
      if (w > 0) parts.push(`<rect x="${cols[3]}" y="${y - 16}" width="${w.toFixed(1)}" height="18" fill="${CHART}"/>`);
      if (r.homes) parts.push(t(cols[3] + w + 10, y, `${Math.round(100 * r.share)}%`, { size: 16, fill: INK2 }));
      parts.push(`<rect x="${PAD}" y="${y + 14}" width="${SVG_W - 2 * PAD}" height="1" fill="${RULE}"/>`);
    });
    return y + 20;
  });
}

const SVG_FOR = { stacked: stackedSvg, quarter: quarterSvg, size: sizeSvg, strip: stripSvg, share: shareSvg, line: lineSvg };

// The site's typefaces, embedded so a drawn image uses them. Read once from
// the site's own copy (vendor/fonts-*/fonts.css, latin files only); if that
// fails the image still draws, in Georgia and Arial.
let fontCss = null;
function embeddedFonts() {
  // Never let a slow download hold up an image: 4 seconds, then without.
  return Promise.race([loadEmbeddedFonts(), new Promise((r) => setTimeout(() => r(""), 4000))]);
}
async function loadEmbeddedFonts() {
  if (fontCss !== null) return fontCss;
  fontCss = "";
  try {
    const href = [...document.querySelectorAll('link[rel="stylesheet"]')].map((l) => l.href).find((h) => /\/fonts\.css$/.test(h));
    if (!href) return fontCss;
    const css = await (await fetch(href)).text();
    const blocks = css.match(/@font-face\s*\{[^}]*\}/g) || [];
    const faces = await Promise.all(blocks.map(async (b) => {
      const file = (/url\(\.?\/?([^)]+-latin-[a-z]+-normal\.woff2)\)/.exec(b) || [])[1];
      if (!file) return "";  // latin-ext and the rest stay out
      const buf = await (await fetch(new URL(file, href))).arrayBuffer();
      let bin = "";
      new Uint8Array(buf).forEach((c) => { bin += String.fromCharCode(c); });
      const data = `url(data:font/woff2;base64,${btoa(bin)}) format('woff2')`;
      return b.replace(/src:[^;]+;/, `src: ${data};`);
    }));
    fontCss = faces.join("\n");
  } catch (error) {
    fontCss = "";
  }
  return fontCss;
}

function chartSvg(id, fonts = "") {
  const spec = CHARTS[id];
  const { h, body } = SVG_FOR[spec.kind](spec);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${SVG_W}" height="${h}" viewBox="0 0 ${SVG_W} ${h}">` +
    (fonts ? `<style>${fonts}</style>` : "") +
    `<rect width="100%" height="100%" fill="${PAPER}"/><rect width="100%" height="8" fill="${ACCENT}"/>${body}</svg>`;
}

async function chartPng(id) {
  await Share.fontsReady();
  const svg = chartSvg(id, await embeddedFonts());
  const img = new Image();
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error("the chart image didn't draw"));
      setTimeout(() => reject(new Error("the chart image took too long")), 10000);
      img.src = url;
    });
    const scale = 2; // sharp on high-resolution screens and in print
    const canvas = document.createElement("canvas");
    canvas.width = img.width * scale;
    canvas.height = img.height * scale;
    const ctx = canvas.getContext("2d");
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    return canvas;
  } finally {
    URL.revokeObjectURL(url);
  }
}

const chartFile = (id, ext) => Share.filename(["chart", CHARTS[id].slug], ext, builtAt || new Date());

async function downloadChart(id, format, button) {
  try {
    button.setAttribute("aria-busy", "true");
    if (format === "png") {
      await Share.downloadCanvas(await chartPng(id), chartFile(id, "png"), "image/png");
      Share.toast("Chart image saved");
    } else if (format === "svg") {
      Share.downloadText(chartSvg(id), chartFile(id, "svg"), "image/svg+xml");
      Share.toast("Chart SVG saved");
    } else {
      Share.downloadText(Share.toCsv(CHARTS[id].csv.rows, CHARTS[id].csv.columns), chartFile(id, "csv"), "text/csv");
      Share.toast("Chart data saved");
    }
  } catch (error) {
    console.warn(error);
    Share.toast("Couldn’t save the chart. Please try again.");
  } finally {
    button.removeAttribute("aria-busy");
  }
}

function chartTools(id) {
  const fig = document.getElementById(`chart-${id}`);
  if (!fig || !CHARTS[id]) return;
  const p = document.createElement("p");
  p.className = "chart__tools";
  p.innerHTML = `<button type="button" class="iconbtn" aria-label="Download this chart" aria-haspopup="menu" aria-expanded="false">${Share.icon("download")}</button>`;
  const button = p.querySelector("button");
  button.addEventListener("click", () => {
    if (button.getAttribute("aria-busy") === "true") return;
    Share.menu(button, [
      { id: "png", label: "Image (PNG)", note: "For posts and slides", onSelect: () => downloadChart(id, "png", button) },
      { id: "svg", label: "Vector (SVG)", note: "For print and editing", onSelect: () => downloadChart(id, "svg", button) },
      { id: "csv", label: "Data (CSV)", note: "The numbers behind the chart", onSelect: () => downloadChart(id, "csv", button) },
    ], { label: "Download this chart" });
  });
  fig.appendChild(p);
}

// Data behind each kind of chart, as CSV.
function stackedCsv(rows) {
  const stageCols = STAGES.map((s) => ({ label: `homes_${s.name.toLowerCase().replace(/[^a-z]+/g, "_")}`,
    value: (r) => sumUnits(r.items.filter((p) => p.status === s.name)) }));
  return {
    rows,
    columns: [
      { label: "group", value: (r) => (r.header ? r.label : r.group || "") },
      { label: "label", value: (r) => (r.header ? "(all)" : r.label) },
      { label: "homes", value: (r) => sumUnits(r.items) },
      { label: "projects", value: (r) => r.items.length },
      { label: "projects_without_unit_count", value: (r) => r.items.filter((p) => !(p.units > 0)).length },
      ...stageCols,
    ],
  };
}

// --------------------------------------------------------------------------
// CSV download, built in the browser from the same data.

function downloadCsv() {
  // Same columns as the map page's download (see share.js).
  Share.downloadText(Share.projectsCsv(projects), Share.filename([], "csv", builtAt || new Date()), "text/csv");
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
