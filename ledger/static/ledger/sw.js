// Damdi service worker: makes the app installable, caches static files, and shows push reminders.
const CACHE = "damdi-static-v2";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())
));

// Static assets: cache-first (they're versioned by redeploys). Pages and API: always the network — money data must be fresh.
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || !url.pathname.startsWith("/static/")) return;
  e.respondWith(caches.open(CACHE).then(async (cache) => {
    const hit = await cache.match(e.request);
    if (hit) return hit;
    const resp = await fetch(e.request);
    if (resp.ok) cache.put(e.request, resp.clone());
    return resp;
  }));
});

self.addEventListener("push", (e) => {
  const d = e.data ? e.data.json() : {};
  e.waitUntil(self.registration.showNotification(d.title || "Damdi", {
    body: d.body || "", icon: "/static/ledger/icon-192.png", badge: "/static/ledger/icon-192.png",
    data: {url: d.url || "/"}, tag: d.title,
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data.url;
  e.waitUntil(clients.matchAll({type: "window", includeUncontrolled: true}).then((wins) => {
    for (const w of wins) if ("focus" in w) return w.navigate(url).then((c) => (c || w).focus());
    return clients.openWindow(url);
  }));
});
