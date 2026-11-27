// GET /media/<project>/<file>: photos and PDFs uploaded through the editor,
// served from the R2 bucket bound as MEDIA. Public, like the rest of the site.
// File names are chosen by /api/upload and never reused, so they're cached for
// a year.

const KEY = /^[A-Za-z0-9._-]{1,120}\/[0-9TZ]{16}-[0-9a-f]{8}\.(jpg|png|webp|pdf)$/;

export async function onRequestGet({ params, env, request }) {
  const key = Array.isArray(params.path) ? params.path.join("/") : String(params.path || "");
  if (!env.MEDIA || !KEY.test(key)) return new Response("Not found", { status: 404 });
  const object = await env.MEDIA.get(key, { onlyIf: request.headers });
  if (!object) return new Response("Not found", { status: 404 });
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", "public, max-age=31536000, immutable");
  headers.set("x-content-type-options", "nosniff");
  if (key.endsWith(".pdf")) {
    const name = (object.customMetadata && object.customMetadata.name) || "document.pdf";
    headers.set("content-disposition", `inline; filename="${name.replace(/"/g, "")}"`);
  }
  // A conditional request that matched: the browser's copy is current.
  if (!("body" in object) || !object.body) return new Response(null, { status: 304, headers });
  return new Response(object.body, { headers });
}

export const onRequestHead = onRequestGet;
