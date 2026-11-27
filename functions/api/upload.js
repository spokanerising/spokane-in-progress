// POST /api/upload?project=<id>&name=<original file name>
// The body is the file itself. Photos arrive already shrunk by editor.js.
//
// Saves the file to the R2 bucket bound as MEDIA and answers with its web
// address (/media/<project>/<stamp>-<random>.<ext>). Uploading doesn't change
// the project: the address goes into the edit form, and Save records it.
//
// Setting (Cloudflare Pages > the project > Settings > Bindings):
//   MEDIA   an R2 bucket binding (the bucket is sip-media)

const MAX_BYTES = 25 * 1024 * 1024;
const ID = /^[A-Za-z0-9._-]{1,120}$/;
const TYPES = {
  jpg: { type: "image/jpeg", test: (b) => b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff },
  png: { type: "image/png", test: (b) => b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47 },
  webp: { type: "image/webp", test: (b) => ascii(b, 0, 4) === "RIFF" && ascii(b, 8, 12) === "WEBP" },
  pdf: { type: "application/pdf", test: (b) => ascii(b, 0, 5) === "%PDF-" },
};

function ascii(bytes, from, to) {
  return String.fromCharCode(...bytes.subarray(from, to));
}

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

export async function onRequestPost({ request, env, data }) {
  if (!env.MEDIA) return json({ error: "File storage isn't set up yet: the MEDIA bucket isn't connected." }, 503);
  const url = new URL(request.url);
  const project = url.searchParams.get("project") || "";
  if (!ID.test(project)) return json({ error: "Unknown project." }, 400);
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_BYTES) return json({ error: "That file is over 25 MB." }, 413);

  const bytes = new Uint8Array(await request.arrayBuffer());
  if (!bytes.length) return json({ error: "The file was empty." }, 400);
  if (bytes.length > MAX_BYTES) return json({ error: "That file is over 25 MB." }, 413);
  // What the file really is, from its first bytes, not its name.
  const ext = Object.keys(TYPES).find((k) => TYPES[k].test(bytes));
  if (!ext) return json({ error: "Only JPEG, PNG or WebP photos and PDFs can be uploaded." }, 415);

  const original = (url.searchParams.get("name") || "").replace(/[^\w .()-]/g, "").slice(0, 120);
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const rand = crypto.getRandomValues(new Uint8Array(4)).reduce((s, b) => s + b.toString(16).padStart(2, "0"), "");
  const key = `${project}/${stamp}-${rand}.${ext}`;
  await env.MEDIA.put(key, bytes, {
    httpMetadata: { contentType: TYPES[ext].type },
    customMetadata: { by: data.email || "", name: original, project },
  });
  return json({ ok: true, url: `${url.origin}/media/${key}`, key, type: TYPES[ext].type, bytes: bytes.length });
}
