// GET /api/me: who's signed in (the sign-in check is in _middleware.js).
export function onRequestGet({ data }) {
  return new Response(JSON.stringify({ email: data.email }), {
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}
