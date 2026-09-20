const VERSION = "v3";
const SHELL = `handy-book-shell-${VERSION}`;
const RUNTIME = `handy-book-runtime-${VERSION}`;
const DATA = `handy-book-data-${VERSION}`;
const FONTS = `handy-book-fonts-${VERSION}`;
const RUNTIME_MAX = 300;
const SCREENS = ["identify", "confirm", "pick", "book", "follow", "invoice"];

const PRECACHE = [
  "./",
  "index.html",
  "css/counter.css",
  ...SCREENS.map((id) => `css/screens/${id}.css`),
  "js/app.js",
  "js/bus.js",
  "js/query.js",
  "js/ttm.js",
  "js/index-data.js",
  "js/search.js",
  "js/ask.js",
  "js/pdf.js",
  "js/speech.js",
  "js/deepgram.js",
  "js/voice.js",
  "js/vision.js",
  ...SCREENS.map((id) => `js/screens/${id}.js`),
  "js/screens/cost.js",
  "css/screens/cost.css",
  "../store/ttm-catalog.json",
  "../store/bike-images.json",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/icon-512-maskable.png",
];

function sameOrigin(url) {
  return url.origin === self.location.origin;
}

function isPdfOrOnnx(url) {
  return /\.(?:pdf|onnx)$/i.test(url.pathname) || /\/manuals\/[^/]+\/file$/.test(url.pathname);
}

function isCatalog(url) {
  return sameOrigin(url) && url.pathname.endsWith("/store/catalog.json");
}

function isImmutableStore(url) {
  if (!sameOrigin(url)) return false;
  const path = url.pathname;
  if (path.includes("/store/img/")) return true;
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
      cache.add(url).catch((err) => {
        console.warn("precache skip", url, err);
      })
    )
  );
}

async function dropOldCaches() {
  const keep = new Set([SHELL, RUNTIME, DATA, FONTS]);
  const keys = await caches.keys();
  await Promise.all(keys.filter((key) => !keep.has(key)).map((key) => caches.delete(key)));
}

async function trimRuntime(cache) {
  const keys = await cache.keys();
  while (keys.length > RUNTIME_MAX) {
    await cache.delete(keys.shift());
  }
}

async function putRuntime(request, response) {
  if (!response || !response.ok) return;
  if (response.type !== "basic" && response.type !== "cors") return;
  const cache = await caches.open(RUNTIME);
  await cache.put(request, response.clone());
  await trimRuntime(cache);
}

async function putUncapped(cacheName, request, response) {
  if (!isCacheable(response)) return;
  if (response.type !== "basic" && response.type !== "cors" && response.type !== "opaque") return;
  const cache = await caches.open(cacheName);
  await cache.put(request, response.clone());
}

async function cacheFirst(request) {
  const cache = await caches.open(RUNTIME);
  const hit = await cache.match(request);
  if (hit) {
    await cache.delete(request);
    await cache.put(request, hit.clone());
    return hit;
  }
  const response = await fetch(request);
  await putRuntime(request, response);
  return response;
}

async function networkFirstData(request) {
  const cache = await caches.open(DATA);
  try {
    const response = await fetch(request);
    await putUncapped(DATA, request, response);
    return response;
  } catch (err) {
    const hit = await cache.match(request);
    if (hit) return hit;
    throw err;
  }
}

async function staleWhileRevalidateFonts(event, request) {
  const cache = await caches.open(FONTS);
  const cached = await cache.match(request);
  const fetching = fetch(request)
    .then(async (response) => {
      await putUncapped(FONTS, request, response);
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
  if (!sameOrigin(url) || isPdfOrOnnx(url) || isCatalog(url) || isImmutableStore(url)) return false;
  return url.pathname === "/counter" || url.pathname.startsWith("/counter/");
}

async function shellFirst(request) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match(request, { ignoreSearch: true });
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (shouldShellCache(request, response)) {
      await cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    if (request.mode === "navigate") {
      const fallback = (await cache.match("./")) || (await cache.match("index.html"));
      if (fallback) return fallback;
    }
    throw err;
  }
}

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(precache());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(dropOldCaches().then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.protocol !== "http:" && url.protocol !== "https:") return;

  if (isPdfOrOnnx(url)) {
    event.respondWith(fetch(request));
    return;
  }
  if (isCatalog(url)) {
    event.respondWith(networkFirstData(request));
    return;
  }
  if (isImmutableStore(url)) {
    event.respondWith(cacheFirst(request));
    return;
  }
  if (isGoogleFont(url)) {
    event.respondWith(staleWhileRevalidateFonts(event, request));
    return;
  }
  event.respondWith(shellFirst(request));
});
