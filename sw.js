/* 離線快取：開過一次之後，沒網路也能看「上次下載的資料」。
   - 頁面與資料（index.html、result.js）：有網路時永遠先抓最新，抓到就更新快取；沒網路才用快取。
   - 圖示等靜態檔：先用快取。
   改版時把 VERSION 加 1，舊快取會被清掉。 */
const VERSION = 'v1';
const CACHE = 'tw-signal-' + VERSION;
const SHELL = ['./', './index.html', './result.js', './manifest.webmanifest', './icon.svg', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await Promise.allSettled(SHELL.map(u => c.add(new Request(u, { cache: 'reload' }))));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  const fresh = req.mode === 'navigate' || /\/(index\.html|result\.js)?$/.test(url.pathname) || url.pathname.endsWith('result.js');
  e.respondWith((async () => {
    const c = await caches.open(CACHE);
    if (fresh) {
      try {
        const r = await fetch(req, { cache: 'no-cache' });
        if (r && r.ok) c.put(req.mode === 'navigate' ? './index.html' : req, r.clone());
        return r;
      } catch (_) {
        return (await c.match(req, { ignoreSearch: true })) || (await c.match('./index.html')) || Response.error();
      }
    }
    const hit = await c.match(req, { ignoreSearch: true });
    if (hit) return hit;
    try {
      const r = await fetch(req);
      if (r && r.ok) c.put(req, r.clone());
      return r;
    } catch (_) { return Response.error(); }
  })());
});
