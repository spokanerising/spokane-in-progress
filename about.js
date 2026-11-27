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

function stackedBars({ id, slug, title, rows, note }) {
  if (id) {
    // Each row's group, for the data download ("Middle housing" for a duplex).
    let group = "";
    const tagged = rows.map((r) => { if (r.header) group = r.label; return { ...r, group: r.indent ? group : "" }; });
    CHARTS[id] = { kind: "stacked", slug, title, rows: tagged, note, csv: stackedCsv(tagged) };
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
      <li><i style="background:var(--ink-2)"></i>Middle housing</li>
      <li><i style="background:#b9b2a5"></i>Other housing</li>
    </ul>
    <div class="cols" role="img" aria-label="Projects first filed with the city, by quarter">${cols}</div>
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
  ["type", "district", "hood", "quarter", "size"].forEach(chartTools);

  const unitsLimit = document.getElementById("limit-units");
  if (unitsLimit && missing) {
    unitsLimit.querySelector("strong").textContent = `${plural(missing, "project has", "projects have")} no unit count yet.`;
  }
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
const INK = "#121212", INK2 = "#3a3936", MUTED = "#6b6964", RULE = "#dcd6ca", OTHER = "#b9b2a5", PAPER = "#faf8f3";
const SANS = "'Libre Franklin', Arial, sans-serif";
const SERIF = "Newsreader, Georgia, serif";

const measurer = document.createElement("canvas").getContext("2d");
function textWidth(text, size, weight = 400, family = SANS) {
  measurer.font = `${weight} ${size}px ${family}`;
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
const t = (x, y, text, { size = 16, weight = 400, fill = INK, anchor = "start", family = SANS, style = "" } = {}) =>
  `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" font-family="${esc(family)}" font-size="${size}" font-weight="${weight}"${style ? ` font-style="${style}"` : ""} fill="${fill}" text-anchor="${anchor}">${esc(text)}</text>`;

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
  y += 36;
  parts.push(t(PAD, y, "Spokane ", { size: 22, weight: 600, family: SERIF }));
  parts.push(t(PAD + textWidth("Spokane ", 22, 600, SERIF), y, "in Progress", { size: 22, weight: 500, family: SERIF, style: "italic" }));
  parts.push(t(SVG_W - PAD, y, "PROJECTS.SPOKANERISING.COM", { size: 15, weight: 600, fill: INK2, anchor: "end" }));
  const h = Math.ceil(y + PAD - 8);
  return { h, body: parts.join("") };
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
      parts.push(t(PAD + (r.indent ? 18 : 0), rowY + 19, r.label, { size: 18 }));
      let x = PAD + labelW;
      STAGES.forEach((s) => {
        const n = sumUnits(r.items.filter((p) => p.status === s.name));
        if (!n) return;
        const w = Math.max(2, (barW * n) / max);
        parts.push(`<rect x="${x.toFixed(1)}" y="${rowY + 2}" width="${w.toFixed(1)}" height="22" fill="${s.color}"/>`);
        x += w + 2;
      });
      const missing = r.items.filter((p) => !(p.units > 0)).length;
      parts.push(t(x + 8, rowY + 19, fmt(sumUnits(r.items)), { size: 17, weight: 700 }));
      if (missing) {
        parts.push(t(x + 14 + textWidth(fmt(sumUnits(r.items)), 17, 700), rowY + 19, `+${missing} not reported`, { size: 14, fill: MUTED }));
      }
      parts.push(t(SVG_W - PAD, rowY + 19, plural(r.items.length, "project", "projects"), { size: 15, fill: MUTED, anchor: "end" }));
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
    y = legendRow(parts, y, [{ label: "Middle housing", color: INK2, square: true }, { label: "Other housing", color: OTHER, square: true }]) + 22;
    const base = y + chartH;
    spec.cols.forEach((c, i) => {
      const x = PAD + i * (colW + gap);
      const bw = Math.min(colW, 64), bx = x + (colW - bw) / 2;
      const h = (chartH * c.projects) / max, hm = c.projects ? (h * c.middle) / c.projects : 0;
      const op = c.partial ? ' opacity="0.45"' : "";
      if (h) {
        parts.push(`<rect x="${bx.toFixed(1)}" y="${(base - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${(h - hm).toFixed(1)}" fill="${OTHER}"${op}/>`);
        parts.push(`<rect x="${bx.toFixed(1)}" y="${(base - hm).toFixed(1)}" width="${bw.toFixed(1)}" height="${hm.toFixed(1)}" fill="${INK2}"${op}/>`);
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
      if (w > 0) parts.push(`<rect x="${cols[3]}" y="${y - 16}" width="${w.toFixed(1)}" height="18" fill="${INK2}"/>`);
      if (r.homes) parts.push(t(cols[3] + w + 10, y, `${Math.round(100 * r.share)}%`, { size: 16, fill: INK2 }));
      parts.push(`<rect x="${PAD}" y="${y + 14}" width="${SVG_W - 2 * PAD}" height="1" fill="${RULE}"/>`);
    });
    return y + 20;
  });
}

const SVG_FOR = { stacked: stackedSvg, quarter: quarterSvg, size: sizeSvg };

// The site's typefaces, embedded so a drawn image uses them. Fetched once
// from Google Fonts (latin subsets only); if that fails the image still
// draws, in Georgia and Arial.
let fontCss = null;
function embeddedFonts() {
  // Never let a slow font server hold up a download: 4 seconds, then without.
  return Promise.race([loadEmbeddedFonts(), new Promise((r) => setTimeout(() => r(""), 4000))]);
}
async function loadEmbeddedFonts() {
  if (fontCss !== null) return fontCss;
  fontCss = "";
  try {
    const href = [...document.querySelectorAll('link[rel="stylesheet"]')].map((l) => l.href).find((h) => h.includes("fonts.googleapis.com"));
    if (!href) return fontCss;
    const css = await (await fetch(href)).text();
    const blocks = css.split("/*").filter((b) => b.startsWith(" latin */"));
    const faces = await Promise.all(blocks.map(async (b) => {
      const url = (/url\((https:[^)]+)\)/.exec(b) || [])[1];
      if (!url) return "";
      const buf = await (await fetch(url)).arrayBuffer();
      let bin = "";
      new Uint8Array(buf).forEach((c) => { bin += String.fromCharCode(c); });
      return b.slice(b.indexOf("@font-face")).replace(url, `data:font/woff2;base64,${btoa(bin)}`);
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
    `<rect width="100%" height="100%" fill="${PAPER}"/>${body}</svg>`;
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
  p.innerHTML = `Download <button type="button" data-format="png">image</button> · <button type="button" data-format="svg">SVG</button> · <button type="button" data-format="csv">data</button>`;
  p.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-format]");
    if (b && b.getAttribute("aria-busy") !== "true") downloadChart(id, b.dataset.format, b);
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
