/**
 * trustthemanual Worker: same-origin `/api/*` proxy in front of the FastAPI backend.
 * Everything else is served straight from the static assets in web/ (see wrangler.jsonc,
 * `assets.run_worker_first: ["/api/*"]` — other paths never reach this handler).
 *
 * `/api/<path>` -> `${API_ORIGIN}/<path>`: method, headers and body are forwarded as-is
 * (Range included), the response body is streamed back untouched, and redirects are NOT
 * followed so the 307 from `/manuals/<id>/file` reaches the browser with the blob URL.
 */
const API_ORIGIN = "https://ttm-api.victoriousground-5b684586.eastus.azurecontainerapps.io";

// Only these read-only, rarely-changing GETs get a short edge/browser cache.
const CACHEABLE = /^\/(catalog|manuals)(\/|$|\?)/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/") && url.pathname !== "/api") {
      // Defensive: with run_worker_first scoped to /api/* we are not called for these.
      return env.ASSETS ? env.ASSETS.fetch(request) : new Response("Not found", { status: 404 });
    }

    const path = url.pathname.slice(4) || "/"; // strip "/api"
    const target = API_ORIGIN + path + url.search;

    const headers = new Headers(request.headers);
    headers.delete("host");
    // Let the upstream choose its own encoding for streamed PDFs.
    headers.delete("cf-connecting-ip");
    headers.delete("cf-ipcountry");
    headers.delete("cf-ray");
    headers.delete("cf-visitor");

    let upstream;
    try {
      upstream = await fetch(target, {
        method: request.method,
        headers,
        body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
        redirect: "manual",
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: "upstream_unreachable", detail: String(err) }), {
        status: 502,
        headers: { "content-type": "application/json", "cache-control": "no-store" },
      });
    }

    const out = new Response(upstream.body, upstream);
    // Content-Type, Content-Length, Content-Range, Accept-Ranges and Location all survive
    // the copy above; only the caching policy is ours.
    if (request.method === "GET" && upstream.status === 200 && CACHEABLE.test(path)) {
      out.headers.set("Cache-Control", "public, max-age=60");
    } else if (!out.headers.has("Cache-Control")) {
      out.headers.set("Cache-Control", "no-store");
    }
    return out;
  },
};
