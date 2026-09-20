// Stamped by deploy/web.sh on every deploy (git sha + time), so each release installs a fresh
// worker, drops the previous caches and takes over every open tab.
const VERSION = "cea25d23-202609201448";
const SHELL = `mechanica-shell-${VERSION}`;
const RUNTIME = `mechanica-runtime-${VERSION}`;
const DATA = `mechanica-data-${VERSION}`;
const FONTS = `mechanica-fonts-${VERSION}`;
const CDN = `mechanica-cdn-${VERSION}`;
const PDFS = `mechanica-pdfs-${VERSION}`;
const RUNTIME_MAX = 300;
const SCREENS = ["identify", "confirm", "pick", "book", "invoice"];

/**
 * The shell a first paint and a working search field are made of. Taken at install, which on a
 * first visit is while the page is still loading — so it is kept to what that page is fetching
 * anyway (one conditional request each, answered 304 off the HTTP cache) plus the handful of
 * icons and the theme sheet the page did not ask for.
 */
const PRECACHE = [
  "./",
  "index.html",
  "css/counter.css",
  "css/themes.css",
  "css/particons.css",
  "css/screens/identify.css",
  "js/app.js",
  "js/bus.js",
  "js/theme.js",
  "js/ttm.js",
  "js/index-data.js",
  "js/search.js",
  "js/vision.js",
  "js/screens/identify.js",
  "manifest.webmanifest",
  "icons/favicon.ico",
  "icons/favicon-32.png",
  "icons/apple-touch-icon-180.png",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/icon-512-maskable.png",
];

/**
 * Everything the *second* visit needs: the rest of the flow, the reader, the chat bundle, the
 * roster and the photo index. Half a megabyte of it, and on the first visit none of it is on
 * the critical path — so it is taken only when the page says it is done loading (app.js posts
 * "precache-rest"), and with the HTTP cache allowed to answer, so the roster the page has just
 * downloaded is not downloaded a second time.
 */
const PRECACHE_REST = [
  ...SCREENS.filter((id) => id !== "identify").map((id) => `css/screens/${id}.css`),
  "css/screens/cost.css",
  "css/chat-ui.css",
  "css/viewer3d.css",
  "css/climate.css",
  "js/query.js",
  "js/ask.js",
  "js/pdf.js",
  "js/speech.js",
  "js/deepgram.js",
  "js/voice.js",
  "js/particons.js",
  "js/climate.js",
  "js/pick-search.js",
  "js/parts-search.js",
  "js/vehicle-type.js",
  ...SCREENS.filter((id) => id !== "identify").map((id) => `js/screens/${id}.js`),
  "js/screens/cost.js",
  "../store/ttm-catalog.json",
  "../store/bike-images.json",
  "../store/bike-images-2.json",
  "../vendor/deep-chat/deepChat.bundle.js",
  "js/chat-ui.js",
  "../store/catalog.json",
];

/** Exactly the href in index.html, so the page's own request matches this cache entry. */
const FONT_CSS =
  "https://fonts.googleapis.com/css2?family=Barlow:wght@400;600;800&family=Big+Shoulders+Display:wght@700;800&display=swap";

function sameOrigin(url) {
  return url.origin === self.location.origin;
}

function isPdf(url) {
  return /\.pdf$/i.test(url.pathname) || /\/manuals\/[^/]+\/file$/.test(url.pathname);
}

function isOnnx(url) {
  return /\.onnx$/i.test(url.pathname);
}

function isCatalog(url) {
  return sameOrigin(url) && url.pathname.endsWith("/store/catalog.json");
}

/**
 * The API path, whether the base is the container app's own host or the same-origin
 * "/api" proxy this Worker puts in front of it. Same-origin paths outside /api belong to
 * the app itself, so they are not API calls.
 */
function apiPath(url) {
  const path = url.pathname;
  if (path === "/api") return "/";
  if (path.startsWith("/api/")) return path.slice(4);
  return sameOrigin(url) ? "" : path;
}

/**
 * /health, /catalog, /catalog/suggest, /manuals, /manuals/{id}, /registry, /cost. Network
 * first, cache as a fallback, so a manual that was opened once stays readable with no
 * network — including /health, which is what makes ttm.js stay in REMOTE mode offline
 * instead of dropping to the bundled-only store.
 */
function isApiData(url) {
  const path = apiPath(url);
  if (!path) return false;
  if (path === "/health" || path === "/cost" || path === "/registry") return true;
  if (path === "/catalog" || path.startsWith("/catalog/")) return true;
  return path === "/manuals" || /^\/manuals\/[^/]+$/.test(path);
}

/** pdf.js, its worker, standard fonts and cmaps. Offline the reader needs all four. */
function isCdn(url) {
  return url.hostname === "cdn.jsdelivr.net" || url.hostname === "cdnjs.cloudflare.com";
}

/**
 * Big, rarely changing files: vehicle photos, part icons and illustrations, 3D models,
 * environments, rendered manual pages. Served from the cache at once and refreshed in the
 * background, because the image and 3D pipelines overwrite files in place under the same
 * name, so "immutable" was never true.
 */
function isStoreAsset(url) {
  if (!sameOrigin(url)) return false;
  const path = url.pathname;
  if (/\/store\/(img|icons-parts|icons-parts-3d|models|env)\//.test(path)) return true;
  return /\/store\/manuals\/.+\/pages\//.test(path);
}

function isGoogleFont(url) {
  return url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com";
}

function isCacheable(response) {
  return Boolean(response) && (response.ok || response.type === "opaque");
}

async function precache() {
  const cache = await caches.open(SHELL);
  await Promise.all(
    PRECACHE.map((url) =>
      cache.add(new Request(url, { cache: "reload" })).catch((err) => {
        console.warn("precache skip", url, err);
      })
    )
  );
}

let restDone = false;

/**
 * The second-visit half. Two rules keep it off the first visit's wire: it runs only when the
 * page asks, and it lets the HTTP cache answer — every one of these files either was just
 * fetched by the page (so this is a 304, or nothing at all when the fetch handler already
 * cached it) or is something the page never asks for on the landing. Four at a time, so a
 * conference wifi is not asked for forty sockets at once.
 */
async function precacheRest() {
  if (restDone) return;
  restDone = true;
  const cache = await caches.open(SHELL);
  const queue = PRECACHE_REST.slice();
  const worker = async () => {
    while (queue.length) {
      const url = queue.shift();
      try {
        const request = new Request(url);
        if (await cache.match(request, { ignoreSearch: true })) continue;
        await cache.add(request);
      } catch (err) {
        console.warn("precache skip", url, err);
      }
    }
  };
  await Promise.all([worker(), worker(), worker(), worker()]);
}

/**
 * The two display faces are the app's whole visual identity, and the stylesheet is in the
 * head — it is requested before the worker ever claims this page, so waiting for a second
 * visit to cache it would leave the first offline load in system-ui. Take the css and the
 * woff2 files it names at install time instead.
 */
async function precacheFonts() {
  try {
    const cache = await caches.open(FONTS);
    const res = await fetch(FONT_CSS);
    if (!res.ok) return;
    const css = await res.text();
    await cache.put(FONT_CSS, new Response(css, { headers: { "Content-Type": "text/css" } }));
    const files = [...new Set(css.match(/https:\/\/fonts\.gstatic\.com\/[^)"']+/g) || [])];
    await Promise.all(files.map((url) => cache.add(url).catch(() => {})));
  } catch (err) {
    console.warn("font precache skip", err);
  }
}

async function dropOldCaches() {
  const keep = new Set([SHELL, RUNTIME, DATA, FONTS, CDN, PDFS]);
  const keys = await caches.keys();
  await Promise.all(keys.filter((key) => !keep.has(key)).map((key) => caches.delete(key)));
}

async function trimRuntime(cache) {
  const keys = await cache.keys();
  while (keys.length > RUNTIME_MAX) {
    await cache.delete(keys.shift());
  }
}

async function putRuntime(cacheName, request, response) {
  if (!response || !response.ok) return;
  if (response.type !== "basic" && response.type !== "cors") return;
  const cache = await caches.open(cacheName);
  await cache.put(request, response.clone());
  if (cacheName === RUNTIME) await trimRuntime(cache);
}

async function putUncapped(cacheName, request, response) {
  if (!isCacheable(response)) return;
  if (response.type !== "basic" && response.type !== "cors" && response.type !== "opaque") return;
  const cache = await caches.open(cacheName);
  await cache.put(request, response.clone());
}

async function cacheFirst(request, cacheName = RUNTIME) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) {
    if (cacheName === RUNTIME) {
      await cache.delete(request);
      await cache.put(request, hit.clone());
    }
    return hit;
  }
  const response = await fetch(request);
  await putRuntime(cacheName, request, response);
  return response;
}

/* ---------- manual PDFs ---------- */

const warming = new Set();
let bytesUrl = "";
let bytesBuf = null;

async function fullBytes(response, url) {
  if (bytesUrl === url && bytesBuf) return bytesBuf;
  const buf = await response.arrayBuffer();
  bytesUrl = url;
  bytesBuf = buf;
  return buf;
}

/**
 * pdf.js reads a manual with Range requests, so a cached whole file has to be sliced by
 * hand: Cache Storage stores the 200, we answer the 206 from it.
 */
async function sliceRange(response, url, header) {
  const buf = await fullBytes(response, url);
  const total = buf.byteLength;
  const hit = /^bytes=(\d*)-(\d*)$/.exec(String(header).trim());
  if (!hit) return new Response(buf.slice(0), { status: 200, headers: response.headers });
  let start;
  let end;
  if (hit[1] === "") {
    const tail = Number(hit[2]);
    if (!Number.isFinite(tail) || tail <= 0) return new Response(null, { status: 416 });
    start = Math.max(0, total - tail);
    end = total - 1;
  } else {
    start = Number(hit[1]);
    end = hit[2] === "" ? total - 1 : Math.min(Number(hit[2]), total - 1);
  }
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || start >= total) {
    return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${total}` } });
  }
  const body = buf.slice(start, end + 1);
  return new Response(body, {
    status: 206,
    statusText: "Partial Content",
    headers: {
      "Content-Type": response.headers.get("Content-Type") || "application/pdf",
      "Content-Length": String(body.byteLength),
      "Content-Range": `bytes ${start}-${end}/${total}`,
      "Accept-Ranges": "bytes",
    },
  });
}

async function fromPdfCache(cache, url, range) {
  const hit = await cache.match(url);
  if (!hit) return null;
  return range ? sliceRange(hit, url, range) : hit;
}

function warmPdf(event, cache, url) {
  if (warming.has(url)) return;
  warming.add(url);
  event.waitUntil(
    fetch(url)
      .then(async (res) => {
        if (res && res.ok && res.status === 200) await cache.put(url, res.clone());
      })
      .catch(() => {})
      .finally(() => warming.delete(url))
  );
}

async function manualPdf(event, request) {
  const url = request.url;
  const range = request.headers.get("range");
  const cache = await caches.open(PDFS);
  const hit = await fromPdfCache(cache, url, range);
  if (hit) return hit;
  warmPdf(event, cache, url);
  try {
    return await fetch(request);
  } catch (err) {
    const late = await fromPdfCache(cache, url, range);
    if (late) return late;
    throw err;
  }
}

async function networkFirstData(request) {
  try {
    const response = await fetch(request);
    await putUncapped(DATA, request, response);
    return response;
  } catch (err) {
    // Any cache: /store/catalog.json is precached into SHELL, API answers land in DATA.
    const hit = await caches.match(request, { ignoreSearch: false });
    if (hit) return hit;
    throw err;
  }
}

async function staleWhileRevalidate(event, request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const fetching = fetch(request)
    .then(async (response) => {
      await putUncapped(cacheName, request, response);
      return response;
    })
    .catch((err) => {
      if (cached) return cached;
      throw err;
    });
  if (cached) {
    event.waitUntil(fetching.catch(() => {}));
    return cached;
  }
  return fetching;
}

function shouldShellCache(request, response) {
  if (!response.ok) return false;
  if (response.type !== "basic" && response.type !== "cors") return false;
  const url = new URL(request.url);
  if (!sameOrigin(url) || isPdf(url) || isOnnx(url) || isCatalog(url) || isStoreAsset(url)) return false;
  const path = url.pathname;
  return path === "/counter" || path.startsWith("/counter/") || path.startsWith("/store/") || path.startsWith("/vendor/");
}

/**
 * The page itself (a navigation): network first, cache as the fallback. It is one small
 * request, it is the file that names every other one, and an agent who has just deployed has
 * to see the deploy on the next reload rather than the one after it.
 */
async function shellNetworkFirst(request) {
  const cache = await caches.open(SHELL);
  try {
    const response = await fetch(request);
    if (shouldShellCache(request, response)) {
      await cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await cache.match(request, { ignoreSearch: true });
    if (cached) return cached;
    if (request.mode === "navigate") {
      const fallback = (await cache.match("./")) || (await cache.match("index.html"));
      if (fallback) return fallback;
    }
    throw err;
  }
}

/**
 * Everything the page then asks for — css, js, the bundled roster, the photo index: whatever
 * this version of the worker has, at once, and a revalidation behind it.
 *
 * It used to be network first for all of it, on the reasoning that the edge answers each file
 * with max-age=0 + ETag so a revalidation is cheap. It is cheap in bytes and expensive in
 * everything else: measured on a second visit at fast 4G + 4x CPU (worker included, which is
 * the half that is easy to forget to throttle) thirty conditional requests put the search field
 * at 21 s, against 2.6 s when they were answered from the cache. Nothing goes stale by it: a
 * deploy stamps VERSION, which is a new worker, which drops every old cache, precaches the new
 * shell and claims the page — and app.js reloads on that claim. The navigation above is still
 * network first, so the reload that follows a deploy lands on the new page immediately.
 */
/**
 * Scripts, styles and the bundled roster/photo indexes: NETWORK FIRST, with the cache as the
 * fallback after a short wait. Stale-while-revalidate here meant every deploy showed up one
 * load late, which the founder read as "caching is way too strong". The edge answers these
 * with max-age=0 + ETag, so online this is one conditional request per file (a 304 when nothing
 * changed); on a slow or dead network the last good copy is served after SHELL_WAIT_MS.
 */
const SHELL_WAIT_MS = 2500;

async function shellCacheFirst(event, request) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match(request, { ignoreSearch: true });
  const fresh = fetch(request)
    .then(async (response) => {
      if (shouldShellCache(request, response)) await cache.put(request, response.clone());
      return response;
    });
  if (!cached) return fresh;
  const timeout = new Promise((resolve) => setTimeout(() => resolve(null), SHELL_WAIT_MS));
  const first = await Promise.race([fresh.catch(() => null), timeout]);
  if (first) return first;
  // network slow or gone: serve the cached copy now, let the fetch finish filling the cache
  event.waitUntil(fresh.catch(() => {}));
  return cached;
}

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(Promise.all([precache(), precacheFonts()]));
});

self.addEventListener("activate", (event) => {
  // Nothing slow belongs in here: a worker is "activating" until this promise settles, and every
  // fetch from the page it just claimed waits for that. (It cost a warm load 20 seconds once.)
  event.waitUntil(dropOldCaches().then(() => self.clients.claim()));
});

self.addEventListener("message", (event) => {
  const type = event.data && event.data.type;
  if (type === "precache-rest") event.waitUntil(precacheRest());
});

let restArmed = false;

/**
 * The fallback for a page that never sends "precache-rest" — an old app.js out of someone's
 * cache, or a tab closed mid-load. Hung off the first fetch event rather than off activate,
 * because a worker is not activated until its activate handler settles and every request from
 * the page it has claimed waits for that.
 */
function armRest(event) {
  if (restArmed || restDone) return;
  restArmed = true;
  event.waitUntil(new Promise((done) => setTimeout(done, 15000)).then(() => precacheRest()));
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.protocol !== "http:" && url.protocol !== "https:") return;

  armRest(event);

  if (isOnnx(url)) {
    event.respondWith(fetch(request));
    return;
  }
  if (isPdf(url)) {
    event.respondWith(manualPdf(event, request));
    return;
  }
  if (isCatalog(url) || isApiData(url)) {
    event.respondWith(networkFirstData(request));
    return;
  }
  if (isCdn(url)) {
    event.respondWith(cacheFirst(request, CDN));
    return;
  }
  if (isStoreAsset(url)) {
    event.respondWith(staleWhileRevalidate(event, request, RUNTIME));
    return;
  }
  if (isGoogleFont(url)) {
    event.respondWith(staleWhileRevalidate(event, request, FONTS));
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(shellNetworkFirst(request));
    return;
  }
  event.respondWith(shellCacheFirst(event, request));
});
