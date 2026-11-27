// POST /api/project: adds a hand-curated project, as a new file
// data/projects/hand-<name>.json on GitHub (the same columns the sheet had).
//
// The sign-in check runs first (_middleware.js). The build places the
// project from its pin (lat/lng), else its parcel number, else its permit
// numbers, and a project that lists permits claims them, so the city's own
// version of that project doesn't also appear. Never overwrites a file.
//
// Uses the same settings as /api/edit (GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH).

const STAGES = ["Pre-Application", "Applied", "Approved", "Under Construction", "Complete", "Stalled"];
const PERMIT = /^[A-Za-z0-9-]{1,40}$/;
const SAFE_URL = /^(https?:\/\/|\/)/i;
const BOUNDS = { minLat: 47.5, maxLat: 47.85, minLng: -117.7, maxLng: -117.15 };

// Form field -> project file column, and how to check it.
const COLUMNS = {
  name: ["name", "text"], address: ["address", "text"], description: ["description", "text"],
  status: ["status", "stage"], statusUpdated: ["status_updated", "date"],
  projectType: ["project_type", "text"], units: ["units", "int"], stories: ["stories", "int"],
  sqft: ["sqft", "int"], parking: ["parking", "int"], estCost: ["est_cost", "int"],
  developer: ["developer", "text"], architect: ["architect", "text"], permitUrl: ["permit_url", "url"],
  parcelId: ["parcel_id", "parcel"], permits: ["permit_numbers", "permits"],
  lat: ["lat", "float"], lng: ["lng", "float"], sourceUrls: ["source_urls", "urls"],
};

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60).replace(/-$/, "");

function read(kind, value) {
  if (value === null || value === undefined || (typeof value === "string" && !value.trim())) return [""];
  const text = String(value).trim();
  if (kind === "text") return text.length <= 5000 ? [text] : [null, "is too long"];
  if (kind === "stage") return STAGES.includes(text) ? [text] : [null, "isn't one of the six stages"];
  if (kind === "date") return /^\d{4}-\d{2}-\d{2}$/.test(text) ? [text] : [null, "should be a date"];
  if (kind === "int") {
    const n = Number(text.replace(/[,$\s]/g, ""));
    return Number.isFinite(n) && n >= 0 && n < 1e12 ? [String(Math.round(n))] : [null, "should be a whole number"];
  }
  if (kind === "float") return Number.isFinite(Number(text)) ? [String(Number(text))] : [null, "should be a number"];
  if (kind === "url") return SAFE_URL.test(text) && text.length <= 2000 ? [text] : [null, "should be a web address"];
  if (kind === "parcel") return /^[0-9.\-]{5,20}$/.test(text) ? [text] : [null, "should look like 35192.0101"];
  if (kind === "permits" || kind === "urls") {
    const list = (Array.isArray(value) ? value : text.split(/[;,\s]+/)).map((x) => String(x).trim()).filter(Boolean);
    if (kind === "permits") {
      const bad = list.find((x) => !PERMIT.test(x));
      return bad ? [null, `has "${bad}", which doesn't look like a permit number`] : [list.map((x) => x.toUpperCase()).join("; ")];
    }
    const bad = list.find((x) => !SAFE_URL.test(x));
    return bad ? [null, "has a link that isn't a web address"] : [list.join("; ")];
  }
  return [null, "can't be set"];
}

function validate(body) {
  const problems = [];
  const row = {};
  for (const [field, [column, kind]] of Object.entries(COLUMNS)) {
    const [value, problem] = read(kind, body[field]);
    if (problem) problems.push(`${field} ${problem}.`);
    else row[column] = value;
  }
  if (!row.name) problems.push("A name is needed.");
  if (!row.status) row.status = "Pre-Application";
  if ((row.lat && !row.lng) || (!row.lat && row.lng)) problems.push("The pin needs both latitude and longitude.");
  if (row.lat && row.lng) {
    const lat = Number(row.lat), lng = Number(row.lng);
    if (lat < BOUNDS.minLat || lat > BOUNDS.maxLat || lng < BOUNDS.minLng || lng > BOUNDS.maxLng) {
      problems.push("The pin is outside the Spokane area.");
    }
  }
  if (!row.lat && !row.parcel_id && !row.permit_numbers) {
    problems.push("Drop a pin, or give a parcel number or a permit number, so the map knows where it is.");
  }
  return [problems.length ? null : row, problems];
}

function base64Utf8(text) {
  const bytes = new TextEncoder().encode(text);
  let out = "";
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(out);
}

export async function onRequestPost({ request, env, data }) {
  if (!env.GITHUB_TOKEN) return json({ error: "The editor isn't set up yet: GITHUB_TOKEN is missing." }, 503);
  const text = await request.text();
  if (text.length > 100000) return json({ error: "That's too much text." }, 413);
  let body;
  try { body = JSON.parse(text); } catch { return json({ error: "That couldn't be read." }, 400); }
  if (!body || typeof body !== "object") return json({ error: "That couldn't be read." }, 400);
  const [row, problems] = validate(body);
  if (!row) return json({ error: problems.join(" "), problems }, 400);

  const id = `hand-${slug(row.name) || "project"}`;
  const today = new Date().toISOString().slice(0, 10);
  const record = {
    id, published: "TRUE", ...row,
    status_updated: row.status_updated || today,
    last_verified: today,
    added_by: data.email || "", added_at: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
  };
  const path = `data/projects/${id}.json`;
  const repo = env.GITHUB_REPO || "spokanerising/spokane-in-progress";
  const res = await fetch(`https://api.github.com/repos/${repo}/contents/${path}`, {
    method: "PUT",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "spokane-in-progress-editor",
      "content-type": "application/json",
    },
    // No "sha": GitHub refuses (422) if the file already exists, so nothing is overwritten.
    body: JSON.stringify({ message: `Add project: ${row.name.slice(0, 80)}`,
                           content: base64Utf8(JSON.stringify(record, null, 2) + "\n"),
                           branch: env.GITHUB_BRANCH || "main" }),
  });
  if (res.status === 422) {
    return json({ error: `There's already a project file called ${id}. Give this one a different name.` }, 409);
  }
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 300);
    return json({ error: `GitHub didn't save the project (HTTP ${res.status}). ${detail}` }, 502);
  }
  return json({ ok: true, id, path, at: record.added_at });
}
