// Runs before every /api/ request: only the editor's email gets through.
//
// Cloudflare Access sits in front of /api/ and /admin/ and makes you sign in
// with a one-time code sent to your email. After that, every request carries a
// login token signed by Cloudflare. This checks the token itself (signature,
// expiry, which Access application it's for, and the email), so a mistake in
// the Access settings can't open the editor to anyone else.
//
// Settings (Cloudflare Pages > the project > Settings > Variables and secrets):
//   ACCESS_TEAM_DOMAIN  e.g. spokanerising.cloudflareaccess.com
//   ACCESS_AUD          the Access application's "Application Audience (AUD) Tag"
//   EDITOR_EMAIL        optional; defaults to spokanerising@gmail.com

const DEFAULT_EDITOR = "spokanerising@gmail.com";
let certCache = { team: "", keys: null, at: 0 };

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

function base64url(text) {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

const decodeJson = (part) => JSON.parse(new TextDecoder().decode(base64url(part)));

function teamOf(env) {
  return String(env.ACCESS_TEAM_DOMAIN || "").replace(/^https?:\/\//, "").replace(/\/.*$/, "");
}

async function signingKeys(team, fetcher) {
  const fresh = certCache.team === team && certCache.keys && Date.now() - certCache.at < 3600e3;
  if (fresh) return certCache.keys;
  const res = await fetcher(`https://${team}/cdn-cgi/access/certs`);
  if (!res.ok) throw new Error(`couldn't fetch Access keys (HTTP ${res.status})`);
  const { keys } = await res.json();
  certCache = { team, keys: keys || [], at: Date.now() };
  return certCache.keys;
}

async function verifyAccess(token, env, fetcher = fetch) {
  const team = teamOf(env);
  const parts = String(token || "").split(".");
  if (parts.length !== 3) throw new Error("malformed token");
  const header = decodeJson(parts[0]);
  const claims = decodeJson(parts[1]);
  if (header.alg !== "RS256") throw new Error("unexpected token type");
  let jwk = (await signingKeys(team, fetcher)).find((k) => k.kid === header.kid);
  if (!jwk) {
    certCache.at = 0; // keys rotate; look once more
    jwk = (await signingKeys(team, fetcher)).find((k) => k.kid === header.kid);
  }
  if (!jwk) throw new Error("unknown signing key");
  const key = await crypto.subtle.importKey(
    "jwk", { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
  const good = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, base64url(parts[2]), signed);
  if (!good) throw new Error("bad signature");
  const now = Date.now() / 1000;
  if (!claims.exp || claims.exp < now) throw new Error("sign-in expired");
  if (claims.nbf && claims.nbf > now + 60) throw new Error("token not valid yet");
  const auds = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!auds.includes(env.ACCESS_AUD)) throw new Error("token is for a different application");
  if (claims.iss !== `https://${team}`) throw new Error("token from a different team");
  const email = String(claims.email || "").toLowerCase();
  const allowed = String(env.EDITOR_EMAIL || DEFAULT_EDITOR).toLowerCase();
  if (email !== allowed) throw new Error(`${email || "this account"} isn't the editor`);
  return email;
}

function cookie(request, name) {
  const header = request.headers.get("cookie") || "";
  const hit = header.split(/;\s*/).find((c) => c.startsWith(`${name}=`));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : "";
}

export async function onRequest(context) {
  const { request, env } = context;
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) {
    return json({ error: "The editor isn't set up yet: ACCESS_TEAM_DOMAIN and ACCESS_AUD are missing." }, 503);
  }
  const token = request.headers.get("cf-access-jwt-assertion") || cookie(request, "CF_Authorization");
  if (!token) return json({ error: "Not signed in." }, 401);
  try {
    context.data.email = await verifyAccess(token, env);
  } catch (error) {
    return json({ error: `Not signed in: ${error.message}.` }, 401);
  }
  return context.next();
}
