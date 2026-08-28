// Spokane in Progress — map, list, filters, detail panel.
// Reads data/projects.json, which build.py generates from your sheet.

// Stages are defined in build.py and travel with the data, so this list is only
// a fallback for when the data fails to load. Edit build.py, not this.
let STAGES = [
  { name: "Pre-Application",     color: "#c9a227" },
  { name: "Applied",             color: "#bd7a24" },
  { name: "Approved",            color: "#14666b" },
  { name: "Under Construction",  color: "#a2472f" },
  { name: "Complete",            color: "#4a5d52" },
  { name: "Stalled",             color: "#868c90" },
];

// Roughly the City of Spokane limits. The map opens here.
const CITY_BOUNDS = [[-117.545, 47.598], [-117.300, 47.748]];

const colorOf = (status) =>
  (STAGES.find((s) => s.name === status) || STAGES[STAGES.length - 1]).color;
const indexOf = (status) => STAGES.findIndex((s) => s.name === status);

const state = {
  projects: [],
  hidden: new Set(),
  query: "",
  selected: null,
};

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
  builtStamp: document.getElementById("built-stamp"),
};

let map;

// --------------------------------------------------------------------------

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

const numberWithCommas = (n) => n.toLocaleString("en-US");

function visible() {
  const q = state.query.trim().toLowerCase();
  return state.projects.filter((p) => {
    if (state.hidden.has(p.status)) return false;
    if (!q) return true;
    return [p.name, p.address, p.neighborhood, p.developer, p.architect, p.projectType]
      .join(" ")
      .toLowerCase()
      .includes(q);
  });
}

// --------------------------------------------------------------------------

function drawSpine() {
  const counts = STAGES.map((s) => ({
    ...s,
    n: state.projects.filter((p) => p.status === s.name).length,
  }));

  el.spine.innerHTML = counts
    .filter((s) => s.n > 0)
    .map(
      (s) =>
        `<div class="spine__seg" style="flex-grow:${s.n};background:${s.color}" title="${s.n} ${escapeHtml(s.name.toLowerCase())}"></div>`
    )
    .join("");

  el.spineKey.innerHTML = counts
    .map(
      (s) =>
        `<li><i style="background:${s.color}"></i><b>${s.n}</b> ${escapeHtml(s.name.toLowerCase())}</li>`
    )
    .join("");
}

function drawChips() {
  el.chips.innerHTML = STAGES.map(
    (s) =>
      `<button class="chip" type="button" aria-pressed="true" data-status="${escapeHtml(s.name)}" style="color:${s.color}">
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

function drawCards(list) {
  el.cards.innerHTML = list
    .map((p) => {
      const facts = [
        p.projectType,
        p.units ? `${numberWithCommas(p.units)} units` : null,
        p.stories ? `${p.stories} stories` : null,
      ].filter(Boolean);

      return `<li>
        <button class="card" data-id="${escapeHtml(p.id)}" style="border-left-color:${colorOf(p.status)}">
          <div class="card__stage" style="color:${colorOf(p.status)}">${escapeHtml(p.status)}</div>
          <h3 class="card__name">${escapeHtml(p.name)}</h3>
          <div class="card__where">${escapeHtml(p.address)}${p.neighborhood ? ` · ${escapeHtml(p.neighborhood)}` : ""}</div>
          ${facts.length ? `<div class="card__facts">${facts.map((f) => `<span>${escapeHtml(f)}</span>`).join("")}</div>` : ""}
        </button>
      </li>`;
    })
    .join("");

  el.cards.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", () => select(card.dataset.id, true));
  });

  el.empty.hidden = list.length > 0;
  el.tally.textContent =
    list.length === state.projects.length
      ? `${list.length} projects`
      : `${list.length} of ${state.projects.length} projects`;
}

function render() {
  const list = visible();
  drawCards(list);
  drawSpine();

  if (map && map.getSource("projects")) {
    map.getSource("projects").setData(toGeoJson(list));
  }
}

// --------------------------------------------------------------------------

function toGeoJson(list) {
  return {
    type: "FeatureCollection",
    features: list.map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lng, p.lat] },
      properties: { id: p.id, name: p.name, color: colorOf(p.status), status: p.status },
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

function select(id, flyTo) {
  const project = state.projects.find((p) => p.id === id);
  if (!project) return;

  state.selected = id;

  el.cards.querySelectorAll(".card").forEach((card) => {
    card.classList.toggle("is-active", card.dataset.id === id);
  });

  const stage = indexOf(project.status);
  const color = colorOf(project.status);

  el.detailBody.innerHTML = `
    <h2>${escapeHtml(project.name)}</h2>
    <p class="detail__where">${escapeHtml(project.address)}${project.neighborhood ? ` · ${escapeHtml(project.neighborhood)}` : ""}</p>

    <div class="track" style="--stage:${color}" role="img" aria-label="Stage: ${escapeHtml(project.status)}">
      ${STAGES.slice(0, 5).map((_, i) => `<span class="${i <= stage && stage < 5 ? "on" : ""}"></span>`).join("")}
    </div>
    <p class="track__label" style="--stage:${color}">${escapeHtml(project.status)}${project.statusUpdated ? ` since ${escapeHtml(project.statusUpdated)}` : ""}</p>

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
      project.drbFile || project.permitNumbers.length || project.parcelId || project.lastVerified
        ? `<dl class="specs specs--quiet">
             ${project.drbFile ? `<dt>Design review</dt><dd>${escapeHtml(project.drbFile)}</dd>` : ""}
             ${project.permitNumbers.length ? `<dt>Permit numbers</dt><dd>${escapeHtml(project.permitNumbers.join(", "))}</dd>` : ""}
             ${project.parcelId ? `<dt>Parcel</dt><dd>${escapeHtml(project.parcelId)}</dd>` : ""}
             ${project.lastVerified ? `<dt>Verified</dt><dd>${escapeHtml(project.lastVerified)}</dd>` : ""}
           </dl>`
        : ""
    }

    <p class="detail__note">This page displays available information at the time of project entry.${
      project.lastVerified ? ` Last checked ${escapeHtml(project.lastVerified)}.` : ""
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

  el.detail.hidden = false;
  el.detail.scrollTop = 0;
  document.getElementById("detail-close").focus();

  if (flyTo && map) {
    map.flyTo({ center: [project.lng, project.lat], zoom: Math.max(map.getZoom(), 15), speed: 0.9 });
  }
}

function closeDetail() {
  el.detail.hidden = true;
  state.selected = null;
  el.cards.querySelectorAll(".card").forEach((c) => c.classList.remove("is-active"));
}

// --------------------------------------------------------------------------

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
    map.addSource("projects", { type: "geojson", data: toGeoJson(visible()) });

    map.addLayer({
      id: "project-halo",
      type: "circle",
      source: "projects",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 7, 16, 15],
        "circle-color": ["get", "color"],
        "circle-opacity": 0.22,
      },
    });

    map.addLayer({
      id: "project-dot",
      type: "circle",
      source: "projects",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 4, 16, 8],
        "circle-color": ["get", "color"],
        "circle-stroke-width": 1.5,
        "circle-stroke-color": "#f5f6f2",
      },
    });

    map.on("click", "project-dot", (e) => select(e.features[0].properties.id, false));
    map.on("mouseenter", "project-dot", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "project-dot", () => (map.getCanvas().style.cursor = ""));
  });
}

// --------------------------------------------------------------------------

async function start() {
  el.search.addEventListener("input", (e) => {
    state.query = e.target.value;
    render();
  });

  document.getElementById("detail-close").addEventListener("click", closeDetail);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.detail.hidden) closeDetail();
  });

  document.querySelectorAll(".viewswitch button").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".viewswitch button").forEach((t) =>
        t.setAttribute("aria-selected", String(t === tab))
      );
      document.body.dataset.view = tab.dataset.view;
      if (tab.dataset.view === "map" && map) map.resize();
    });
  });
  document.body.dataset.view = "map";

  try {
    const response = await fetch("data/projects.json", { cache: "no-store" });
    if (!response.ok) throw new Error(response.status);
    const payload = await response.json();

    if (Array.isArray(payload.stages) && payload.stages.length) STAGES = payload.stages;
    state.projects = payload.projects;

    drawChips();
    startMap();
    el.countStamp.textContent = `${payload.projects.length} projects tracked`;
    el.builtStamp.textContent = payload.builtAt
      ? `Updated ${new Date(payload.builtAt).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}`
      : "";

    render();
  } catch (error) {
    drawChips();
    startMap();
    el.countStamp.textContent = "Data did not load";
    el.tally.textContent = "";
    el.empty.hidden = false;
    el.empty.textContent = "The project data did not load. Run python3 build.py to generate data/projects.json.";
    console.error(error);
  }
}

start();
