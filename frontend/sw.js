/* Service worker: stale-while-revalidate para estáticos y network-first para navegación.
   Nunca cachea API, datos personales, C4 ni respuestas autenticadas. */
const CACHE_NAME = 'buscador-personas-v18';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/styles.css?v=2.9',
  '/app.js?v=2.16',
  '/theme.js',
  '/manifest.json',
  '/icon.svg',
  '/fonts/inter-latin.woff2',
  '/fonts/inter-latin-ext.woff2'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  // No skipWaiting automático: la página muestra "Nueva versión disponible".
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

function isPrivateRequest(url) {
  return url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/persona/') ||
    url.pathname.startsWith('/buscar') ||
    url.pathname.startsWith('/scraping/') ||
    url.pathname.startsWith('/c4');
}

const STATIC_DESTINATIONS = new Set(['style', 'script', 'font', 'image', 'manifest']);

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin || isPrivateRequest(url)) return;

  // Navegación: red primero, shell offline como respaldo.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => response)
        .catch(() => caches.match('/index.html').then((cached) => cached || caches.match('/')))
    );
    return;
  }

  if (!STATIC_DESTINATIONS.has(request.destination)) return;

  // Estáticos: responde caché y revalida en segundo plano.
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => {});
          }
          return response;
        })
        .catch(() => cached || new Response('', { status: 504, statusText: 'Offline' }));
      return cached || network;
    })
  );
});
