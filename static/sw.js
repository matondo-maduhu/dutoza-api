/* Service worker ya Mercfy.
   Sheria za usalama:
   - HTML ya kurasa HAIHIFADHIWI (ina data ya session ya mtumiaji).
   - /api/ haihifadhiwi kamwe na haipitishwi hapa.
   - Inahifadhi tu: ukurasa wa offline, icons/CSS/JS za app, na Font Awesome kutoka CDN. */
const VERSION = "v1";
const SHELL = "mercfy-shell-" + VERSION;
const ASSETS = "mercfy-assets-" + VERSION;
const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL)
      .then((cache) => cache.addAll([OFFLINE_URL, "/static/icons/icon-192.png"]))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => (k.startsWith("mercfy-") || k.startsWith("incredibles-")) && k !== SHELL && k !== ASSETS)
            .map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

function isCdnAsset(url) {
  return url.hostname === "cdnjs.cloudflare.com" || url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com";
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                       // POST n.k. hazigusiwi

  const url = new URL(req.url);

  // Kurasa: mtandao kwanza; ukikosekana, ukurasa wa offline
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  // API na kitu chochote kisicho cha app: acha kivinjari kishughulikie
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) return;

  // Static za app: toa cache mara moja, sasisha nyuma (stale-while-revalidate)
  if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.open(ASSETS).then((cache) =>
        cache.match(req).then((hit) => {
          const net = fetch(req).then((res) => {
            if (res && res.status === 200) cache.put(req, res.clone());
            return res;
          }).catch(() => hit);
          return hit || net;
        })
      )
    );
    return;
  }

  // Font Awesome n.k. kutoka CDN: cache kwanza (icons zifanye kazi offline)
  if (isCdnAsset(url)) {
    event.respondWith(
      caches.open(ASSETS).then((cache) =>
        cache.match(req).then((hit) =>
          hit || fetch(req).then((res) => {
            if (res && (res.status === 200 || res.type === "opaque")) cache.put(req, res.clone());
            return res;
          })
        )
      )
    );
  }
});
