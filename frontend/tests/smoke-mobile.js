const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const person = {
  dni: '12345678', nombres: 'JUAN CARLOS', ap_pat: 'PEREZ', ap_mat: 'GOMEZ',
  sexo: 'M', edad_anios: 34, fecha_nac: '1990-01-02', est_civil: 'SOLTERO',
  padre: 'LUIS PEREZ', madre: 'MARIA GOMEZ', direccion: 'AV. SIEMPRE VIVA 123',
  ubigeo_dir: '150101', ubigeo_nac: '150101', fch_caducidad: '2030-01-01',
};

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body, headers: { get: () => null } };
}

function makeDom() {
  const dom = new JSDOM(html, { url: 'http://127.0.0.1:8000/', runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollIntoView = function () {};
  window.URL.createObjectURL = () => 'blob:test';
  window.URL.revokeObjectURL = () => {};
  window.fetch = async (input) => {
    const url = String(input);
    if (url.includes('/api/status')) return response(200, { status: 'ok' });
    if (url.includes('/api/auth/me')) return response(200, { username: 'user', rol: 'user', consultas_restantes: 99 });
    if (url.match(/\/persona\/\d{8}(\?|$)/)) return response(200, person);
    if (url.includes('/buscar')) return response(200, [person]);
    return response(404, { detail: 'not found' });
  };
  window.eval(appJs);
  return { dom, window };
}

const wait = (ms = 100) => new Promise((resolve) => setTimeout(resolve, ms));
const assert = (cond, msg) => { if (!cond) throw new Error('FALLO: ' + msg); };

(async () => {
  const { dom, window } = makeDom();
  await wait(200);
  assert(!window.document.body.classList.contains('login-visible'), 'sesión restaurada en móvil');
  const input = window.document.getElementById('search-input');
  input.value = '12345678';
  window.document.getElementById('btn-search').click();
  await wait(260);
  const item = window.document.querySelector('.result-item');
  assert(item, 'resultado visible en móvil');
  item.click();
  await wait(120);
  assert(item.classList.contains('result-item--expanded'), 'tarjeta se expande en móvil');
  const openBtn = item.querySelector('[data-result-open]');
  assert(openBtn, 'tarjeta móvil tiene botón principal');
  assert(openBtn.getAttribute('aria-expanded') === 'true', 'botón principal marca expansión');
  window.document.querySelector('.result-inline-data').click();
  await wait(80);
  assert(item.classList.contains('result-item--expanded'), 'leer el detalle no pliega la tarjeta');
  openBtn.click();
  await wait(80);
  assert(!item.classList.contains('result-item--expanded'), 'botón principal pliega la tarjeta');
  assert(openBtn.getAttribute('aria-expanded') === 'false', 'aria-expanded vuelve a false');
  openBtn.click();
  await wait(80);
  assert(item.classList.contains('result-item--expanded'), 'botón principal despliega la tarjeta');
  assert(window.document.getElementById('btn-view-table'), 'control de vista tabla presente');

  window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
  await wait(120);
  assert(window.document.getElementById('quick-search-modal').classList.contains('open'), 'Ctrl+K funciona en móvil');
  window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await wait(60);
  assert(!window.document.getElementById('quick-search-modal').classList.contains('open'), 'Escape cierra búsqueda rápida');
  dom.window.close();
  console.log('SMOKE MOBILE OK');
  process.exit(0);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
