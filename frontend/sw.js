/* Service worker: stale-while-revalidate para estáticos y network-first para navegación.
   Nunca cachea API, datos personales ni respuestas autenticadas. */
const VERSION = 'v22';
const CACHE_NAME = `buscador-personas-${VERSION}`;
const CACHE_PREFIX = 'buscador-personas-';
const SHELL_URL = `/index.html?v=${VERSION}`;
const STATIC_ASSETS = [
  '/',
  '/index.html',
  SHELL_URL,
  '/styles.css?v=3.3',
  '/app.js?v=2.19',
  '/theme.js',
  '/manifest.json',
  '/icon.svg',
  '/fonts/inter-latin.woff2',
  '/fonts/inter-latin-ext.woff2',
  '/fonts/material-symbols-outlined.woff2'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      Promise.allSettled(STATIC_ASSETS.map((url) => cache.add(url)))
    )
  );
  // No skipWaiting automático: la página muestra "Nueva versión disponible".
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
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
    url.pathname.startsWith('/scraping/');
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
        .catch(() =>
          caches.match(SHELL_URL).then((cached) => cached || caches.match('/index.html') || caches.match('/'))
        )
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
