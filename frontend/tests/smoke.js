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
const person2 = {
  dni: '87654321', nombres: 'ANA', ap_pat: 'TORRES', ap_mat: 'DIAZ',
  sexo: 'F', edad_anios: 28, fecha_nac: '1996-05-06', est_civil: 'CASADA',
  padre: 'PEDRO TORRES', madre: 'LUCIA DIAZ', direccion: 'CALLE 2',
  ubigeo_dir: '150102', ubigeo_nac: '150102', fch_caducidad: '2031-01-01',
};

function response(status, body, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    headers: { get: (name) => headers[name] || null },
  };
}

function makeDom(url, opts = {}) {
  const dom = new JSDOM(html, {
    url,
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  });
  const { window } = dom;
  if (opts.width) {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: opts.width });
  }
  window.matchMedia = () => ({
    matches: false,
    addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {},
  });
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollIntoView = function () {};
  window.URL.createObjectURL = () => 'blob:test';
  window.URL.revokeObjectURL = () => {};
  if (opts.fastTimeout) {
    const originalSetTimeout = window.setTimeout.bind(window);
    window.setTimeout = (fn, ms, ...args) => originalSetTimeout(fn, ms === 25000 ? 40 : ms, ...args);
  }

  let authenticated = !!opts.authenticated;
  const admin = opts.admin !== false;
  const calls = [];
  window.fetch = async (input, init = {}) => {
    const url = String(input);
    calls.push(url);
    if (url.includes('/api/status')) return response(200, { status: 'ok' });
    if (url.includes('/api/auth/me')) {
      return authenticated
        ? response(200, { username: admin ? 'admin' : 'user', rol: admin ? 'admin' : 'user', consultas_restantes: 99 })
        : response(401, { detail: 'No autenticado' });
    }
    if (url.includes('/api/auth/login')) {
      authenticated = true;
      return response(200, { username: 'admin', rol: 'admin', consultas_restantes: 99 });
    }
    if (url.includes('/api/auth/logout')) return response(200, { ok: true });
    if (url.includes('/api/admin/usuarios')) {
      return response(200, [
        { id: 1, username: 'admin', rol: 'admin', consultas_usadas: 0, consultas_max: 9999, activo: true },
        { id: 2, username: 'operador', rol: 'user', consultas_usadas: 10, consultas_max: 100, activo: true },
      ]);
    }
    if (url.includes('/arbol')) return response(200, { persona: person });
    if (url.includes('/c4')) return response(200, { persona: person });
    if (url.match(/\/persona\/\d{8}(\?|$)/)) {
      const dni = url.match(/\/persona\/(\d{8})/)[1];
      const found = [person, person2].find((p) => p.dni === dni);
      return found ? response(200, found) : response(404, { detail: 'Persona no encontrada' });
    }
    if (url.includes('/buscar')) {
      if (opts.hangSearch) {
        return new Promise((resolve, reject) => {
          const signal = init.signal;
          if (signal) {
            signal.addEventListener('abort', () => {
              const err = new Error('Aborted');
              err.name = 'AbortError';
              reject(err);
            });
          }
        });
      }
      return response(200, [person, person2]);
    }
    return response(404, { detail: 'not found' });
  };
  window.eval(appJs);
  return { dom, window, calls, isAuthenticated: () => authenticated };
}

function wait(ms = 80) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function assert(cond, msg) {
  if (!cond) throw new Error('FALLO: ' + msg);
}

(async () => {
  // 1. Login accesible + panel admin.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/', { authenticated: false });
    await wait(140);
    assert(window.document.querySelector('.skip-link'), 'existe enlace saltar');
    assert(window.document.body.classList.contains('login-visible'), 'body login-visible al iniciar sin sesión');
    assert(window.document.querySelector('.header').hasAttribute('inert'), 'header inert con login');
    assert(window.document.querySelector('.main').hasAttribute('inert'), 'main inert con login');
    assert(window.document.getElementById('login-overlay').getAttribute('aria-hidden') === 'false', 'login aria-hidden false');
    assert(window.document.activeElement === window.document.getElementById('login-user'), 'foco en usuario');
    assert(window.document.getElementById('login-user').getAttribute('autocomplete') === 'username', 'autocomplete usuario');
    assert(window.document.getElementById('login-pass').getAttribute('autocomplete') === 'current-password', 'autocomplete contraseña');

    window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    await wait(120);
    assert(!window.document.getElementById('quick-search-modal').classList.contains('open'), 'Ctrl+K no abre búsqueda sin sesión');
    assert(window.document.activeElement === window.document.getElementById('login-user'), 'atajos no roban el foco del login');

    window.document.getElementById('login-user').value = 'admin';
    window.document.getElementById('login-pass').value = 'secreto';
    window.document.getElementById('login-form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await wait(180);
    assert(!window.document.body.classList.contains('login-visible'), 'login-visible se retira al entrar');
    assert(!window.document.querySelector('.header').hasAttribute('inert'), 'header sin inert tras login');
    assert(!window.document.querySelector('.main').hasAttribute('inert'), 'main sin inert tras login');
    assert(window.document.getElementById('login-overlay').classList.contains('hidden'), 'login oculto');
    assert(window.document.getElementById('login-overlay').hasAttribute('inert'), 'login inert oculto');

    const adminBtn = window.document.getElementById('btn-open-admin');
    assert(!adminBtn.classList.contains('hidden'), 'botón admin visible para admin');
    adminBtn.click();
    await wait(120);
    const overlay = window.document.getElementById('admin-overlay');
    assert(overlay.classList.contains('show'), 'panel admin abierto');
    assert(overlay.getAttribute('aria-hidden') === 'false', 'panel admin aria-hidden false');
    assert(!overlay.hasAttribute('inert'), 'panel admin sin inert');
    assert(adminBtn.getAttribute('aria-expanded') === 'true', 'aria-expanded true');
    assert(window.document.activeElement === window.document.getElementById('btn-close-admin'), 'foco en cerrar panel');

    window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await wait(40);
    assert(!overlay.classList.contains('show'), 'Escape cierra panel admin');
    assert(overlay.getAttribute('aria-hidden') === 'true', 'panel admin aria-hidden true');
    assert(overlay.hasAttribute('inert'), 'panel admin inert al cerrar');
    assert(adminBtn.getAttribute('aria-expanded') === 'false', 'aria-expanded false al cerrar');
    assert(window.document.activeElement === adminBtn, 'foco vuelve al botón admin');
    dom.window.close();
  }

  // 2. Deep link ?dni=, detalle, botón principal y copia de enlace.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/?dni=12345678', { authenticated: true, admin: false });
    await wait(240);
    const input = window.document.getElementById('search-input');
    assert(input.value === '12345678', 'deep link rellena DNI');
    assert(window.document.querySelectorAll('.result-item').length === 1, 'deep link muestra resultado');
    const openBtn = window.document.querySelector('.result-item [data-result-open]');
    assert(openBtn, 'tarjeta expone un botón principal');
    assert(openBtn.getAttribute('aria-current') === 'true', 'resultado activo marcado con aria-current');
    assert(!openBtn.hasAttribute('aria-expanded'), 'escritorio no anuncia expansión en línea');
    assert(openBtn.getAttribute('aria-label').includes('12345678'), 'botón principal incluye el DNI');
    assert(!window.document.querySelector('.result-item').hasAttribute('role'), 'tarjeta ya no simula ser un botón');
    assert(openBtn.querySelectorAll('button, a').length === 0, 'el botón principal no anida controles');
    assert(window.document.querySelector('.result-item__inline-detail').querySelectorAll('button').length === 3, 'acciones fuera del botón principal');
    assert(!window.document.getElementById('detail-content').classList.contains('hidden'), 'detalle visible');
    assert(window.location.search.includes('dni=12345678'), 'URL conserva dni');

    let copied = '';
    Object.defineProperty(window.navigator, 'clipboard', {
      configurable: true,
      value: { writeText: async (text) => { copied = text; } },
    });
    const linkBtn = window.document.getElementById('btn-copy-link');
    assert(linkBtn, 'botón copiar enlace presente');
    linkBtn.click();
    await wait(40);
    assert(copied.includes('dni=12345678'), 'enlace directo copiado con DNI');
    assert(copied.includes('?dni='), 'enlace directo limpio');
    dom.window.close();
  }

  // 3. Historial real + caché local sin repetir cuota.
  {
    const { dom, window, calls } = makeDom('http://127.0.0.1:8000/', { authenticated: true, admin: false });
    await wait(180);
    const input = window.document.getElementById('search-input');
    const btn = window.document.getElementById('btn-search');
    window.document.getElementById('mode-nombre').click();
    const initialLength = window.history.length;

    input.value = 'JUAN PEREZ';
    btn.click();
    await wait(240);
    assert(window.location.search.includes('q=JUAN+PEREZ') || window.location.search.includes('q=JUAN%20PEREZ'), 'URL con primera búsqueda');
    assert(window.history.length > initialLength, 'primera búsqueda crea entrada');
    const busquedas = () => calls.filter((u) => u.includes('/buscar')).length;
    const llamadasIniciales = busquedas();
    assert(llamadasIniciales === 1, 'primera búsqueda llama a la API');
    assert(window.document.getElementById('consultas-count').textContent === '98', 'primera búsqueda descuenta cuota');

    btn.click();
    await wait(180);
    assert(busquedas() === llamadasIniciales, 'búsqueda repetida usa caché local');
    assert(window.document.getElementById('consultas-count').textContent === '98', 'caché local no descuenta cuota');

    input.value = 'ANA TORRES';
    btn.click();
    await wait(240);
    assert(window.location.search.includes('q=ANA+TORRES') || window.location.search.includes('q=ANA%20TORRES'), 'URL con segunda búsqueda');
    const afterSecond = window.history.length;

    window.history.back();
    await wait(280);
    assert(window.document.getElementById('search-input').value === 'JUAN PEREZ', 'atrás restaura primera búsqueda');
    assert(window.history.length === afterSecond, 'atrás no crea entradas');
    assert(busquedas() === 2, 'atrás reutiliza la caché sin nueva consulta');
    dom.window.close();
  }

  // 4. Debounce no contamina el historial.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/', { authenticated: true, admin: false });
    await wait(180);
    const input = window.document.getElementById('search-input');
    window.document.getElementById('mode-nombre').click();
    const initialLength = window.history.length;
    input.value = 'MARIA LOPEZ';
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
    await wait(700);
    assert(window.document.querySelectorAll('.result-item').length === 2, 'debounce muestra resultados');
    assert(window.history.length === initialLength, 'debounce no agrega entradas');
    dom.window.close();
  }

  // 5. Logout limpia resultados, caché y datos locales.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/', { authenticated: true, admin: false });
    await wait(180);
    const input = window.document.getElementById('search-input');
    const btn = window.document.getElementById('btn-search');
    window.document.getElementById('mode-nombre').click();
    input.value = 'JUAN PEREZ';
    btn.click();
    await wait(240);
    assert(window.document.querySelectorAll('.result-item').length === 2, 'resultados antes de logout');
    assert(window.localStorage.getItem('recent_searches'), 'historial local antes de logout');

    window.document.getElementById('btn-logout').click();
    await wait(200);
    assert(window.document.body.classList.contains('login-visible'), 'logout muestra login');
    assert(window.document.querySelector('.header').hasAttribute('inert'), 'header inert tras logout');
    assert(window.document.getElementById('results-list').innerHTML === '', 'resultados eliminados del DOM');
    assert(window.document.getElementById('detail-content').innerHTML === '', 'detalle eliminado del DOM');
    assert(window.document.getElementById('search-input').value === '', 'búsqueda limpiada');
    assert(window.localStorage.getItem('recent_searches') === null, 'historial local eliminado');
    dom.window.close();
  }

  // 6. Búsqueda rápida: combobox, flechas, Enter, selección y caché.
  {
    const { dom, window, calls } = makeDom('http://127.0.0.1:8000/', { authenticated: true, admin: false });
    await wait(180);
    window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    await wait(140);
    const qsInput = window.document.getElementById('quick-search-input');
    const qsResults = window.document.getElementById('quick-search-results');
    assert(window.document.getElementById('quick-search-modal').classList.contains('open'), 'Ctrl+K abre búsqueda rápida');
    assert(qsInput.getAttribute('aria-expanded') === 'true', 'combobox expandido');
    assert(qsResults.getAttribute('role') === 'listbox', 'resultados con rol listbox');
    assert(qsInput.getAttribute('aria-controls') === 'quick-search-results', 'combobox controla resultados');

    qsInput.value = 'JUAN';
    qsInput.dispatchEvent(new window.Event('input', { bubbles: true }));
    await wait(440);
    const options = qsResults.querySelectorAll('.qs-item');
    assert(options.length === 2, 'búsqueda rápida muestra resultados');
    assert(options[0].getAttribute('role') === 'option', 'opciones con rol option');
    assert(options[0].getAttribute('aria-selected') === 'false', 'opción inactiva al inicio');

    qsInput.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    assert(options[0].classList.contains('qs-item--active'), 'flecha abajo activa primera opción');
    assert(qsInput.getAttribute('aria-activedescendant') === 'qs-opt-0', 'activedescendant primera opción');

    qsInput.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    assert(options[1].classList.contains('qs-item--active'), 'segunda flecha activa segunda opción');
    assert(options[1].getAttribute('aria-selected') === 'true', 'segunda opción seleccionada');

    qsInput.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await wait(240);
    assert(!window.document.getElementById('quick-search-modal').classList.contains('open'), 'Enter cierra búsqueda rápida');
    assert(window.document.getElementById('search-input').value === 'JUAN', 'Enter traslada la consulta');
    assert(window.location.search.includes('q=JUAN'), 'Enter actualiza la URL');
    const detail = window.document.getElementById('detail-content').textContent;
    assert(detail.includes('ANA') || detail.includes('87654321'), 'detalle corresponde a la opción elegida');
    assert(calls.filter((u) => u.includes('/api/auth/me')).length >= 2, 'cuota sincronizada al cerrar');

    const busquedasQs = calls.filter((u) => u.includes('/buscar')).length;
    window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    await wait(140);
    const qsInput2 = window.document.getElementById('quick-search-input');
    qsInput2.value = 'JUAN';
    qsInput2.dispatchEvent(new window.Event('input', { bubbles: true }));
    await wait(440);
    assert(calls.filter((u) => u.includes('/buscar')).length === busquedasQs, 'búsqueda rápida repetida usa caché local');
    window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await wait(60);
    dom.window.close();
  }

  // 7. Móvil: vista tabla abre el bottom sheet y lo cierra.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/?dni=12345678', { authenticated: true, admin: false, width: 390 });
    await wait(260);
    window.document.getElementById('btn-view-table').click();
    await wait(120);
    const row = window.document.querySelector('.result-row');
    assert(row, 'vista tabla renderiza filas en móvil');
    row.click();
    await wait(160);
    assert(row.getAttribute('aria-current') === 'true', 'fila activa marcada con aria-current');
    assert(!row.hasAttribute('aria-selected'), 'fila no usa aria-selected inválido');
    const sheet = window.document.getElementById('mobile-sheet');
    assert(sheet.classList.contains('open'), 'bottom sheet abierto');
    assert(sheet.getAttribute('aria-hidden') === 'false', 'sheet aria-hidden false');
    assert(sheet.getAttribute('aria-label').includes('JUAN CARLOS'), 'sheet anuncia el nombre del titular');
    assert(sheet.getAttribute('aria-label').includes('12345678'), 'sheet anuncia el DNI del titular');
    assert(window.document.getElementById('mobile-sheet-content').textContent.includes('JUAN'), 'sheet muestra la persona');
    sheet.querySelector('.sheet__close').click();
    await wait(120);
    assert(!sheet.classList.contains('open'), 'bottom sheet cerrado');
    assert(sheet.getAttribute('aria-hidden') === 'true', 'sheet aria-hidden true al cerrar');
    dom.window.close();
  }

  // 8. Timeout de búsqueda: mensaje claro y sin resultados viejos.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/', {
      authenticated: true, admin: false, fastTimeout: true, hangSearch: true,
    });
    await wait(180);
    window.document.getElementById('mode-nombre').click();
    const input = window.document.getElementById('search-input');
    input.value = 'JUAN PEREZ';
    window.document.getElementById('btn-search').click();
    await wait(180);
    assert(window.document.getElementById('estado-texto').textContent.includes('tardó demasiado'), 'timeout muestra mensaje');
    assert(window.document.getElementById('results-list').innerHTML === '', 'timeout no deja resultados viejos');
    assert(window.document.getElementById('results-section').getAttribute('aria-busy') === 'false', 'timeout libera aria-busy');
    dom.window.close();
  }

  // 9. Cabecera de cuota: saldo exacto sin petición extra a /api/auth/me.
  {
    const { dom, window, calls } = makeDom('http://127.0.0.1:8000/', { authenticated: true, admin: false });
    const baseFetch = window.fetch;
    window.fetch = async (input, init) => {
      const res = await baseFetch(input, init);
      const url = String(input);
      if (url.includes('/buscar') || /\/persona\/\d{8}/.test(url)) {
        res.headers = {
          get: (name) => name === 'X-Consultas-Restantes' ? '77' : null,
        };
      }
      return res;
    };
    await wait(180);
    window.document.getElementById('mode-nombre').click();
    const input = window.document.getElementById('search-input');
    input.value = 'JUAN PEREZ';
    window.document.getElementById('btn-search').click();
    await wait(240);
    assert(window.document.getElementById('consultas-count').textContent === '77', 'cabecera sincroniza saldo exacto');
    assert(window.document.getElementById('consultas-badge').getAttribute('aria-label') === 'Consultas disponibles: 77', 'badge anuncia el saldo');

    const meCalls = calls.filter((u) => u.includes('/api/auth/me')).length;
    window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    await wait(140);
    const qsInput = window.document.getElementById('quick-search-input');
    qsInput.value = 'JUAN';
    qsInput.dispatchEvent(new window.Event('input', { bubbles: true }));
    await wait(440);
    assert(window.document.getElementById('consultas-count').textContent === '77', 'búsqueda rápida usa la cabecera');
    window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await wait(80);
    assert(calls.filter((u) => u.includes('/api/auth/me')).length === meCalls, 'no hay petición extra de cuota');
    dom.window.close();
  }

  // 10. Búsqueda sin coincidencias: también sincroniza la cuota consumida.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/', { authenticated: true, admin: false });
    const baseFetch = window.fetch;
    window.fetch = async (input, init) => {
      const url = String(input);
      if (url.includes('/buscar')) return response(200, [], { 'X-Consultas-Restantes': '76' });
      return baseFetch(input, init);
    };
    await wait(180);
    window.document.getElementById('mode-nombre').click();
    window.document.getElementById('search-input').value = 'ZZZZ';
    window.document.getElementById('btn-search').click();
    await wait(240);
    assert(window.document.getElementById('results-list').textContent.includes('No se encontraron registros'), 'estado vacío visible');
    assert(window.document.getElementById('consultas-count').textContent === '76', 'búsqueda vacía sincroniza cuota');
    dom.window.close();
  }

  // 11. Logout cancela una búsqueda en vuelo: no repinta datos ni cuota.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/', { authenticated: true, admin: false });
    const baseFetch = window.fetch;
    window.fetch = (input, init = {}) => {
      const url = String(input);
      if (url.includes('/buscar')) {
        return new Promise((resolve, reject) => {
          const timer = setTimeout(
            () => resolve(response(200, [person, person2], { 'X-Consultas-Restantes': '55' })),
            180,
          );
          if (init.signal) {
            init.signal.addEventListener('abort', () => {
              clearTimeout(timer);
              const err = new Error('Aborted');
              err.name = 'AbortError';
              reject(err);
            });
          }
        });
      }
      return baseFetch(input, init);
    };
    await wait(180);
    window.document.getElementById('mode-nombre').click();
    window.document.getElementById('search-input').value = 'JUAN PEREZ';
    window.document.getElementById('btn-search').click();
    await wait(30);
    window.document.getElementById('btn-logout').click();
    await wait(320);
    assert(window.document.body.classList.contains('login-visible'), 'logout muestra login');
    assert(window.document.getElementById('results-list').innerHTML === '', 'respuesta tardía no repinta resultados');
    assert(window.document.querySelectorAll('.result-item').length === 0, 'sin tarjetas tras logout');
    assert(window.document.getElementById('consultas-count').textContent !== '55', 'respuesta tardía no repinta cuota');
    dom.window.close();
  }

  // 12. RUC sincroniza la cuota desde la cabecera y la agota en 403.
  {
    const { dom, window } = makeDom('http://127.0.0.1:8000/?dni=12345678', { authenticated: true, admin: false });
    const baseFetch = window.fetch;
    let rucStatus = 'ok';
    window.fetch = async (input, init) => {
      const url = String(input);
      if (url.includes('/scraping/ruc/')) {
        if (rucStatus === 'ok') {
          return response(200, {
            tiene_ruc: true,
            ruc: '10123456785',
            razon_social: 'PEREZ GOMEZ JUAN CARLOS',
            estado: 'ACTIVO',
            condicion: 'HABIDO',
          }, { 'X-Consultas-Restantes': '41' });
        }
        return response(403, { detail: 'Sin consultas disponibles' });
      }
      return baseFetch(input, init);
    };
    await wait(260);
    const rucBtn = window.document.getElementById('btn-consultar-ruc');
    assert(rucBtn, 'botón de consulta RUC presente');
    rucBtn.click();
    await wait(160);
    assert(window.document.getElementById('consultas-count').textContent === '41', 'RUC sincroniza cuota desde cabecera');
    assert(window.document.getElementById('ruc-resultado').textContent.includes('PEREZ GOMEZ'), 'RUC muestra razón social');

    rucStatus = '403';
    rucBtn.click();
    await wait(160);
    assert(window.document.getElementById('consultas-count').textContent === '0', 'RUC sin cuota marca cero');
    assert(window.document.getElementById('ruc-resultado').textContent.includes('Sin consultas disponibles'), 'RUC muestra aviso de cuota');
    dom.window.close();
  }

  // 13. Árbol y C4 sincronizan cuota sin pedir /api/auth/me de nuevo.
  {
    const { dom, window, calls } = makeDom('http://127.0.0.1:8000/?dni=12345678', { authenticated: true, admin: false });
    const baseFetch = window.fetch;
    window.fetch = async (input, init) => {
      const url = String(input);
      const res = await baseFetch(input, init);
      if (url.includes('/arbol') || url.includes('/c4')) {
        const restantes = url.includes('/arbol') ? '39' : '38';
        res.headers = { get: (name) => name === 'X-Consultas-Restantes' ? restantes : null };
      }
      return res;
    };
    await wait(260);
    const meCalls = () => calls.filter((u) => u.includes('/api/auth/me')).length;
    const before = meCalls();

    window.document.getElementById('btn-tree').click();
    await wait(180);
    assert(window.document.getElementById('tree-modal').classList.contains('open'), 'árbol abierto');
    assert(window.document.getElementById('consultas-count').textContent === '39', 'árbol sincroniza cuota');
    window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await wait(60);

    window.document.getElementById('btn-c4-direct').click();
    await wait(180);
    assert(window.document.getElementById('c4-modal').classList.contains('open'), 'C4 abierto');
    assert(window.document.getElementById('consultas-count').textContent === '38', 'C4 sincroniza cuota');
    assert(meCalls() === before, 'árbol y C4 no piden /api/auth/me extra');
    dom.window.close();
  }

  console.log('SMOKE OK');
  process.exit(0);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
