// POST /api/edit: saves one edit as one new file in data/edits/ on GitHub.
//
// The sign-in check runs first (_middleware.js). This checks the edit, then
// commits it through GitHub's API. The commit starts the "Refresh project
// data" build, which applies every edit (edits.py) and republishes the site.
//
// Settings (Cloudflare Pages > the project > Settings > Variables and secrets):
//   GITHUB_TOKEN   secret: a fine-grained token for this one repository,
//                  with Contents: read and write
//   GITHUB_REPO    optional; defaults to spokanerising/spokane-in-progress
//   GITHUB_BRANCH  optional; defaults to main

const KINDS = {
  name: "text", address: "text", description: "text",
  projectType: "text", developer: "text", architect: "text",
  imageCredit: "text", docLabel: "text",
  statusUpdated: "date", lastVerified: "date",
  status: "stage",
  units: "int", stories: "int", sqft: "int", parking: "int", estCost: "int",
  permitUrl: "url", imageUrl: "url", docUrl: "url",
  sourceUrls: "urls",
  lat: "float", lng: "float",
  imagePermission: "permission",
  hidden: "bool",
};
const STAGES = ["Pre-Application", "Applied", "Approved", "Under Construction", "Complete", "Stalled"];
const PERMISSIONS = ["granted", "public-record", "not-sure", ""];
const ID = /^[A-Za-z0-9._-]{1,120}$/;
const PERMIT = /^[A-Za-z0-9-]{1,40}$/;
const SAFE_URL = /^(https?:\/\/|\/)/i;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

const blank = (v) => v === null || v === undefined || (typeof v === "string" && !v.trim());

// Returns [value, problem]. Values are kept close to what was typed; the
// build (edits.py) does the final reading and has the final say.
function check(key, value) {
  const kind = KINDS[key];
  if (kind === "bool") return typeof value === "boolean" ? [value] : [null, "should be true or false"];
  if (kind === "stage") return STAGES.includes(value) ? [value] : [null, "isn't one of the six stages"];
  if (kind === "permission") return PERMISSIONS.includes(value) ? [value] : [null, "isn't a permission choice"];
  if (blank(value)) return [kind === "urls" ? [] : null];
  if (kind === "text") return typeof value === "string" && value.length <= 5000 ? [value.trim()] : [null, "should be text (up to 5,000 characters)"];
  if (kind === "date") return /^\d{4}-\d{2}-\d{2}$/.test(value) ? [value] : [null, "should be a date"];
  if (kind === "int") {
    const n = Number(String(value).replace(/[,$\s]/g, ""));
    return Number.isFinite(n) && n >= 0 && n < 1e12 ? [Math.round(n)] : [null, "should be a whole number"];
  }
  if (kind === "float") {
    const n = Number(value);
    return Number.isFinite(n) ? [n] : [null, "should be a number"];
  }
  if (kind === "url") {
    return typeof value === "string" && value.length <= 2000 && SAFE_URL.test(value.trim())
      ? [value.trim()] : [null, "should be a web address starting with https://"];
  }
  if (kind === "urls") {
    const list = Array.isArray(value) ? value : [value];
    const clean = list.map((u) => String(u).trim()).filter(Boolean);
    if (clean.length > 20) return [null, "has more than 20 links"];
    const bad = clean.find((u) => u.length > 2000 || !SAFE_URL.test(u));
    return bad ? [null, `has a link that isn't a web address (${bad.slice(0, 60)})`] : [clean];
  }
  return [null, "can't be edited"];
}

function validate(body) {
  const problems = [];
  if (!body || typeof body !== "object" || Array.isArray(body)) return [null, ["The edit is empty."]];
  if (typeof body.project !== "string" || !ID.test(body.project)) problems.push("Unknown project.");
  const permits = Array.isArray(body.permits) ? body.permits.map(String).filter((p) => PERMIT.test(p)).slice(0, 100) : [];
  const set = {};
  for (const [key, value] of Object.entries(body.set && typeof body.set === "object" ? body.set : {})) {
    if (!(key in KINDS)) { problems.push(`"${key}" can't be edited.`); continue; }
    const [clean, problem] = check(key, value);
    if (problem) problems.push(`${key} ${problem}.`);
    else set[key] = clean;
  }
  const unset = (Array.isArray(body.unset) ? body.unset : []).filter((k) => k in KINDS && !(k in set));
  const was = {};
  for (const [key, value] of Object.entries(body.was && typeof body.was === "object" ? body.was : {})) {
    if (key in KINDS && (key in set || unset.includes(key))) {
      was[key] = typeof value === "string" ? value.slice(0, 5000) : Array.isArray(value) ? value.slice(0, 20).map((v) => String(v).slice(0, 2000)) : value;
    }
  }
  const note = typeof body.note === "string" ? body.note.trim().slice(0, 2000) : "";
  if (!Object.keys(set).length && !unset.length) problems.push("Nothing changed.");
  if (problems.length) return [null, problems];
  return [{ project: body.project, permits, set, was, unset, note }, []];
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
  if (text.length > 100000) return json({ error: "That edit is too big." }, 413);
  let body;
  try { body = JSON.parse(text); } catch { return json({ error: "That edit couldn't be read." }, 400); }
  const [edit, problems] = validate(body);
  if (!edit) return json({ error: problems.join(" "), problems }, 400);

  const now = new Date();
  const at = now.toISOString().replace(/\.\d+Z$/, "Z");
  const record = { project: edit.project, permits: edit.permits, at, by: data.email, set: edit.set,
                   was: edit.was, unset: edit.unset, note: edit.note };
  const stamp = at.replace(/[-:]/g, "").replace(/Z$/, "Z");         // 20261127T091244Z
  const rand = crypto.getRandomValues(new Uint8Array(3)).reduce((s, b) => s + b.toString(16).padStart(2, "0"), "");
  const path = `data/edits/${at.slice(0, 4)}/${at.slice(5, 7)}/${stamp}-${edit.project}-${rand}.json`;
  const fields = [...Object.keys(edit.set), ...edit.unset.map((k) => `reset ${k}`)];
  const name = typeof body.name === "string" && body.name.trim() ? body.name.trim().slice(0, 80) : edit.project;
  const message = `Edit: ${name} (${fields.join(", ")})`;

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
    body: JSON.stringify({ message, content: base64Utf8(JSON.stringify(record, null, 2) + "\n"),
                           branch: env.GITHUB_BRANCH || "main" }),
  });
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 300);
    return json({ error: `GitHub didn't save the edit (HTTP ${res.status}). ${detail}` }, 502);
  }
  const saved = await res.json();
  return json({ ok: true, path, at, commit: saved.commit && saved.commit.sha });
}
