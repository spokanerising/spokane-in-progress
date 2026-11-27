"""The editor's Cloudflare functions (functions/api/), run in Node with fake
Cloudflare Access keys and a fake GitHub. No browser or network needed."""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FUNCS = os.path.join(HERE, "..", "functions", "api")

SCRIPT = r"""
import { generateKeyPairSync, createSign } from "node:crypto";
const mw = await import("./_middleware.mjs");
const edit = await import("./edit.mjs");
const me = await import("./me.mjs");
const up = await import("./upload.mjs");
const media = await import("./media.mjs");
const proj = await import("./project.mjs");
let ok = 0;
const check = (cond, what) => { if (!cond) { console.log("FAIL: " + what); process.exit(1); } ok++; };

const { publicKey, privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const other = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "k1", alg: "RS256", use: "sig" };
const TEAM = "team.cloudflareaccess.com", AUD = "aud123";
const env = { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, GITHUB_TOKEN: "ghtok" };
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
function token(claims, { key = privateKey, kid = "k1" } = {}) {
  const head = b64({ alg: "RS256", kid, typ: "JWT" });
  const body = b64({ aud: [AUD], iss: `https://${TEAM}`, email: "SpokaneRising@gmail.com",
                     exp: Math.floor(Date.now() / 1000) + 3600, ...claims });
  const sig = createSign("RSA-SHA256").update(`${head}.${body}`).sign(key).toString("base64url");
  return `${head}.${body}.${sig}`;
}

let github = [];
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  if (url === `https://${TEAM}/cdn-cgi/access/certs`) return new Response(JSON.stringify({ keys: [jwk] }));
  if (url.startsWith("https://api.github.com/")) {
    github.push({ url, init, body: JSON.parse(init.body) });
    if (env.FAIL_GITHUB) return new Response("nope", { status: 403 });
    if (env.EXISTS) return new Response('{"message":"sha wasn\'t supplied"}', { status: 422 });
    return new Response(JSON.stringify({ commit: { sha: "abc" } }), { status: 201 });
  }
  throw new Error("unexpected fetch " + url);
};

async function call(handler, { tok, method = "GET", body, e = env, cookie } = {}) {
  const headers = {};
  if (tok) headers["cf-access-jwt-assertion"] = tok;
  if (cookie) headers.cookie = cookie;
  const request = new Request("https://projects.spokanerising.com/api/x", { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const context = { request, env: e, data: {}, next: () => handler({ request, env: e, data: context.data }) };
  const res = await mw.onRequest(context);
  return { status: res.status, body: await res.json() };
}

// Sign-in
let r = await call(me.onRequestGet, { tok: token({}) });
check(r.status === 200 && r.body.email === "spokanerising@gmail.com", "editor signed in " + JSON.stringify(r));
r = await call(me.onRequestGet, { cookie: "x=1; CF_Authorization=" + token({}) });
check(r.status === 200, "token from the cookie");
check((await call(me.onRequestGet, {})).status === 401, "no token");
check((await call(me.onRequestGet, { tok: token({ email: "someone@else.com" }) })).status === 401, "wrong email");
check((await call(me.onRequestGet, { tok: token({ aud: ["other"] }) })).status === 401, "wrong application");
check((await call(me.onRequestGet, { tok: token({ iss: "https://evil.cloudflareaccess.com" }) })).status === 401, "wrong team");
check((await call(me.onRequestGet, { tok: token({ exp: 1000 }) })).status === 401, "expired");
check((await call(me.onRequestGet, { tok: token({}, { key: other.privateKey }) })).status === 401, "forged signature");
check((await call(me.onRequestGet, { tok: token({}, { kid: "nope" }) })).status === 401, "unknown key");
const t = token({}).split("."); t[1] = b64({ aud: [AUD], iss: `https://${TEAM}`, email: "spokanerising@gmail.com", exp: 9e9 });
check((await call(me.onRequestGet, { tok: t.join(".") })).status === 401, "tampered claims");
r = await call(me.onRequestGet, { tok: token({}), e: { GITHUB_TOKEN: "x" } });
check(r.status === 503 && /set up/.test(r.body.error), "not set up says so");

// Saving
const good = { project: "city-b2404005bldc", name: "Corner Flats", permits: ["B2404005BLDC"],
               set: { units: "1,048", status: "Complete", sourceUrls: ["https://a.example"] },
               was: { units: 44, status: "Applied", sneaky: 1 }, unset: ["stories"], note: "From the developer" };
r = await call(edit.onRequestPost, { tok: token({}), method: "POST", body: good });
check(r.status === 200 && r.body.ok, "saved " + JSON.stringify(r));
check(github.length === 1, "one commit");
const g = github[0];
check(/\/repos\/spokanerising\/spokane-in-progress\/contents\/data\/edits\/\d{4}\/\d{2}\/\d{8}T\d{6}Z-city-b2404005bldc-[0-9a-f]{6}\.json$/.test(g.url), "path " + g.url);
check(g.init.method === "PUT" && g.init.headers.authorization === "Bearer ghtok", "PUT with the token");
check(g.body.branch === "main" && g.body.message === "Edit: Corner Flats (units, status, sourceUrls, reset stories)", "message " + g.body.message);
const rec = JSON.parse(Buffer.from(g.body.content, "base64").toString("utf8"));
check(rec.set.units === 1048 && rec.set.status === "Complete" && rec.by === "spokanerising@gmail.com", "record " + JSON.stringify(rec));
check(rec.unset.join() === "stories" && !("sneaky" in rec.was) && rec.note === "From the developer", "unset, was, note");
check(r.body.path.endsWith(".json") && r.body.at === rec.at, "reply names the file");

// Refused edits never reach GitHub
github = [];
const bad = async (body, what) => {
  const res = await call(edit.onRequestPost, { tok: token({}), method: "POST", body });
  check(res.status === 400 && res.body.error, what + " " + JSON.stringify(res));
};
await bad({ project: "../../x", set: { units: 1 } }, "bad project id");
await bad({ project: "p", set: { colour: "red" } }, "unknown field");
await bad({ project: "p", set: { docUrl: "javascript:alert(1)" } }, "javascript link");
await bad({ project: "p", set: { sourceUrls: ["https://ok", "data:text/html,x"] } }, "bad link in a list");
await bad({ project: "p", set: { status: "Soon" } }, "bad stage");
await bad({ project: "p", set: { units: "lots" } }, "bad number");
await bad({ project: "p", set: {} }, "nothing changed");
await bad({ project: "p", set: { name: "x".repeat(6000) } }, "too long");
check(github.length === 0, "nothing committed for refused edits");
r = await call(edit.onRequestPost, { tok: token({ email: "x@y.z" }), method: "POST", body: good });
check(r.status === 401 && github.length === 0, "only the editor can save");
// Accepted shapes
r = await call(edit.onRequestPost, { tok: token({}), method: "POST", body: { project: "p", set: { hidden: true, units: "", imageUrl: "/media/p/a.jpg", imagePermission: "granted" } } });
check(r.status === 200, "hide, blank, site path " + JSON.stringify(r));
const rec2 = JSON.parse(Buffer.from(github[0].body.content, "base64").toString("utf8"));
check(rec2.set.hidden === true && rec2.set.units === null && rec2.set.imageUrl === "/media/p/a.jpg", "values " + JSON.stringify(rec2.set));
// GitHub failure is reported
env.FAIL_GITHUB = 1;
r = await call(edit.onRequestPost, { tok: token({}), method: "POST", body: good });
check(r.status === 502 && /GitHub/.test(r.body.error), "GitHub failure reported");
delete env.FAIL_GITHUB;
r = await call(edit.onRequestPost, { tok: token({}), method: "POST", body: good, e: { ...env, GITHUB_TOKEN: "" } });
check(r.status === 503, "no token says so");
// ---- uploads (phase 2) ----
const store = new Map();
const MEDIA = {
  async put(key, bytes, opts) { store.set(key, { bytes: new Uint8Array(bytes), opts }); },
  async get(key, opts) {
    const hit = store.get(key);
    if (!hit) return null;
    const etag = '"e-' + key.length + '"';
    const obj = { httpEtag: etag, customMetadata: hit.opts.customMetadata,
                  writeHttpMetadata: (h) => h.set("content-type", hit.opts.httpMetadata.contentType) };
    const inm = opts && opts.onlyIf && opts.onlyIf.get && opts.onlyIf.get("if-none-match");
    if (inm === etag) return obj;           // precondition failed: no body
    return { ...obj, body: new Blob([hit.bytes]).stream() };
  },
};
const menv = { ...env, MEDIA };
async function send(query, bytes, e = menv, tok = token({})) {
  const headers = { "content-type": "application/octet-stream" };
  if (tok) headers["cf-access-jwt-assertion"] = tok;
  const request = new Request("https://projects.spokanerising.com/api/upload" + query, { method: "POST", headers, body: bytes });
  const context = { request, env: e, data: {}, next: () => up.onRequestPost({ request, env: e, data: context.data }) };
  const res = await mw.onRequest(context);
  return { status: res.status, body: await res.json() };
}
const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4]);
const pdf = new TextEncoder().encode("%PDF-1.7\n...");
r = await send("?project=city-b1&name=Site%20plan.pdf", pdf);
check(r.status === 200 && /^https:\/\/projects\.spokanerising\.com\/media\/city-b1\/\d{8}T\d{6}Z-[0-9a-f]{8}\.pdf$/.test(r.body.url), "pdf stored " + JSON.stringify(r));
const pdfKey = r.body.key;
check(store.get(pdfKey).opts.httpMetadata.contentType === "application/pdf" && store.get(pdfKey).opts.customMetadata.by === "spokanerising@gmail.com", "pdf type and uploader");
r = await send("?project=city-b1&name=photo.png", jpeg);
check(r.status === 200 && r.body.url.endsWith(".jpg"), "type from the bytes, not the name");
const jpgKey = r.body.key;
check((await send("?project=city-b1", new TextEncoder().encode("<html><script>"))).status === 415, "html refused");
check((await send("?project=../x", jpeg)).status === 400, "bad project");
check((await send("?project=p", new Uint8Array(0))).status === 400, "empty");
check((await send("?project=p", new Uint8Array(25 * 1024 * 1024 + 1).fill(0xff))).status === 413, "over 25 MB");
check((await send("?project=p", jpeg, env)).status === 503, "no bucket says so");
check((await send("?project=p", jpeg, menv, token({ email: "x@y.z" }))).status === 401, "only the editor uploads");
const n = store.size;
check(n === 2, "only good files stored");

// Serving
async function get(path, headers = {}) {
  const request = new Request("https://projects.spokanerising.com/media/" + path, { headers });
  return media.onRequestGet({ params: { path: path.split("/") }, env: menv, request });
}
let res = await get(pdfKey);
check(res.status === 200 && res.headers.get("content-type") === "application/pdf", "pdf served");
check(/immutable/.test(res.headers.get("cache-control")) && res.headers.get("x-content-type-options") === "nosniff", "cached, nosniff");
check(/inline; filename="Site plan.pdf"/.test(res.headers.get("content-disposition")), "pdf keeps its name");
check(new TextDecoder().decode(await res.arrayBuffer()).startsWith("%PDF-"), "pdf bytes");
res = await get(jpgKey);
check(res.status === 200 && res.headers.get("content-type") === "image/jpeg" && !res.headers.get("content-disposition"), "photo served");
res = await get(jpgKey, { "if-none-match": '"e-' + jpgKey.length + '"' });
check(res.status === 304, "304 when unchanged");
check((await get("city-b1/20261127T191705Z-deadbeef.jpg")).status === 404, "missing file 404");
check((await get("../secret")).status === 404 && (await get("city-b1/notes.txt")).status === 404, "odd paths 404");
// ---- adding a project (phase 3) ----
github = [];
const add = (body, e = env, tok = token({})) => call(proj.onRequestPost, { tok, method: "POST", body, e });
r = await add({ name: "Corner Flats Phase 2!", address: "1 W Main Ave", status: "Applied", units: "24",
                lat: 47.6588, lng: -117.4260, permits: "b2600001bldc; B26M0001PDEV", sourceUrls: "https://news.example/a",
                developer: "Acme", statusUpdated: "2026-11-01" });
check(r.status === 200 && r.body.id === "hand-corner-flats-phase-2", "added " + JSON.stringify(r));
let g2 = github[0];
check(g2.url.endsWith("/contents/data/projects/hand-corner-flats-phase-2.json") && !("sha" in g2.body), "new file, never overwrites");
check(g2.body.message === "Add project: Corner Flats Phase 2!", "commit message");
let row = JSON.parse(Buffer.from(g2.body.content, "base64").toString("utf8"));
check(row.id === "hand-corner-flats-phase-2" && row.published === "TRUE" && row.name === "Corner Flats Phase 2!", "row basics " + JSON.stringify(row));
check(row.permit_numbers === "B2600001BLDC; B26M0001PDEV" && row.units === "24" && row.lat === "47.6588" && row.status_updated === "2026-11-01", "row columns");
check(row.source_urls === "https://news.example/a" && row.developer === "Acme" && row.added_by === "spokanerising@gmail.com", "row extras");
r = await add({ name: "Parcel Only", parcelId: "35192.0101" });
row = JSON.parse(Buffer.from(github[1].body.content, "base64").toString("utf8"));
check(r.status === 200 && row.parcel_id === "35192.0101" && row.status === "Pre-Application" && /^\d{4}-\d{2}-\d{2}$/.test(row.status_updated), "parcel only, defaults");
github = [];
const refuse = async (body, what) => {
  const res = await add(body);
  check(res.status === 400 && res.body.error, what + " " + JSON.stringify(res));
};
await refuse({ address: "1 W Main", lat: 47.66, lng: -117.42 }, "no name");
await refuse({ name: "Nowhere" }, "no location");
await refuse({ name: "Half pin", lat: 47.66 }, "half a pin");
await refuse({ name: "Seattle", lat: 47.6, lng: -122.3 }, "outside Spokane");
await refuse({ name: "Bad permit", permits: "B26<script>" }, "bad permit");
await refuse({ name: "Bad link", lat: 47.66, lng: -117.42, permitUrl: "javascript:x" }, "bad link");
await refuse({ name: "Bad stage", lat: 47.66, lng: -117.42, status: "Soon" }, "bad stage");
check(github.length === 0, "nothing committed for refused projects");
env.EXISTS = 1;
r = await add({ name: "Corner Flats Phase 2", lat: 47.66, lng: -117.42 });
check(r.status === 409 && /already a project file/.test(r.body.error), "existing file not overwritten");
delete env.EXISTS;
check((await add({ name: "X", lat: 47.66, lng: -117.42 }, env, token({ email: "x@y.z" }))).status === 401, "only the editor adds");
console.log(`${ok} checks passed`);
"""

d = tempfile.mkdtemp(prefix="funcs-")
for name in ("_middleware", "edit", "me", "upload", "project"):
    shutil.copy(os.path.join(FUNCS, f"{name}.js"), os.path.join(d, f"{name}.mjs"))
shutil.copy(os.path.join(FUNCS, "..", "media", "[[path]].js"), os.path.join(d, "media.mjs"))
open(os.path.join(d, "run.mjs"), "w").write(SCRIPT)
result = subprocess.run(["node", "run.mjs"], cwd=d, capture_output=True, text=True)
print(result.stdout.strip() or result.stderr.strip())
sys.exit(result.returncode or (0 if "checks passed" in result.stdout else 1))
