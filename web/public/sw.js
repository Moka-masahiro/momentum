/*
 * Service Worker: ホーム画面に追加したアプリとして開けるようにし、
 * 一度開いた画面とデータを端末に残す（電波の無いところでも前回の内容を見られる）。
 *
 * - 画面の部品（assets/ の下。ファイル名に中身のハッシュが付く）… 端末に残したものを優先
 * - それ以外（index.html・データ）… まず取りに行き、取れなければ端末に残したものを使う
 *   データは毎日作り直されるので、端末の古いものを優先すると更新が見えなくなる
 */
const VERSION = "v1";
const SHELL = `shell-${VERSION}`;
const DATA = `data-${VERSION}`;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL, DATA]);
      for (const key of await caches.keys()) if (!keep.has(key)) await caches.delete(key);
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes("/assets/")) {
    event.respondWith(cacheFirst(req, SHELL));
  } else {
    event.respondWith(networkFirst(req, url.pathname.includes("/data/") ? DATA : SHELL));
  }
});

async function cacheFirst(req, name) {
  const cache = await caches.open(name);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

async function networkFirst(req, name) {
  const cache = await caches.open(name);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    throw err;
  }
}
