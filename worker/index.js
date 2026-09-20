/**
 * trustthemanual Worker: same-origin `/api/*` proxy in front of the FastAPI backend, plus the
 * `/ws/deepgram/*` WebSocket proxy that keeps the Deepgram key at the edge.
 * Everything else is served straight from the static assets in web/ (see wrangler.jsonc,
 * `assets.run_worker_first: ["/api/*", "/ws/*"]` — other paths never reach this handler).
 *
 * `/api/<path>` -> `${API_ORIGIN}/<path>`: method, headers and body are forwarded as-is
 * (Range included), the response body is streamed back untouched, and redirects are NOT
 * followed so the 307 from `/manuals/<id>/file` reaches the browser with the blob URL.
 */
const API_ORIGIN = "https://ttm-api.victoriousground-5b684586.eastus.azurecontainerapps.io";

// Only these read-only, rarely-changing GETs get a short edge/browser cache.
const CACHEABLE = /^\/(catalog|manuals)(\/|$|\?)/;

/**
 * Deepgram sockets the browser is allowed to reach through this Worker.
 *
 * A browser WebSocket cannot set headers, so the old path minted a temporary Deepgram key and
 * shipped it to the tab in the `Sec-WebSocket-Protocol` pair. That needs `keys:write` on the
 * account key, which this account does not have — `/api/voice/deepgram-token` 502s and neither
 * socket ever opens. Here the Worker holds `DEEPGRAM_API_KEY` (a Worker secret), opens the
 * upstream socket with a real `Authorization: Token` header and pipes the frames through. No
 * credential of any kind reaches the browser, and nothing about a frame is ever logged.
 */
const DEEPGRAM_ROUTES = {
  "/ws/deepgram/agent": "https://agent.deepgram.com/v1/agent/converse",
  "/ws/deepgram/listen": "https://api.deepgram.com/v2/listen",
};

const ORIGIN_ALLOW = new Set([
  "mechanica.emilvinu.ch",
  "trustthemanual.cloudflare-disjoin783.workers.dev",
  "localhost",
  "127.0.0.1",
]);

/**
 * Browsers always send Origin on a WebSocket handshake. This used to read that the other way round
 * — "no Origin means one of our own scripts" — but everything that is not a browser also sends no
 * Origin, so the check was an open door to DEEPGRAM_API_KEY for any client that simply left the
 * header off (docs/qa/BUGS.md BUG-10). Nothing of ours needs the exemption: every harness in
 * web/tools drives headless Chrome, and there is no node WebSocket client in the repo.
 */
export function originOk(origin, url) {
  if (!origin) return false;
  let host;
  try {
    host = new URL(origin).hostname;
  } catch {
    return false;
  }
  // `url.hostname` covers the live domain and every workers.dev preview of this Worker.
  return host === url.hostname || ORIGIN_ALLOW.has(host);
}

/**
 * A Location that points back at the API origin -> the same path under /api on this origin.
 * Returns "" for anything else (the blob URL a PDF redirect carries, above all), so only a
 * redirect that would have left the proxy is rewritten.
 */
export function backToApi(location, here) {
  let target;
  try {
    target = new URL(location, API_ORIGIN);
  } catch {
    return "";
  }
  const origin = new URL(API_ORIGIN);
  if (target.hostname !== origin.hostname) return "";
  return `${here.origin}/api${target.pathname}${target.search}`;
}

function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/** Close codes a WebSocket may be closed with: 1005/1006/1015 and anything below 1000 are not. */
function shut(ws, code, reason) {
  const ok = Number.isInteger(code) && code >= 1000 && code <= 4999 && ![1005, 1006, 1015].includes(code);
  try {
    ws.close(ok ? code : 1000, reason ? String(reason).slice(0, 120) : undefined);
  } catch {
    /* already gone */
  }
}

/**
 * A socket whose binary frames arrive as ArrayBuffer. Workers defaults `binaryType` to "blob",
 * and a Blob handed back to `send()` goes out as the text "[object Blob]" — which is exactly how
 * a transparent audio proxy turns every PCM frame into an UNPARSABLE_CLIENT_MESSAGE. One line,
 * both ends, or nothing that is not JSON survives the hop.
 */
function raw(ws) {
  ws.binaryType = "arraybuffer";
  ws.accept();
  return ws;
}

/** Frames from `from` to `to`, verbatim, in whatever type they arrive (text or ArrayBuffer). */
function pipe(from, to) {
  from.addEventListener("message", (event) => {
    try {
      to.send(event.data);
    } catch {
      shut(from, 1011);
    }
  });
  from.addEventListener("close", (event) => shut(to, event.code, event.reason));
  from.addEventListener("error", () => shut(to, 1011));
}

async function deepgram(request, env, url, upstreamUrl) {
  if ((request.headers.get("Upgrade") || "").toLowerCase() !== "websocket") {
    return json(426, { error: "expected_websocket" });
  }
  if (!originOk(request.headers.get("Origin"), url)) return json(403, { error: "forbidden_origin" });
  const key = env.DEEPGRAM_API_KEY;
  if (!key) return json(503, { error: "no_deepgram_key" });

  // The upstream socket is opened BEFORE the browser's handshake is answered, so the Settings
  // message the client sends on `open` can never race an upstream that is not there yet.
  let upstream;
  try {
    upstream = await fetch(upstreamUrl + url.search, {
      headers: {
        Upgrade: "websocket",
        Connection: "Upgrade",
        Authorization: `Token ${key}`,
      },
    });
  } catch (err) {
    return json(502, { error: "deepgram_unreachable", detail: String(err) });
  }

  if (!upstream.webSocket) return json(502, { error: "deepgram_refused", status: upstream.status });
  const remote = raw(upstream.webSocket);

  const pair = new WebSocketPair();
  const [client, server] = [pair[0], raw(pair[1])];

  pipe(server, remote);
  pipe(remote, server);

  return new Response(null, { status: 101, webSocket: client });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    const upstreamWs = DEEPGRAM_ROUTES[url.pathname];
    if (upstreamWs) return deepgram(request, env, url, upstreamWs);

    if (!url.pathname.startsWith("/api/") && url.pathname !== "/api") {
      // Defensive: with run_worker_first scoped to /api/* and /ws/* we are not called for these.
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
      return json(502, { error: "upstream_unreachable", detail: String(err) });
    }

    const out = new Response(upstream.body, upstream);
    // Content-Type, Content-Length, Content-Range, Accept-Ranges and Location all survive
    // the copy above; only the caching policy and a self-referential Location are ours.
    //
    // FastAPI's redirect_slashes answers `/api/health/` with a 307 to the upstream's own URL, and
    // Azure Container Apps terminates TLS so that URL comes back as **http://ttm-api…**. Passed
    // through untouched it is a mixed-content redirect a browser on https refuses to follow, and it
    // names the origin the proxy exists to hide. Anything pointing back at API_ORIGIN belongs under
    // /api; the 307 from /manuals/<id>/file points at the blob and must survive verbatim.
    const location = out.headers.get("Location");
    if (location) {
      const rewritten = backToApi(location, url);
      if (rewritten) out.headers.set("Location", rewritten);
    }
    if (request.method === "GET" && upstream.status === 200 && CACHEABLE.test(path)) {
      out.headers.set("Cache-Control", "public, max-age=60");
    } else if (!out.headers.has("Cache-Control")) {
      out.headers.set("Cache-Control", "no-store");
    }
    return out;
  },
};
