(function () {
  'use strict';

  /* ── Config ──────────────────────────────────────────────── */
  // La API se sirve siempre desde el mismo origen (Nginx hace el proxy).
  // Evita CORS, cookies de terceros y mezclas de esquema http/https.
  const API_BASE = window.location.origin;

  /* ── Auth State ──────────────────────────────────────────── */
  // El JWT vive únicamente en una cookie HttpOnly; el frontend nunca lo lee
  // ni lo guarda. Solo mantiene datos de presentación en memoria.
  let _userRol = null;
  let _username = null;
  let _consultasRestantes = 0;
  let _authenticated = false;

  function apiHeaders(extra) {
    return extra || {};
  }

  function applySession(data) {
    _username = data.username || null;
    _userRol = data.rol || null;
    _consultasRestantes = Number.isFinite(Number(data.consultas_restantes))
      ? Number(data.consultas_restantes)
      : 0;
    _authenticated = !!_username;
  }

  function clearAuth() {
    _userRol = null; _username = null; _consultasRestantes = 0; _authenticated = false;
  }

  function clearLegacyAuthStorage() {
    // Migración: versiones anteriores guardaban el JWT en localStorage.
    ['jwt_token', 'user_rol', 'username', 'consultas_restantes'].forEach((k) => {
      try { localStorage.removeItem(k); } catch { /* almacenamiento no disponible */ }
    });
  }

  function isLoggedIn() { return _authenticated; }

  async function apiFetch(url, options) {
    const opts = Object.assign({ credentials: 'include' }, options || {});
    const res = await fetch(url, opts);
    if (res.status === 401 && !String(url).includes('/api/auth/login')) {
      showLoginScreen();
    }
    return res;
  }


  /* ── DOM refs ────────────────────────────────────────────── */
  const $ = (id) => document.getElementById(id);
  const appHeader         = document.querySelector('.header');
  const appMain           = document.querySelector('.main');
  const searchInput       = $('search-input');
  const btnClearSearch    = $('btn-clear-search');
  const modeDni           = $('mode-dni');
  const modeNombre        = $('mode-nombre');
  const limitRow          = $('limit-row');
  const limiteSelect      = $('limite');
  const resultsSection    = $('results-section');
  const resultsList       = $('results-list');
  const resultsGrid       = $('results-grid');
  const badgeCount        = $('badge-count');
  const estadoTexto       = $('estado-texto');
  const btnExportar       = $('btn-exportar');
  const btnExportarJson   = $('btn-exportar-json');
  const btnViewList       = $('btn-view-list');
  const btnViewTable      = $('btn-view-table');
  const btnToggleDetail   = $('btn-toggle-detail');
  const detailPanel       = $('detail-panel');
  const detailResizer     = $('detail-resizer');
  const detailEmpty       = $('detail-empty');
  const detailContent     = $('detail-content');
  const emptyState        = $('empty-state');
  const connectionStatus  = $('connection-status');
  const toastContainer    = $('toast-container');
  const qsModal           = $('quick-search-modal');
  const qsInput           = $('quick-search-input');
  const qsResults         = $('quick-search-results');
  const mobileSheet       = $('mobile-sheet');
  const mobileSheetOverlay = $('mobile-sheet-overlay');
  const mobileSheetContent = $('mobile-sheet-content');
  const treeModal          = $('tree-modal');
  const treeViewport       = $('tree-viewport');
  const treeCanvas         = $('tree-canvas');
  const treeContainer      = $('tree-container');
  const treeTitularBadge   = $('tree-titular-badge');
  const treeStatsBar       = $('tree-stats-bar');
  const treeZoomLabel      = $('tree-zoom-label');
  const btnTreeZoomIn      = $('btn-tree-zoom-in');
  const btnTreeZoomOut     = $('btn-tree-zoom-out');
  const btnTreeReset       = $('btn-tree-reset');
  const btnTreeDownload    = $('btn-tree-download');
  const btnTreeViewGraph   = $('btn-tree-view-graph');
  const btnTreeViewList    = $('btn-tree-view-list');
  const c4Modal            = $('c4-modal');
  const c4Container        = $('c4-container');
  const btnCloseC4         = $('btn-close-c4');
  const btnPrintC4         = $('btn-print-c4');
  const btnThemeToggle     = $('btn-theme-toggle');
  const dniCounter         = $('dni-counter');
  const modeGlider         = $('mode-glider');
  const searchHistoryEl    = $('search-history');
  const searchHistoryChipsEl = $('search-history-chips');
  const btnClearHistoryEl  = $('btn-clear-history');

  /* ── Theme Management ────────────────────────────────────── */
  function getTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
  }

  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) {
      metaTheme.setAttribute('content', theme === 'light' ? '#f8fafc' : '#070709');
    }
  }

  function toggleTheme() {
    const current = getTheme();
    const next = current === 'light' ? 'dark' : 'light';
    setTheme(next);
    toast(next === 'light' ? 'Modo claro activado' : 'Modo oscuro activado', 'info');
  }

  if (btnThemeToggle) {
    btnThemeToggle.addEventListener('click', toggleTheme);
  }

  let resultados = [];
  let personaSeleccionada = null;
  let searchMode = 'dni';
  let abortCtrl = null;
  let debounce = null;
  let qsTimer = null;
  let qsAbort = null;

  // Tree graph interactive pan & zoom state
  let treeZoom = 1.0;
  let treePanX = 0;
  let treePanY = 0;
  let isDraggingTree = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let initialPinchDist = null;
  let initialPinchZoom = 1.0;

  // Resultados: vista, orden y panel de detalle
  let resultadosVista = [];
  let resultsSort = { key: '', dir: 1 };
  let resultsView = 'list';
  let detailCollapsed = false;
  let detailWidth = 430;
  let detailRenderToken = 0;
  let swRefreshing = false;

  // Búsquedas: caché en memoria para atrás/adelante sin repetir consultas.
  const SEARCH_CACHE_TTL = 5 * 60 * 1000;
  const SEARCH_CACHE_MAX = 40;
  const searchCache = new Map();

  // Árbol: caché, render progresivo y vista lista
  const TREE_CACHE_TTL = 5 * 60 * 1000;
  const treeCache = new Map();
  let treeData = null;
  let treeRootDni = null;
  let treeView = window.innerWidth <= 768 ? 'list' : 'graph';
  let treeListTab = 'padres';
  let treeNeedsFit = false;
  let treeVisible = { hermanos: 12, hijos: 12, probables: 8, hijosProbables: 8 };
  let treeRequestToken = 0;
  let c4RequestToken = 0;
  let lastFocusedElement = null;
  let lastFocusedC4 = null;
  let lastFocusedQS = null;
  let lastFocusedAdmin = null;

  function updateBodyScrollLock() {
    const adminEl = document.getElementById('admin-overlay');
    const anyOpen = [treeModal, c4Modal, qsModal, mobileSheet]
      .some((el) => el && el.classList.contains('open')) ||
      (adminEl && adminEl.classList.contains('show'));
    document.body.style.overflow = anyOpen ? 'hidden' : '';
  }

  try {
    const savedView = localStorage.getItem('results_view');
    if (savedView === 'table' || savedView === 'list') resultsView = savedView;
    const savedDetail = localStorage.getItem('detail_collapsed');
    if (savedDetail === '1') detailCollapsed = true;
    const savedWidth = parseInt(localStorage.getItem('detail_width') || '', 10);
    if (Number.isFinite(savedWidth)) detailWidth = Math.min(640, Math.max(320, savedWidth));
    const savedTreeView = localStorage.getItem('tree_view');
    if (savedTreeView === 'list' || savedTreeView === 'graph') treeView = savedTreeView;
  } catch { /* almacenamiento no disponible */ }

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function isTypingTarget(target) {
    if (!target) return false;
    const tag = target.tagName ? target.tagName.toLowerCase() : '';
    return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable;
  }

  function scrollBehavior() {
    return prefersReducedMotion() ? 'auto' : 'smooth';
  }

  function activeModalElement() {
    if (c4Modal && c4Modal.classList.contains('open')) return c4Modal.querySelector('.c4-panel');
    if (treeModal && treeModal.classList.contains('open')) return treeModal.querySelector('.tree-panel');
    if (qsModal && qsModal.classList.contains('open')) return qsModal.querySelector('.qs-panel');
    if (mobileSheet && mobileSheet.classList.contains('open')) return mobileSheet;
    const adminEl = document.getElementById('admin-overlay');
    if (adminEl && adminEl.classList.contains('show')) return adminEl.querySelector('.admin-panel');
    return null;
  }

  function trapFocus(e, container) {
    if (!container) return;
    const selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusables = Array.from(container.querySelectorAll(selector))
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first || !container.contains(document.activeElement)) {
        e.preventDefault();
        last.focus();
      }
    } else if (document.activeElement === last || !container.contains(document.activeElement)) {
      e.preventDefault();
      first.focus();
    }
  }

  /* ── Helpers ─────────────────────────────────────────────── */
  function nombre(p) {
    return [p.nombres, p.ap_pat, p.ap_mat].filter(Boolean).join(' ').trim();
  }
  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  function copyText(text) {
    const value = String(text == null ? '' : text);
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      return navigator.clipboard.writeText(value);
    }
    return new Promise((resolve, reject) => {
      const area = document.createElement('textarea');
      area.value = value;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try {
        const ok = document.execCommand('copy');
        area.remove();
        if (ok) resolve();
        else reject(new Error('No se pudo copiar'));
      } catch (error) {
        area.remove();
        reject(error);
      }
    });
  }
  function sexoLetra(s) {
    const t = (s || '').trim().toUpperCase();
    if (t === 'MASCULINO' || t === 'M' || t === '1') return 'M';
    if (t === 'FEMENINO' || t === 'F' || t === '2') return 'F';
    return '';
  }
  function dniDisplay(p) {
    return escHtml(p.dni || '-') + (p.dig_ruc ? ` (DV: ${escHtml(p.dig_ruc)})` : '');
  }
  function rucDisplay(p) {
    if (!p.dni) return '-';
    return `10${p.dni}${p.dig_ruc || ''}`;
  }

  /* ── Animated Counter ─────────────────────────────────────── */
  function animateValue(el, start, end, duration) {
    if (start === end || prefersReducedMotion()) { el.textContent = end; return; }
    const range = end - start;
    const startTime = performance.now();
    function step(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.floor(start + range * eased);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function bumpBadge(el) {
    el.classList.remove('bump');
    void el.offsetWidth;
    el.classList.add('bump');
  }

  /* ── Ripple Effect ──────────────────────────────────────── */
  function addRipple(e, target) {
    if (prefersReducedMotion()) return;
    const btn = target || e.currentTarget;
    const rect = btn.getBoundingClientRect();
    const ripple = document.createElement('span');
    ripple.className = 'ripple-effect';
    const size = Math.max(rect.width, rect.height);
    ripple.style.width = ripple.style.height = size + 'px';
    ripple.style.left = (e.clientX - rect.left - size / 2) + 'px';
    ripple.style.top = (e.clientY - rect.top - size / 2) + 'px';
    btn.appendChild(ripple);
    ripple.addEventListener('animationend', () => ripple.remove());
  }

  /* ── Parallax Blobs ────────────────────────────────────── */
  function initParallax() {
    const blobs = document.querySelectorAll('.bg-blob');
    if (!blobs.length) return;
    if (window.matchMedia('(hover: none)').matches || prefersReducedMotion()) return;
    let ticking = false;
    document.addEventListener('mousemove', (e) => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const cx = (e.clientX / window.innerWidth - 0.5) * 2;
        const cy = (e.clientY / window.innerHeight - 0.5) * 2;
        blobs[0].style.transform = `translate(${cx * 15}px, ${cy * 10}px)`;
        if (blobs[1]) blobs[1].style.transform = `translate(${cx * -10}px, ${cy * 12}px)`;
        if (blobs[2]) blobs[2].style.transform = `translate(${cx * 8}px, ${cy * -8}px)`;
        ticking = false;
      });
    });
  }

  /* ── Toast ───────────────────────────────────────────────── */
  const TOAST_ICONS = { info: 'info', success: 'check_circle', error: 'error', warn: 'warning' };

  function toast(msg, type = 'info', opts = {}) {
    const el = document.createElement('div');
    el.className = `toast toast--${type}`;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    const icon = document.createElement('span');
    icon.className = 'material-symbols-outlined';
    icon.textContent = TOAST_ICONS[type] || TOAST_ICONS.info;
    const text = document.createElement('span');
    text.className = 'toast__text';
    text.textContent = String(msg == null ? '' : msg);
    el.append(icon, text);

    let actionBtn = null;
    if (opts.actionLabel && typeof opts.onAction === 'function') {
      actionBtn = document.createElement('button');
      actionBtn.className = 'toast__action';
      actionBtn.type = 'button';
      actionBtn.textContent = opts.actionLabel;
      actionBtn.addEventListener('click', () => {
        try { opts.onAction(); } finally { removeToast(); }
      });
      el.appendChild(actionBtn);
    }

    toastContainer.appendChild(el);
    let removed = false;
    function removeToast() {
      if (removed) return;
      removed = true;
      el.style.opacity = '0';
      el.style.transform = 'translateX(20px)';
      setTimeout(() => el.remove(), 300);
    }
    const duration = Number.isFinite(opts.duration) ? opts.duration : (actionBtn ? 12000 : 3500);
    setTimeout(removeToast, duration);
  }

  /* ── Connection check ────────────────────────────────────── */
  async function checkConnection() {
    const c = new AbortController();
    const t = setTimeout(() => c.abort(), 3000);
    let ok = false;
    try {
      const res = await apiFetch(`${API_BASE}/api/status`, { signal: c.signal });
      ok = res.ok;
    } catch {
      ok = false;
    } finally {
      clearTimeout(t);
    }
    connectionStatus.innerHTML = ok
      ? '<span class="status-dot status-dot--online"></span><span class="status-label">Online</span>'
      : '<span class="status-dot status-dot--offline"></span><span class="status-label">Offline</span>';
    connectionStatus.className = ok ? 'connection-status' : 'connection-status connection-status--offline';
  }

  /* ── Recent Searches Management ───────────────────────────── */
  function addRecentSearch(query, mode) {
    if (!query) return;
    try {
      let recents = JSON.parse(localStorage.getItem('recent_searches') || '[]');
      recents = recents.filter(item => item.query !== query);
      recents.unshift({ query, mode, time: Date.now() });
      if (recents.length > 5) recents = recents.slice(0, 5);
      localStorage.setItem('recent_searches', JSON.stringify(recents));
      renderRecentSearches();
    } catch {}
  }

  function renderRecentSearches() {
    if (!searchHistoryEl || !searchHistoryChipsEl) return;
    try {
      const recents = JSON.parse(localStorage.getItem('recent_searches') || '[]');
      if (recents.length === 0) {
        searchHistoryEl.classList.add('hidden');
        return;
      }
      searchHistoryChipsEl.innerHTML = recents.map(r => `
        <button class="history-chip" data-query="${escHtml(r.query)}" data-mode="${escHtml(r.mode)}" title="Buscar ${escHtml(r.query)}">
          <span aria-hidden="true">${r.mode === 'dni' ? '🆔' : '👤'}</span>
          <span>${escHtml(r.query)}</span>
        </button>
      `).join('');
      searchHistoryEl.classList.remove('hidden');

      searchHistoryChipsEl.querySelectorAll('.history-chip').forEach(btn => {
        btn.addEventListener('click', () => {
          const q = btn.getAttribute('data-query');
          const m = btn.getAttribute('data-mode') || 'dni';
          setMode(m);
          searchInput.value = q;
          btnClearSearch.classList.add('visible');
          if (m === 'dni' && dniCounter) {
            dniCounter.textContent = `${q.length}/8`;
            dniCounter.classList.toggle('hidden', q.length === 0);
            dniCounter.classList.toggle('dni-counter--valid', q.length === 8);
          }
          search();
        });
      });
    } catch {}
  }

  if (btnClearHistoryEl) {
    btnClearHistoryEl.addEventListener('click', () => {
      localStorage.removeItem('recent_searches');
      renderRecentSearches();
      toast('Historial reciente borrado', 'normal');
    });
  }

  // Render on startup
  renderRecentSearches();

  /* ── Mode switching ──────────────────────────────────────── */
  function setMode(mode, focus = true) {
    searchMode = mode;
    searchInput.placeholder = mode === 'dni' ? 'Escribe un DNI (8 dígitos)...' : 'Escribe apellidos o nombres completos...';
    if (mode === 'dni') {
      searchInput.setAttribute('inputmode', 'numeric');
      searchInput.setAttribute('pattern', '[0-9]*');
      if (dniCounter) {
        const len = searchInput.value.length;
        dniCounter.textContent = `${len}/8`;
        dniCounter.classList.toggle('hidden', len === 0);
        dniCounter.classList.toggle('dni-counter--valid', len === 8);
      }
    } else {
      searchInput.setAttribute('inputmode', 'text');
      searchInput.removeAttribute('pattern');
      if (dniCounter) dniCounter.classList.add('hidden');
    }
    modeDni.classList.toggle('mode-btn--active', mode === 'dni');
    modeNombre.classList.toggle('mode-btn--active', mode === 'nombre');
    if (modeGlider) {
      modeGlider.classList.toggle('mode-glider--nombre', mode === 'nombre');
    }
    limitRow.classList.toggle('visible', mode === 'nombre');
    if (focus) searchInput.focus();
  }

  modeDni.addEventListener('click', () => { setMode('dni'); if (searchInput.value.trim()) search(); });
  modeNombre.addEventListener('click', () => { setMode('nombre'); if (searchInput.value.trim()) search(); });

  /* ── Status & loading ────────────────────────────────────── */
  function setEstado(t, type = 'normal') {
    estadoTexto.textContent = t;
    estadoTexto.className = `status-text${type === 'error' ? ' status-text--error' : type === 'ok' ? ' status-text--ok' : ''}`;
    estadoTexto.style.opacity = '1';
  }

  function setLoading(l) {
    searchInput.disabled = l;
  }

  /* ── Skeleton ────────────────────────────────────────────── */
  function skeleton() {
    let html = '';
    for (let i = 0; i < 6; i++) {
      html += `<div class="result-item fade-in stagger-${i + 1}">
        <div class="result-item__inner">
          <div class="skeleton" style="width:46px;height:46px;border-radius:14px;flex-shrink:0"></div>
          <div style="flex:1;display:flex;flex-direction:column;gap:8px">
            <div class="skeleton" style="height:16px;width:65%"></div>
            <div class="skeleton" style="height:12px;width:35%"></div>
          </div>
          <div class="skeleton" style="width:24px;height:12px"></div>
        </div>
      </div>`;
    }
    resultsList.innerHTML = html;
  }

  /* ── Render results: tarjetas y tabla ─────────────────────── */
  const RESULT_SORT_ACCESSORS = {
    nombre: (p) => nombre(p).toLowerCase(),
    dni: (p) => String(p.dni || ''),
    edad: (p) => Number(p.edad_anios) || -1,
    ubigeo: (p) => String(p.ubigeo_dir || p.ubigeo_nac || '').toLowerCase(),
    sexo: (p) => String(p.sexo || '').toLowerCase(),
    civil: (p) => String(p.est_civil || '').toLowerCase(),
  };

  function sortResults(data) {
    const arr = (data || []).slice();
    const accessor = RESULT_SORT_ACCESSORS[resultsSort.key];
    if (!accessor) return arr;
    arr.sort((a, b) => {
      const va = accessor(a);
      const vb = accessor(b);
      if (va < vb) return -1 * resultsSort.dir;
      if (va > vb) return 1 * resultsSort.dir;
      return 0;
    });
    return arr;
  }

  function initialsFor(p) {
    const primerNombre = (p.nombres || '').trim().split(/\s+/)[0] || '';
    const primerApe = (p.ap_pat || '').trim() || '';
    return ((primerNombre[0] || '') + (primerApe[0] || '')).toUpperCase() || (sexoLetra(p.sexo) === 'F' ? 'F' : 'M');
  }

  function resultItemHtml(p, i, busqueda) {
    const n = nombre(p);
    let nHtml = escHtml(n || '-');
    if (busqueda && n) {
      const safe = busqueda.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const re = new RegExp(`(${safe})`, 'gi');
      nHtml = escHtml(n).replace(re, '<mark>$1</mark>');
    }
    const g = sexoLetra(p.sexo);
    const active = personaSeleccionada && personaSeleccionada.dni === p.dni ? ' result-item--active' : '';
    const iniciales = initialsFor(p);
    const avatarGenderClass = g === 'F' ? 'result-item__avatar--female' : 'result-item__avatar--male';

    let vigenciaBadge = '';
    if (p.fch_caducidad) {
      const isVencido = new Date(p.fch_caducidad) < new Date();
      vigenciaBadge = isVencido
        ? '<span class="badge-mini badge-mini--expired">Caducado</span>'
        : '<span class="badge-mini badge-mini--valid">Vigente</span>';
    }
    const edadBadge = p.edad_anios != null ? `<span class="badge-mini badge-mini--age">${p.edad_anios} años</span>` : '';
    const civilBadge = p.est_civil ? `<span class="badge-mini">${escHtml(p.est_civil)}</span>` : '';

    const fechaNac = p.fecha_nac ? `${escHtml(p.fecha_nac)} (${p.edad_anios || '-'} años)` : '-';
    const padres = [p.padre ? `P: ${p.padre}` : '', p.madre ? `M: ${p.madre}` : ''].filter(Boolean).join(' · ') || 'No registrados';
    const ubigeoDir = p.ubigeo_dir || p.ubigeo_nac || '-';
    const anim = i < 8 ? ` slide-up stagger-${i + 1}` : '';

    return `<div class="result-item${anim}${active}" data-index="${i}" data-dni="${escHtml(p.dni || '')}" role="button" tabindex="0" aria-expanded="${active ? 'true' : 'false'}" aria-label="${escHtml(n || 'Persona')}, DNI ${escHtml(p.dni || '-')}">
      <div class="result-item__inner">
        <div class="result-item__avatar ${avatarGenderClass}" title="${g === 'F' ? 'Femenino' : 'Masculino'}">
          <span class="result-avatar-text">${escHtml(iniciales)}</span>
        </div>
        <div class="result-item__body">
          <p class="result-item__name">${nHtml}</p>
          <div class="result-item__meta">
            <span class="result-item__dni">DNI ${escHtml(p.dni || '-')}</span>
            ${vigenciaBadge}
            ${edadBadge}
            ${civilBadge}
          </div>
        </div>
        <span class="material-symbols-outlined result-item__chevron" aria-hidden="true">chevron_right</span>
      </div>
      ${p.direccion ? `<p class="result-item__address"><span class="material-symbols-outlined" aria-hidden="true">location_on</span>${escHtml(p.direccion)}</p>` : ''}

      <div class="result-item__inline-detail">
        <div class="result-inline-data">
          <div><strong>Nacimiento:</strong> ${fechaNac}</div>
          <div><strong>Padres:</strong> ${escHtml(padres)}</div>
          <div><strong>Ubigeo:</strong> ${escHtml(ubigeoDir)}</div>
        </div>
        <div class="inline-actions-grid">
          <button class="btn-inline-action btn-inline-action--primary" data-inline-action="tree" data-dni="${escHtml(p.dni)}">
            <span class="material-symbols-outlined" style="font-size:15px" aria-hidden="true">account_tree</span>
            <span>Árbol</span>
          </button>
          <button class="btn-inline-action btn-inline-action--c4" data-inline-action="c4" data-dni="${escHtml(p.dni)}" title="Ficha de referencia (no oficial)">
            <span class="material-symbols-outlined" style="font-size:15px" aria-hidden="true">print</span>
            <span>C4</span>
          </button>
          <button class="btn-inline-action" data-inline-action="copy" data-index="${i}">
            <span class="material-symbols-outlined" style="font-size:15px" aria-hidden="true">content_copy</span>
            <span>Copiar</span>
          </button>
        </div>
      </div>
    </div>`;
  }

  function sortIcon(key) {
    if (resultsSort.key !== key) return 'unfold_more';
    return resultsSort.dir > 0 ? 'arrow_upward' : 'arrow_downward';
  }

  function resultsTableHtml(data, busqueda) {
    if (!data.length) {
      return '<div class="results-table-wrap"><p class="table-empty">No se encontraron registros</p></div>';
    }
    const headers = [
      ['nombre', 'Nombre'],
      ['dni', 'DNI'],
      ['edad', 'Edad'],
      ['sexo', 'Sexo'],
      ['ubigeo', 'Ubigeo'],
      ['civil', 'Estado civil'],
    ];
    const head = headers.map(([key, label]) => `
      <th scope="col" aria-sort="${resultsSort.key === key ? (resultsSort.dir > 0 ? 'ascending' : 'descending') : 'none'}">
        <button type="button" data-sort="${key}">
          ${label}
          <span class="material-symbols-outlined" aria-hidden="true">${sortIcon(key)}</span>
        </button>
      </th>`).join('');

    const rows = data.map((p, i) => {
      const n = nombre(p) || '-';
      const g = sexoLetra(p.sexo);
      const active = personaSeleccionada && personaSeleccionada.dni === p.dni ? ' result-row--active' : '';
      const iniciales = initialsFor(p);
      return `<tr class="result-row${active}" data-index="${i}" data-dni="${escHtml(p.dni || '')}" tabindex="0" role="row" aria-selected="${active ? 'true' : 'false'}" aria-label="${escHtml(n)}, DNI ${escHtml(p.dni || '-')}">
        <td class="result-cell--name"><span class="table-avatar" aria-hidden="true">${escHtml(iniciales)}</span>${escHtml(n)}</td>
        <td class="result-cell--dni">${escHtml(p.dni || '-')}</td>
        <td>${p.edad_anios != null ? escHtml(p.edad_anios) + ' años' : '-'}</td>
        <td>${g === 'F' ? 'Femenino' : g === 'M' ? 'Masculino' : '-'}</td>
        <td>${escHtml(p.ubigeo_dir || p.ubigeo_nac || '-')}</td>
        <td>${escHtml(p.est_civil || '-')}</td>
      </tr>`;
    }).join('');

    return `<div class="results-table-wrap">
      <table class="results-table">
        <caption class="sr-only">Resultados de búsqueda. Usa las cabeceras para ordenar.</caption>
        <thead><tr>${head}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }

  function updateResultsControls() {
    if (btnViewList) {
      btnViewList.classList.toggle('view-switch__btn--active', resultsView === 'list');
      btnViewList.setAttribute('aria-pressed', resultsView === 'list' ? 'true' : 'false');
    }
    if (btnViewTable) {
      btnViewTable.classList.toggle('view-switch__btn--active', resultsView === 'table');
      btnViewTable.setAttribute('aria-pressed', resultsView === 'table' ? 'true' : 'false');
    }
    if (btnToggleDetail) {
      btnToggleDetail.setAttribute('aria-pressed', detailCollapsed ? 'false' : 'true');
      const icon = btnToggleDetail.querySelector('.material-symbols-outlined');
      if (icon) icon.textContent = detailCollapsed ? 'right_panel_open' : 'right_panel_close';
    }
    if (resultsGrid) resultsGrid.classList.toggle('results-grid--detail-hidden', detailCollapsed);
  }

  function renderResults(data) {
    resultadosVista = sortResults(data || []);
    updateResultsControls();

    if (!resultadosVista.length) {
      if (resultsView === 'table') {
        resultsList.innerHTML = resultsTableHtml([], '');
      } else {
        resultsList.innerHTML = `<div class="empty-state" style="padding:54px 16px">
          <span class="material-symbols-outlined" style="font-size:42px;color:var(--text-6);margin-bottom:12px" aria-hidden="true">search_off</span>
          <p style="font-weight:600;color:var(--text-4)">No se encontraron registros</p>
          <p style="font-size:12px;color:var(--text-5);margin-top:4px">Intenta verificar el número de documento o escribe otros apellidos</p>
        </div>`;
      }
      badgeCount.textContent = '0';
      return;
    }

    const busqueda = searchInput.value.trim().toLowerCase();
    if (resultsView === 'table') {
      resultsList.innerHTML = resultsTableHtml(resultadosVista, busqueda);
    } else {
      resultsList.innerHTML = resultadosVista.map((p, i) => resultItemHtml(p, i, busqueda)).join('');
    }
  }

  function setResultsView(view, persist = true) {
    resultsView = view === 'table' ? 'table' : 'list';
    if (persist) {
      try { localStorage.setItem('results_view', resultsView); } catch { /* sin almacenamiento */ }
    }
    renderResults(resultados);
    syncUrlState();
  }

  function setDetailCollapsed(collapsed, persist = true) {
    detailCollapsed = !!collapsed;
    if (persist) {
      try { localStorage.setItem('detail_collapsed', detailCollapsed ? '1' : '0'); } catch { /* sin almacenamiento */ }
    }
    updateResultsControls();
    if (!detailCollapsed && personaSeleccionada) {
      detailContent.scrollIntoView({ block: 'nearest', behavior: scrollBehavior() });
    }
  }

  function showResultAtIndex(index) {
    const p = resultadosVista[index];
    if (!p) return;
    if (window.innerWidth <= 768) {
      const el = resultsList.querySelector(`.result-item[data-index="${index}"]`);
      if (!el) {
        // En vista tabla no hay tarjeta expandible: usa el bottom sheet.
        personaSeleccionada = p;
        resultsList.querySelectorAll('.result-row').forEach((row) => {
          const isActive = Number(row.getAttribute('data-index')) === index;
          row.classList.toggle('result-row--active', isActive);
          row.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        syncUrlState();
        openMobileSheet(buildDetailHTML(p), p);
        return;
      }
      const isExpanded = el.classList.contains('result-item--expanded');
      resultsList.querySelectorAll('.result-item').forEach((item) => {
        item.classList.remove('result-item--expanded');
        item.setAttribute('aria-expanded', 'false');
      });
      if (!isExpanded) {
        el.classList.add('result-item--expanded');
        el.setAttribute('aria-expanded', 'true');
        personaSeleccionada = p;
        syncUrlState();
        setTimeout(() => el.scrollIntoView({ behavior: scrollBehavior(), block: 'nearest' }), 80);
      } else {
        personaSeleccionada = null;
        syncUrlState();
      }
      return;
    }
    showDetail(p, index, true);
  }

  function copyResultSummary(p) {
    const fullSummary = `DATOS DE IDENTIFICACIÓN (DNI)\n` +
      `────────────────────────────────────────\n` +
      `DNI: ${p.dni || '-'}\n` +
      `NOMBRES: ${p.nombres || '-'}\n` +
      `APELLIDOS: ${p.ap_pat || '-'} ${p.ap_mat || '-'}\n` +
      `FECHA NAC: ${p.fecha_nac || '-'}\n` +
      `DIRECCIÓN: ${p.direccion || '-'}\n` +
      `UBIGEO: ${p.ubigeo_dir || '-'}`;
    copyText(fullSummary)
      .then(() => toast('Ficha copiada', 'success'))
      .catch(() => toast('Error al copiar', 'error'));
  }

  function handleResultsClick(e) {
    const actionBtn = e.target.closest('[data-inline-action]');
    if (actionBtn) {
      e.stopPropagation();
      const action = actionBtn.getAttribute('data-inline-action');
      const dni = actionBtn.getAttribute('data-dni');
      const idx = Number(actionBtn.getAttribute('data-index'));
      if (action === 'tree') openTreeModal(dni);
      else if (action === 'c4') openC4Modal(dni);
      else if (action === 'copy' && resultadosVista[idx]) copyResultSummary(resultadosVista[idx]);
      return;
    }

    const row = e.target.closest('.result-item, .result-row');
    if (!row) return;
    const index = Number(row.getAttribute('data-index'));
    if (!Number.isInteger(index)) return;
    showResultAtIndex(index);
  }

  function handleResultsKeydown(e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    if (e.target.closest('button, a')) return;
    const row = e.target.closest('.result-item, .result-row');
    if (!row) return;
    e.preventDefault();
    const index = Number(row.getAttribute('data-index'));
    if (Number.isInteger(index)) showResultAtIndex(index);
  }

  if (resultsList) {
    resultsList.addEventListener('click', handleResultsClick);
    resultsList.addEventListener('keydown', handleResultsKeydown);
    resultsList.addEventListener('click', (e) => {
      const sortBtn = e.target.closest('[data-sort]');
      if (!sortBtn) return;
      const key = sortBtn.getAttribute('data-sort');
      if (resultsSort.key === key) {
        resultsSort.dir *= -1;
      } else {
        resultsSort = { key, dir: 1 };
      }
      renderResults(resultados);
    });
  }

  if (btnViewList) btnViewList.addEventListener('click', () => setResultsView('list'));
  if (btnViewTable) btnViewTable.addEventListener('click', () => setResultsView('table'));
  if (btnToggleDetail) btnToggleDetail.addEventListener('click', () => setDetailCollapsed(!detailCollapsed));

  /* ── RUC consultation ────────────────────────────────────── */
  async function consultarRUC(btn, resultadoEl, dni) {
    btn.disabled = true;
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin" style="animation:spin 1s infinite linear">progress_activity</span> Consultando SUNAT...';
    resultadoEl.classList.add('hidden');

    try {
      const res = await apiFetch(`${API_BASE}/scraping/ruc/${encodeURIComponent(dni)}`, { headers: apiHeaders() });
      const data = await res.json();

      if (res.status === 429) {
        const retry = res.headers.get('Retry-After');
        const msg = retry ? `Límite alcanzado. Intenta en ${retry} seg.` : 'Límite de consultas alcanzado. Intenta más tarde.';
        resultadoEl.innerHTML = `<div class="ruc-alert ruc-alert--warn"><span class="material-symbols-outlined">hourglass_empty</span><span>${escHtml(msg)}</span></div>`;
      } else if (res.status === 401) {
        resultadoEl.innerHTML = `<div class="ruc-alert ruc-alert--error"><span class="material-symbols-outlined">lock</span><span>Sesión expirada. Recarga la página.</span></div>`;
      } else if (!res.ok) {
        resultadoEl.innerHTML = `<div class="ruc-alert ruc-alert--error"><span class="material-symbols-outlined">error</span><span>${escHtml(data.detail || 'Error al consultar RUC')}</span></div>`;
      } else if (!data.tiene_ruc) {
        resultadoEl.innerHTML = `<div class="ruc-alert ruc-alert--info"><span class="material-symbols-outlined">info</span><span>Esta persona no tiene RUC registrado ante SUNAT</span></div>`;
      } else {
        const estadoClass = data.estado === 'ACTIVO' ? 'ruc-status--active' : 'ruc-status--inactive';
        resultadoEl.innerHTML = `
          <div class="ruc-data fade-in">
            <div class="field-pill"><span class="material-symbols-outlined">badge</span><span>RUC: ${escHtml(data.ruc || '-')}</span></div>
            <div class="field-pill"><span class="material-symbols-outlined">business</span><span>${escHtml(data.razon_social || '-')}</span></div>
            ${data.estado ? `<div class="field-pill"><span class="material-symbols-outlined ${estadoClass}">verified</span><span class="${estadoClass}">Estado: ${escHtml(data.estado)}</span></div>` : ''}
            ${data.condicion ? `<div class="field-pill"><span class="material-symbols-outlined">check_circle</span><span>Condición: ${escHtml(data.condicion)}</span></div>` : ''}
            ${data.direccion ? `<div class="field-pill"><span class="material-symbols-outlined">location_on</span><span>${escHtml(data.direccion)}</span></div>` : ''}
          </div>`;
      }
      resultadoEl.classList.remove('hidden');
      if (res.ok) refreshUserInfo();
    } catch {
      resultadoEl.innerHTML = `<div class="ruc-alert ruc-alert--error"><span class="material-symbols-outlined">error</span><span>Error de conexión al consultar RUC</span></div>`;
      resultadoEl.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<span class="material-symbols-outlined">account_balance</span> Consultar RUC en SUNAT';
    }
  }

  /* ── Detail panel (100% COMPLETE DATA) ───────────────────── */
  function buildDetailHTML(p) {
    const n = nombre(p);
    const g = sexoLetra(p.sexo);
    const rucCalc = rucDisplay(p);

    let docStatus = '';
    if (p.fch_caducidad) {
      const vencido = new Date(p.fch_caducidad) < new Date();
      docStatus = vencido
        ? '<span class="badge-doc badge-doc--vencido"><span class="material-symbols-outlined" style="font-size:12px">warning</span> Vencido</span>'
        : '<span class="badge-doc badge-doc--vigente"><span class="material-symbols-outlined" style="font-size:12px">check</span> Vigente</span>';
    }

    return `
      <div class="fade-in">
        <!-- Digital DNI Card Visual (ID-1 Format & Holo Shimmer) -->
        <div class="dni-card-visual" id="dni-card-visual">
          <div class="dni-card__shimmer"></div>
          <div class="dni-card__peru-strip">
            <span class="dni-card__rep-peru">REPÚBLICA DEL PERÚ</span>
            <span class="dni-card__dni-elect">DOCUMENTO NACIONAL DE IDENTIDAD</span>
          </div>
          <div class="dni-card__chip"></div>
          <div class="dni-card__header">
            <div class="dni-card__avatar">
              <span class="material-symbols-outlined" style="font-size:32px; color: ${g === 'F' ? 'var(--pink)' : 'var(--blue)'}">${g === 'F' ? 'woman' : 'person'}</span>
            </div>
            <div style="flex:1; min-width:0;">
              <h3 class="dni-card__name">${escHtml(n || '-')}</h3>
              <p class="dni-card__dni">DNI ${escHtml(p.dni || '-')}${p.dig_ruc ? ` - ${escHtml(p.dig_ruc)}` : ''}</p>
            </div>
          </div>
          <div class="dni-card__mrz">
            IDPER${escHtml(p.dni || '00000000')}&lt;&lt;${escHtml(p.dig_ruc || '0')}&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;
          </div>
        </div>

        <!-- Quick Action Toolbar -->
        <div class="detail-toolbar">
          <button class="btn-action" id="btn-copy-full" title="Copiar ficha completa como texto">
            <span class="material-symbols-outlined">assignment</span>
            <span>Copiar Ficha</span>
          </button>
          <button class="btn-action btn-action--whatsapp" id="btn-copy-report" title="Copiar reporte formateado para WhatsApp">
            <span class="material-symbols-outlined" style="color:#22c55e">chat</span>
            <span>WhatsApp</span>
          </button>
          <button class="btn-action" id="btn-tree" title="Ver árbol genealógico" aria-keyshortcuts="T">
            <span class="material-symbols-outlined">account_tree</span>
            <span>Árbol</span>
          </button>
          <button class="btn-action" id="btn-c4-direct" title="Ver ficha de referencia (no oficial)" aria-keyshortcuts="C">
            <span class="material-symbols-outlined" style="color:#38bdf8">description</span>
            <span>C4</span>
          </button>
          <button class="btn-action btn-action--icon" id="btn-copy-link" title="Copiar enlace directo a esta persona" aria-label="Copiar enlace directo a esta persona">
            <span class="material-symbols-outlined" aria-hidden="true">link</span>
          </button>
        </div>

        <div class="detail-body">
          <!-- 1. Desglose de Nombres -->
          <div>
            <p class="detail-section__title">
              <span class="material-symbols-outlined">badge</span> Desglose de Identidad
            </p>
            <div style="display:flex; flex-direction:column; gap:6px;">
              <div class="field-pill" title="Nombres">
                <span class="material-symbols-outlined">person</span>
                <span>Nombres: <strong>${escHtml(p.nombres || '-')}</strong></span>
              </div>
              <div class="detail-grid">
                <div class="field-pill" title="Apellido Paterno">
                  <span class="material-symbols-outlined">family_restroom</span>
                  <span>Ape. Paterno: <strong>${escHtml(p.ap_pat || '-')}</strong></span>
                </div>
                <div class="field-pill" title="Apellido Materno">
                  <span class="material-symbols-outlined">family_restroom</span>
                  <span>Ape. Materno: <strong>${escHtml(p.ap_mat || '-')}</strong></span>
                </div>
              </div>
            </div>
          </div>

          <!-- 2. Datos Personales & Estado Civil -->
          <div>
            <p class="detail-section__title">
              <span class="material-symbols-outlined">id_card</span> Información Civil y Demográfica
            </p>
            <div class="detail-grid">
              <div class="field-pill" title="Sexo">
                <span class="material-symbols-outlined">wc</span>
                <span>Sexo: ${escHtml(p.sexo || '-')}</span>
              </div>
              <div class="field-pill" title="Estado Civil">
                <span class="material-symbols-outlined">favorite</span>
                <span>Est. Civil: ${escHtml(p.est_civil || '-')}</span>
              </div>
              <div class="field-pill" title="Fecha de Nacimiento">
                <span class="material-symbols-outlined">cake</span>
                <span>Nacimiento: ${escHtml(p.fecha_nac || '-')}</span>
              </div>
              <div class="field-pill" title="Edad Exacta">
                <span class="material-symbols-outlined">timer</span>
                <span>${escHtml(p.edad_texto || (p.edad_anios ? p.edad_anios + ' años' : '-'))}</span>
              </div>
            </div>
          </div>

          <!-- 3. Filiación / Padres (1-clic search) -->
          ${p.padre || p.madre ? `
          <div>
            <p class="detail-section__title">
              <span class="material-symbols-outlined">diversity_1</span> Filiación y Padres (Clic para buscar)
            </p>
            <div style="display:flex; flex-direction:column; gap:6px;">
              ${p.padre ? `
                <div class="field-pill field-pill--interactive btn-search-relative" data-name="${escHtml(p.padre)}" title="Buscar padre en padrón">
                  <span class="material-symbols-outlined">man</span>
                  <span>Padre: ${escHtml(p.padre)}</span>
                  <span class="material-symbols-outlined" style="margin-left:auto; font-size:14px;">search</span>
                </div>` : ''}
              ${p.madre ? `
                <div class="field-pill field-pill--interactive btn-search-relative" data-name="${escHtml(p.madre)}" title="Buscar madre en padrón">
                  <span class="material-symbols-outlined">woman</span>
                  <span>Madre: ${escHtml(p.madre)}</span>
                  <span class="material-symbols-outlined" style="margin-left:auto; font-size:14px;">search</span>
                </div>` : ''}
            </div>
          </div>` : ''}

          <!-- 4. Residencia, Ubigeo y Lugar de Nacimiento -->
          <div>
            <p class="detail-section__title">
              <span class="material-symbols-outlined">location_on</span> Domicilio y Origen
            </p>
            <div style="display:flex; flex-direction:column; gap:6px;">
              ${p.direccion ? `
                <div class="field-pill">
                  <span class="material-symbols-outlined">home</span>
                  <span style="white-space:normal; line-height:1.3;">Dirección: ${escHtml(p.direccion)}</span>
                </div>` : ''}
              ${(p.direccion || p.ubigeo_dir) ? `
                <a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([p.direccion, p.ubigeo_dir, 'Peru'].filter(Boolean).join(', '))}" target="_blank" rel="noopener noreferrer" class="btn-map-link" title="Ver dirección en Google Maps">
                  <span class="material-symbols-outlined">map</span>
                  <span>Abrir en Google Maps</span>
                </a>` : ''}
              <div class="detail-grid">
                <div class="field-pill" title="Ubigeo de Domicilio">
                  <span class="material-symbols-outlined">home_pin</span>
                  <span>Ubigeo Dom: <strong>${escHtml(p.ubigeo_dir || '-')}</strong></span>
                </div>
                <div class="field-pill" title="Ubigeo de Nacimiento">
                  <span class="material-symbols-outlined">child_care</span>
                  <span>Ubigeo Nac: <strong>${escHtml(p.ubigeo_nac || '-')}</strong></span>
                </div>
              </div>
            </div>
          </div>

          <!-- 5. Documento y Fechas -->
          <div>
            <p class="detail-section__title">
              <span class="material-symbols-outlined">event_repeat</span> Cronología del Documento
            </p>
            <div class="doc-grid" style="grid-template-columns: 1fr 1fr 1fr 1fr; gap:6px;">
              <div class="doc-card">
                <p class="doc-card__label">Inscripción</p>
                <p class="doc-card__value">${escHtml(p.fch_inscripcion || '-')}</p>
              </div>
              <div class="doc-card">
                <p class="doc-card__label">Emisión</p>
                <p class="doc-card__value">${escHtml(p.fch_emision || '-')}</p>
              </div>
              <div class="doc-card">
                <p class="doc-card__label">Caducidad</p>
                <p class="doc-card__value">${escHtml(p.fch_caducidad || '-')}</p>
              </div>
              <div class="doc-card">
                <p class="doc-card__label">Estado</p>
                <div style="display:flex; justify-content:center; margin-top:2px;">${docStatus || '<span style="font-size:11px;color:var(--text-5)">-</span>'}</div>
              </div>
            </div>
          </div>

          <!-- 6. Consulta RUC SUNAT -->
          <div>
            <p class="detail-section__title">
              <span class="material-symbols-outlined">corporate_fare</span> Registro Único de Contribuyente (SUNAT)
            </p>
            <button class="btn-ruc" id="btn-consultar-ruc">
              <span class="material-symbols-outlined">account_balance</span>
              Consultar RUC en SUNAT
            </button>
            <div id="ruc-resultado" class="hidden"></div>
          </div>
        </div>
      </div>`;
  }

  function personDeepLink(dni) {
    try {
      const url = new URL(window.location.href);
      url.search = '';
      url.hash = '';
      url.searchParams.set('dni', dni);
      return url.toString();
    } catch {
      return `${window.location.origin}${window.location.pathname}?dni=${encodeURIComponent(dni)}`;
    }
  }

  function bindDetailEvents(container, p) {
    const copyBtn = container.querySelector('#btn-copy-dni');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        copyText(String(p.dni)).then(() => {
          toast('DNI copiado al portapapeles', 'success');
        }).catch(() => toast('Error al copiar', 'error'));
      });
    }

    const copyFullBtn = container.querySelector('#btn-copy-full');
    if (copyFullBtn) {
      copyFullBtn.addEventListener('click', () => {
        const fullSummary = [
          `--- FICHA DE REFERENCIA ---`,
          `DNI: ${p.dni || '-'}${p.dig_ruc ? ' - ' + p.dig_ruc : ''}`,
          `Nombre Completo: ${nombre(p)}`,
          `Nombres: ${p.nombres || '-'}`,
          `Ape. Paterno: ${p.ap_pat || '-'}`,
          `Ape. Materno: ${p.ap_mat || '-'}`,
          `Sexo: ${p.sexo || '-'}`,
          `Estado Civil: ${p.est_civil || '-'}`,
          `Fecha Nacimiento: ${p.fecha_nac || '-'}`,
          `Edad: ${p.edad_texto || (p.edad_anios ? p.edad_anios + ' años' : '-')}`,
          `Padre: ${p.padre || '-'}`,
          `Madre: ${p.madre || '-'}`,
          `Dirección: ${p.direccion || '-'}`,
          `Ubigeo Domicilio: ${p.ubigeo_dir || '-'}`,
          `Ubigeo Nacimiento: ${p.ubigeo_nac || '-'}`,
          `Fch. Inscripción: ${p.fch_inscripcion || '-'}`,
          `Fch. Emisión: ${p.fch_emision || '-'}`,
          `Fch. Caducidad: ${p.fch_caducidad || '-'}`
        ].join('\n');

        copyText(fullSummary).then(() => {
          toast('Ficha completa copiada', 'success');
        }).catch(() => toast('Error al copiar', 'error'));
      });
    }

    const copyReportBtn = container.querySelector('#btn-copy-report');
    if (copyReportBtn) {
      copyReportBtn.addEventListener('click', () => {
        const fullReport = [
          `👤 *DATOS PERSONALES (REFERENCIA)*`,
          `▫️ *DNI:* ${p.dni || '-'}${p.dig_ruc ? ' (RUC: ' + rucDisplay(p) + ')' : ''}`,
          `▫️ *Nombre:* ${nombre(p)}`,
          `▫️ *Sexo:* ${p.sexo === '1' || p.sexo === 'M' ? 'Masculino' : p.sexo === '2' || p.sexo === 'F' ? 'Femenino' : (p.sexo || '-')}`,
          `▫️ *Estado Civil:* ${p.est_civil || '-'}`,
          `▫️ *Nacimiento:* ${p.fecha_nac || '-'} (${p.edad_anios ? p.edad_anios + ' años' : '-'})`,
          ``,
          `👪 *FILIACIÓN:*`,
          `▫️ *Padre:* ${p.padre || 'No registrado'}`,
          `▫️ *Madre:* ${p.madre || 'No registrado'}`,
          ``,
          `📍 *DOMICILIO & UBIGEO:*`,
          `▫️ *Dirección:* ${p.direccion || 'No registrada'}`,
          `▫️ *Ubigeo Domicilio:* ${p.ubigeo_dir || '-'}`,
          `▫️ *Ubigeo Nacimiento:* ${p.ubigeo_nac || '-'}`,
          ``,
          `📅 *DOCUMENTO:*`,
          `▫️ *Emisión:* ${p.fch_emision || '-'} | *Caducidad:* ${p.fch_caducidad || '-'}`
        ].join('\n');

        copyText(fullReport).then(() => {
          toast('Reporte formateado copiado al portapapeles', 'success');
        }).catch(() => toast('Error al copiar reporte', 'error'));
      });
    }

    const copyLinkBtn = container.querySelector('#btn-copy-link');
    if (copyLinkBtn) {
      copyLinkBtn.addEventListener('click', () => {
        if (!p.dni) {
          toast('Esta persona no tiene DNI registrado', 'warn');
          return;
        }
        copyText(personDeepLink(p.dni))
          .then(() => toast('Enlace directo copiado', 'success'))
          .catch(() => toast('Error al copiar el enlace', 'error'));
      });
    }

    // Buscador interactivo de padres
    container.querySelectorAll('.btn-search-relative').forEach(el => {
      el.addEventListener('click', () => {
        const nameToSearch = el.getAttribute('data-name');
        if (nameToSearch) {
          setMode('nombre');
          searchInput.value = nameToSearch;
          btnClearSearch.classList.add('visible');
          search();
          if (window.innerWidth < 769) closeMobileSheet();
        }
      });
    });

    const rucBtn = container.querySelector('#btn-consultar-ruc');
    const rucRes = container.querySelector('#ruc-resultado');
    if (rucBtn) {
      rucBtn.addEventListener('click', () => consultarRUC(rucBtn, rucRes, p.dni));
    }

    const treeBtn = container.querySelector('#btn-tree');
    if (treeBtn) {
      treeBtn.addEventListener('click', () => openTreeModal(p.dni));
    }

    const c4DirectBtn = container.querySelector('#btn-c4-direct');
    if (c4DirectBtn) {
      c4DirectBtn.addEventListener('click', () => openC4Modal(p.dni));
    }
  }

  /* ═══════════════════════════════════════════════════════════════════
     ÁRBOL GENEALÓGICO INTERACTIVO — Interactive Graph & Pan/Zoom Canvas
     ═══════════════════════════════════════════════════════════════════ */
  function applyTreeTransform() {
    if (!treeCanvas) return;
    treeCanvas.style.transform = `translate(${treePanX}px, ${treePanY}px) scale(${treeZoom})`;
    if (treeZoomLabel) {
      treeZoomLabel.textContent = `${Math.round(treeZoom * 100)}%`;
    }
  }

  function resetTreeTransform() {
    treeZoom = 1.0;
    treePanX = 0;
    treePanY = 0;
    treeNeedsFit = true;
    applyTreeTransform();
  }

  function setTreeZoom(delta) {
    treeNeedsFit = false;
    treeZoom = Math.min(2.2, Math.max(0.4, treeZoom + delta));
    applyTreeTransform();
  }

  // Pan & Zoom controls
  if (btnTreeZoomIn) btnTreeZoomIn.addEventListener('click', () => setTreeZoom(0.15));
  if (btnTreeZoomOut) btnTreeZoomOut.addEventListener('click', () => setTreeZoom(-0.15));
  if (btnTreeReset) btnTreeReset.addEventListener('click', () => {
    treeNeedsFit = true;
    fitTreeToViewport();
  });

  // Download Tree as Image (PNG)
  if (btnTreeDownload) {
    btnTreeDownload.addEventListener('click', () => {
      const titularDni = treeTitularBadge ? treeTitularBadge.textContent.replace(/\D/g, '') : 'arbol';
      toast('Generando imagen del árbol...', 'normal');

      const container = treeContainer;
      if (!container) return;

      const w = Math.max(container.scrollWidth || 1000, 900);
      const h = Math.max(container.scrollHeight || 700, 600);

      const svgString = `<svg xmlns="http://www.w3.org/2000/svg" width="${w + 60}" height="${h + 60}">
        <foreignObject width="100%" height="100%">
          <div xmlns="http://www.w3.org/1999/xhtml" style="background:#070709; color:#f8fafc; padding:30px; font-family:system-ui, sans-serif;">
            ${container.innerHTML}
          </div>
        </foreignObject>
      </svg>`;

      const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = (w + 60) * 1.5;
        canvas.height = (h + 60) * 1.5;
        const ctx = canvas.getContext('2d');
        ctx.scale(1.5, 1.5);
        ctx.fillStyle = '#070709';
        ctx.fillRect(0, 0, w + 60, h + 60);
        ctx.drawImage(img, 0, 0);
        URL.revokeObjectURL(url);
        canvas.toBlob((pngBlob) => {
          if (!pngBlob) return;
          const a = document.createElement('a');
          a.download = `arbol_genealogico_${titularDni || 'familiar'}.png`;
          a.href = URL.createObjectURL(pngBlob);
          a.click();
          toast('Árbol descargado en formato PNG', 'success');
        });
      };
      img.onerror = () => {
        const a = document.createElement('a');
        a.download = `arbol_genealogico_${titularDni || 'familiar'}.svg`;
        a.href = url;
        a.click();
        toast('Árbol descargado en SVG', 'success');
      };
      img.src = url;
    });
  }

  // Mouse Drag to Pan
  if (treeViewport) {
    treeViewport.addEventListener('mousedown', (e) => {
      if (treeView === 'list') return;
      // Don't drag if clicking an action button
      if (e.target.closest('.btn-node-mini, button, a')) return;
      isDraggingTree = true;
      dragStartX = e.clientX - treePanX;
      dragStartY = e.clientY - treePanY;
      treeViewport.classList.add('is-dragging');
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDraggingTree) return;
      treePanX = e.clientX - dragStartX;
      treePanY = e.clientY - dragStartY;
      applyTreeTransform();
    });

    window.addEventListener('mouseup', () => {
      if (isDraggingTree) {
        isDraggingTree = false;
        if (treeViewport) treeViewport.classList.remove('is-dragging');
      }
    });

    // Mouse Wheel to Zoom
    treeViewport.addEventListener('wheel', (e) => {
      if (treeView === 'list') return;
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.08 : -0.08;
      setTreeZoom(delta);
    }, { passive: false });

    // Touch Support (Pinch to Zoom & Drag)
    treeViewport.addEventListener('touchstart', (e) => {
      if (treeView === 'list') return;
      if (e.touches.length === 1) {
        isDraggingTree = true;
        dragStartX = e.touches[0].clientX - treePanX;
        dragStartY = e.touches[0].clientY - treePanY;
      } else if (e.touches.length === 2) {
        isDraggingTree = false;
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        initialPinchDist = Math.hypot(dx, dy);
        initialPinchZoom = treeZoom;
      }
    }, { passive: true });

    treeViewport.addEventListener('touchmove', (e) => {
      if (treeView === 'list') return;
      if (e.touches.length === 1 && isDraggingTree) {
        treePanX = e.touches[0].clientX - dragStartX;
        treePanY = e.touches[0].clientY - dragStartY;
        applyTreeTransform();
      } else if (e.touches.length === 2 && initialPinchDist) {
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        const currentDist = Math.hypot(dx, dy);
        const factor = currentDist / initialPinchDist;
        treeZoom = Math.min(2.2, Math.max(0.4, initialPinchZoom * factor));
        applyTreeTransform();
      }
    }, { passive: true });

    treeViewport.addEventListener('touchend', () => {
      isDraggingTree = false;
      initialPinchDist = null;
    });
  }

  function treeBatchSize() {
    return window.innerWidth <= 768 ? 6 : 12;
  }

  function treeCacheKey(dni) {
    const limite = window.innerWidth <= 768 ? 60 : 200;
    return `${dni}:${limite}`;
  }

  function treeMoreButton(key, remaining) {
    return `<div class="tree-more-wrap">
      <button type="button" class="tree-more-btn" data-tree-more="${key}">
        <span class="material-symbols-outlined" aria-hidden="true">expand_more</span>
        Ver más (${remaining})
      </button>
    </div>`;
  }

  function openTreeModal(dni, opts = {}) {
    if (!treeModal || !dni) return;
    const requestToken = ++treeRequestToken;
    const isOpen = treeModal.classList.contains('open');
    if (!isOpen) {
      lastFocusedElement = document.activeElement;
      treeModal.classList.add('open');
      treeModal.removeAttribute('inert');
      treeModal.setAttribute('aria-hidden', 'false');
      updateBodyScrollLock();
    }

    const sameRoot = treeRootDni === dni;
    if (!sameRoot) {
      treeRootDni = dni;
      treeData = null;
      treeListTab = 'padres';
      treeVisible = { hermanos: treeBatchSize(), hijos: treeBatchSize(), probables: treeBatchSize(), hijosProbables: treeBatchSize() };
      treeNeedsFit = !opts.preserveView;
      if (!opts.preserveView) resetTreeTransform();
    }

    if (treeTitularBadge) treeTitularBadge.textContent = `DNI ${dni}`;
    if (treeStatsBar) treeStatsBar.innerHTML = '';

    const cacheKey = treeCacheKey(dni);
    const cached = treeCache.get(cacheKey);
    if (cached && Date.now() - cached.ts < TREE_CACHE_TTL) {
      treeNeedsFit = !opts.preserveView;
      renderArbol(cached.data);
      setTimeout(() => { if ($('btn-close-tree')) $('btn-close-tree').focus(); }, 60);
      return;
    }

    treeContainer.innerHTML = '<div class="tree-loading"><div class="qs-spinner"></div><p>Construyendo red genealógica interactiva...</p></div>';
    fetchArbol(dni, requestToken);
    setTimeout(() => { if ($('btn-close-tree')) $('btn-close-tree').focus(); }, 60);
  }

  function closeTreeModal() {
    if (!treeModal) return;
    treeRequestToken += 1;
    treeModal.classList.remove('open');
    updateBodyScrollLock();
    if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
      lastFocusedElement.focus();
    }
    treeModal.setAttribute('aria-hidden', 'true');
    treeModal.setAttribute('inert', '');
  }

  document.querySelectorAll('[data-close-tree]').forEach(el => el.addEventListener('click', closeTreeModal));
  if ($('btn-close-tree')) $('btn-close-tree').addEventListener('click', closeTreeModal);

  async function fetchArbol(dni, requestToken) {
    const limite = window.innerWidth <= 768 ? 60 : 200;
    try {
      const res = await apiFetch(`${API_BASE}/persona/${encodeURIComponent(dni)}/arbol?limite=${limite}`, { headers: apiHeaders() });
      if (requestToken !== treeRequestToken) return;
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        if (requestToken !== treeRequestToken) return;
        treeContainer.innerHTML = `<div class="tree-empty">
          <span class="material-symbols-outlined tree-empty__icon">error</span>
          <p class="tree-empty__title">${escHtml(body?.detail || 'Error al cargar el árbol')}</p>
        </div>`;
        return;
      }
      const data = await res.json();
      if (requestToken !== treeRequestToken) return;
      treeCache.set(treeCacheKey(dni), { data, ts: Date.now() });
      // Mantén la caché acotada: sólo los árboles consultados recientemente.
      if (treeCache.size > 30) {
        const oldest = [...treeCache.entries()]
          .sort((a, b) => a[1].ts - b[1].ts)
          .slice(0, treeCache.size - 30);
        oldest.forEach(([key]) => treeCache.delete(key));
      }
      renderArbol(data);
      refreshUserInfo();
    } catch {
      if (requestToken !== treeRequestToken) return;
      treeContainer.innerHTML = `<div class="tree-empty">
        <span class="material-symbols-outlined tree-empty__icon">cloud_off</span>
        <p class="tree-empty__title">Error de conexión</p>
        <p class="tree-empty__desc">No se pudo conectar al servidor para construir el árbol genealógico</p>
      </div>`;
    }
  }

  function fitTreeToViewport() {
    if (treeView !== 'graph' || !treeViewport || !treeContainer) return;
    const vw = treeViewport.clientWidth;
    const vh = treeViewport.clientHeight;
    const cw = treeContainer.scrollWidth;
    const ch = treeContainer.scrollHeight;
    if (!vw || !vh || !cw || !ch) return;
    const fit = Math.min((vw - 28) / cw, (vh - 28) / ch, 1.1);
    treeZoom = Math.max(0.4, Math.min(1.25, fit));
    treePanX = 0;
    treePanY = 0;
    treeNeedsFit = false;
    applyTreeTransform();
  }

  function setTreeView(view, persist = true) {
    treeView = view === 'list' ? 'list' : 'graph';
    if (persist) {
      try { localStorage.setItem('tree_view', treeView); } catch { /* sin almacenamiento */ }
    }
    renderTree();
    if (treeView === 'graph' && treeNeedsFit) requestAnimationFrame(fitTreeToViewport);
  }

  if (btnTreeViewGraph) btnTreeViewGraph.addEventListener('click', () => setTreeView('graph'));
  if (btnTreeViewList) btnTreeViewList.addEventListener('click', () => setTreeView('list'));

  function tipoRelacionLabel(tipo) {
    const etiquetas = {
      hermano_completo: 'Hermano completo',
      medio_hermano_paterno: 'Medio hermano (padre)',
      medio_hermano_materno: 'Medio hermano (madre)',
      hermano_probable: 'Hermano probable',
      hijo: 'Hijo',
      hija: 'Hija',
      hijo_probable: 'Hijo probable',
      hija_probable: 'Hija probable',
      padre: 'Padre',
      madre: 'Madre',
      titular: 'Titular',
    };
    return etiquetas[tipo] || '';
  }

  function treeActionsHtml(nodo, nombreNodo) {
    if (!nodo.dni || !nodo.encontrado) return '';
    return `<div class="tree-node__actions">
      <button class="btn-node-mini" type="button" data-tree-action="explore" data-dni="${escHtml(nodo.dni)}" title="Explorar árbol de ${escHtml(nombreNodo)}">
        <span class="material-symbols-outlined" style="font-size:11px" aria-hidden="true">account_tree</span>
        <span>Árbol</span>
      </button>
      <button class="btn-node-mini" type="button" data-tree-action="detail" data-dni="${escHtml(nodo.dni)}" title="Ver Ficha Completa">
        <span class="material-symbols-outlined" style="font-size:11px" aria-hidden="true">visibility</span>
        <span>Ficha</span>
      </button>
      <button class="btn-node-mini" type="button" data-tree-action="c4" data-dni="${escHtml(nodo.dni)}" title="Generar ficha de referencia (no oficial)">
        <span class="material-symbols-outlined" style="font-size:11px" aria-hidden="true">print</span>
        <span>C4</span>
      </button>
    </div>`;
  }

  function treeNodeHtml(nodo, opts = {}) {
    if (!nodo) return '';
    const n = [nodo.nombres, nodo.ap_pat, nodo.ap_mat].filter(Boolean).join(' ').trim() || '-';
    const g = sexoLetra(nodo.sexo);
    const gClass = g === 'M' ? 'tree-node--male' : g === 'F' ? 'tree-node--female' : '';
    const mainClass = opts.isMain ? 'tree-node--main' : '';
    const ghostClass = !nodo.encontrado ? 'tree-node--ghost' : '';
    const smClass = opts.small ? 'tree-node--sm' : '';
    const probableClass = (opts.probable || nodo.tipo_relacion === 'hermano_probable')
      ? 'tree-node--probable'
      : '';

    let relClass = '';
    const relLower = (opts.relation || '').toLowerCase();
    if (opts.isMain) relClass = 'tree-node--main';
    else if (relLower.includes('padre') || relLower.includes('madre')) relClass = 'tree-node--parent';
    else if (relLower.includes('cónyuge') || relLower.includes('espos') || relLower.includes('pareja')) relClass = 'tree-node--spouse';
    else if (relLower.includes('hijo') || relLower.includes('hija')) relClass = 'tree-node--child';
    else if (relLower.includes('herman')) relClass = 'tree-node--sibling';

    const icon = g === 'F' ? 'woman' : 'person';
    const relationLabel = opts.relation || tipoRelacionLabel(nodo.tipo_relacion);
    const relation = relationLabel ? `<div class="tree-node__relation">${escHtml(relationLabel)}</div>` : '';
    const meta = nodo.dni ? `DNI ${escHtml(nodo.dni)}` : (nodo.encontrado ? '' : 'No encontrado');
    const age = nodo.edad_anios ? ` · ${nodo.edad_anios}a` : '';
    const ubigeo = nodo.ubigeo_dir && !opts.small ? `<div class="tree-node__ubigeo"><span class="material-symbols-outlined" style="font-size:10px" aria-hidden="true">location_on</span>${escHtml(nodo.ubigeo_dir)}</div>` : '';

    const confianza = Number(nodo.confianza);
    const tieneConfianza = nodo.encontrado && !opts.isMain &&
      nodo.confianza != null && Number.isFinite(confianza);
    const nivel = String(nodo.nivel_confianza || 'baja').toLowerCase();
    const evidencia = (nodo.evidencia || [])
      .map((e) => `${e.descripcion || e.codigo || ''}${e.puntos != null ? ` (+${e.puntos})` : ''}`)
      .filter(Boolean);
    const confidenceHtml = tieneConfianza
      ? `<div class="tree-node__confidence tree-node__confidence--${escHtml(nivel)}" title="${escHtml(evidencia.length ? `Evidencia:\n${evidencia.join('\n')}` : 'Sin evidencia detallada')}">
           <span class="tree-node__confidence-dot"></span>${confianza}% ${escHtml(nivel)}
         </div>`
      : '';

    const alternativas = nodo.candidatos || [];
    const alternativasHtml = alternativas.length
      ? `<div class="tree-node__candidates" title="${escHtml(alternativas.map((c) => {
          const cn = [c.nombres, c.ap_pat, c.ap_mat].filter(Boolean).join(' ') || c.dni || 'Sin identificar';
          return `${cn} — ${c.confianza != null ? c.confianza + '%' : 'sin confianza'}${c.dni ? ` (DNI ${c.dni})` : ''}`;
        }).join('\n'))}">
           <span class="material-symbols-outlined" style="font-size:11px" aria-hidden="true">alt_route</span>
           ${alternativas.length} alternativa${alternativas.length !== 1 ? 's' : ''}
         </div>`
      : '';

    const aria = `${relationLabel || 'Familiar'}: ${n}${nodo.dni ? `, DNI ${nodo.dni}` : ''}${nodo.edad_anios ? `, ${nodo.edad_anios} años` : ''}${tieneConfianza ? `, confianza ${confianza}%` : ''}`;
    const focusable = nodo.dni && nodo.encontrado ? 'tabindex="0" role="button"' : 'tabindex="-1"';

    return `
      <div class="tree-node ${gClass} ${mainClass} ${relClass} ${ghostClass} ${smClass} ${probableClass}" data-dni="${escHtml(nodo.dni || '')}" title="${escHtml(n)}" ${focusable} aria-label="${escHtml(aria)}">
        ${relation}
        <div class="tree-node__avatar">
          <span class="material-symbols-outlined" style="font-size:20px" aria-hidden="true">${icon}</span>
        </div>
        <div class="tree-node__name">${escHtml(n)}</div>
        <div class="tree-node__meta">${meta}${age}</div>
        ${confidenceHtml}
        ${alternativasHtml}
        ${ubigeo}
        ${opts.small ? '' : treeActionsHtml(nodo, n)}
      </div>
    `;
  }

  function treeListNodeHtml(nodo, relation, opts = {}) {
    if (!nodo) return '';
    const n = [nodo.nombres, nodo.ap_pat, nodo.ap_mat].filter(Boolean).join(' ').trim() || '-';
    const g = sexoLetra(nodo.sexo);
    const gClass = g === 'M' ? 'tree-list-item--male' : g === 'F' ? 'tree-list-item--female' : '';
    const mainClass = opts.isMain ? 'tree-list-item--main' : '';
    const ghostClass = !nodo.encontrado ? 'tree-list-item--ghost' : '';
    const confianza = Number(nodo.confianza);
    const nivel = String(nodo.nivel_confianza || 'baja').toLowerCase();
    const confHtml = nodo.encontrado && !opts.isMain &&
      nodo.confianza != null && Number.isFinite(confianza)
      ? `<span class="tree-list-item__confidence tree-list-item__confidence--${escHtml(nivel)}">${confianza}% ${escHtml(nivel)}</span>`
      : '';
    const metaParts = [
      relation,
      nodo.dni ? `DNI ${nodo.dni}` : 'No encontrado',
      nodo.edad_anios ? `${nodo.edad_anios} años` : '',
      nodo.ubigeo_dir || '',
    ].filter(Boolean);
    const aria = `${relation || 'Familiar'}: ${n}${nodo.dni ? `, DNI ${nodo.dni}` : ''}${nodo.edad_anios ? `, ${nodo.edad_anios} años` : ''}`;
    const focusable = nodo.dni && nodo.encontrado ? 'tabindex="0" role="button"' : 'tabindex="-1"';

    return `<div class="tree-list-item ${gClass} ${mainClass} ${ghostClass}" data-dni="${escHtml(nodo.dni || '')}" ${focusable} aria-label="${escHtml(aria)}">
      <div class="tree-list-item__avatar">
        <span class="material-symbols-outlined" style="font-size:20px" aria-hidden="true">${g === 'F' ? 'woman' : 'person'}</span>
      </div>
      <div class="tree-list-item__body">
        <div class="tree-list-item__name">${escHtml(n)}</div>
        <div class="tree-list-item__meta">
          ${metaParts.map((part, i) => i === 1 ? `<span class="dni">${escHtml(part)}</span>` : `<span>${escHtml(part)}</span>`).join('<span aria-hidden="true">·</span>')}
          ${confHtml}
        </div>
      </div>
      <div class="tree-list-item__actions">${treeActionsHtml(nodo, n).replace('class="tree-node__actions"', 'class="tree-list-item__actions-inner"')}</div>
    </div>`;
  }

  function renderTreeStats(data) {
    if (!treeStatsBar) return;
    const gpCount = [data.abuelo_paterno, data.abuela_paterna, data.abuelo_materno, data.abuela_materna].filter(x => x && x.encontrado).length;
    const parentsCount = [data.padre, data.madre].filter(x => x && x.encontrado).length;
    const todosHermanos = data.hermanos || [];
    const sibCount = todosHermanos.filter(h => h.tipo_relacion !== 'hermano_probable').length;
    const probCount = todosHermanos.length - sibCount;
    const todosHijos = data.hijos || [];
    const childrenCount = todosHijos.filter(h => !String(h.tipo_relacion || '').endsWith('_probable')).length;
    const childProbCount = todosHijos.length - childrenCount;

    let statsHtml = `
      <span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#a855f7" aria-hidden="true">person</span><strong>1</strong> Titular</span>
      <span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#6366f1" aria-hidden="true">family_restroom</span><strong>${parentsCount}</strong> Padres</span>
      <span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#eab308" aria-hidden="true">elderly</span><strong>${gpCount}</strong> Abuelos</span>
    `;
    if (sibCount > 0) {
      statsHtml += `<span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#10b981" aria-hidden="true">group</span><strong>${sibCount}</strong> Hermanos</span>`;
    }
    if (probCount > 0) {
      statsHtml += `<span class="tree-stat-chip tree-stat-chip--probable"><span class="material-symbols-outlined" style="font-size:13px; color:#fbbf24" aria-hidden="true">help</span><strong>${probCount}</strong> Probables</span>`;
    }
    if (childrenCount > 0) {
      statsHtml += `<span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#0284c7" aria-hidden="true">child_care</span><strong>${childrenCount}</strong> Hijos</span>`;
    }
    if (childProbCount > 0) {
      statsHtml += `<span class="tree-stat-chip tree-stat-chip--probable"><span class="material-symbols-outlined" style="font-size:13px; color:#fbbf24" aria-hidden="true">help</span><strong>${childProbCount}</strong> Hijos prob.</span>`;
    }
    treeStatsBar.innerHTML = statsHtml;

    const advertencias = (data.meta && data.meta.advertencias) || [];
    if (advertencias.length) {
      const warn = document.createElement('div');
      warn.className = 'tree-warnings';
      const icon = document.createElement('span');
      icon.className = 'material-symbols-outlined';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = 'info';
      const list = document.createElement('ul');
      advertencias.forEach((texto) => {
        const li = document.createElement('li');
        li.textContent = texto;
        list.appendChild(li);
      });
      warn.append(icon, list);
      treeStatsBar.appendChild(warn);
    }
  }

  function renderTreeGraph(data) {
    let html = '<div class="tree">';

    // ── Level 0: Grandparents ──
    const hasGPPat = data.abuelo_paterno || data.abuela_paterna;
    const hasGPMat = data.abuelo_materno || data.abuela_materna;
    if (hasGPPat || hasGPMat) {
      html += '<p class="tree-gen-label">Abuelos</p>';
      html += '<div class="tree-level"><div class="tree-grandparents">';
      if (hasGPPat) {
        html += '<div class="tree-gp-couple">';
        html += '<p class="tree-gp-label">Línea Paterna</p>';
        html += '<div class="tree-gp-pair">';
        if (data.abuelo_paterno) html += treeNodeHtml(data.abuelo_paterno, { small: true, relation: 'Abuelo Pat.' });
        if (data.abuela_paterna) html += treeNodeHtml(data.abuela_paterna, { small: true, relation: 'Abuela Pat.' });
        html += '</div><div class="tree-gp-connector"></div></div>';
      }
      if (hasGPMat) {
        html += '<div class="tree-gp-couple">';
        html += '<p class="tree-gp-label">Línea Materna</p>';
        html += '<div class="tree-gp-pair">';
        if (data.abuelo_materno) html += treeNodeHtml(data.abuelo_materno, { small: true, relation: 'Abuelo Mat.' });
        if (data.abuela_materna) html += treeNodeHtml(data.abuela_materna, { small: true, relation: 'Abuela Mat.' });
        html += '</div><div class="tree-gp-connector"></div></div>';
      }
      html += '</div></div><div class="tree-connector"></div>';
    }

    // ── Level 1: Parents ──
    if (data.padre || data.madre) {
      html += '<p class="tree-gen-label">Padres</p>';
      html += '<div class="tree-level"><div class="tree-couple">';
      if (data.padre) html += treeNodeHtml(data.padre, { relation: 'Padre' });
      if (data.madre) html += treeNodeHtml(data.madre, { relation: 'Madre' });
      html += '</div></div><div class="tree-connector"></div>';
    }

    // ── Level 2: Person + Siblings (progresivo) ──
    const todosHermanos = data.hermanos || [];
    const hermanos = todosHermanos.filter(h => h.tipo_relacion !== 'hermano_probable');
    const probables = todosHermanos.filter(h => h.tipo_relacion === 'hermano_probable');
    const visiblesHermanos = hermanos.slice(0, treeVisible.hermanos);
    html += '<p class="tree-gen-label">Persona' + (hermanos.length > 0 ? ' y Hermanos' : '') + '</p>';
    html += '<div class="tree-level"><div class="tree-siblings-row">';
    visiblesHermanos.forEach((h, i) => {
      if (i === Math.floor(visiblesHermanos.length / 2)) {
        html += treeNodeHtml(data.persona, { isMain: true, relation: 'Titular' });
      }
      html += treeNodeHtml(h, { relation: tipoRelacionLabel(h.tipo_relacion) || 'Hermano/a' });
    });
    if (visiblesHermanos.length === 0) {
      html += treeNodeHtml(data.persona, { isMain: true, relation: 'Titular' });
    }
    html += '</div>';
    if (hermanos.length > visiblesHermanos.length) {
      html += treeMoreButton('hermanos', hermanos.length - visiblesHermanos.length);
    }
    if (probables.length > 0) {
      const visiblesProbables = probables.slice(0, treeVisible.probables);
      html += `<details class="tree-probables">
        <summary><span class="material-symbols-outlined" style="font-size:14px" aria-hidden="true">help</span> ${probables.length} hermano(s) probable(s) — baja confianza</summary>
        <div class="tree-siblings-row tree-siblings-row--probables">`;
      visiblesProbables.forEach(h => {
        html += treeNodeHtml(h, { relation: 'Hermano probable', probable: true });
      });
      html += '</div>';
      if (probables.length > visiblesProbables.length) {
        html += treeMoreButton('probables', probables.length - visiblesProbables.length);
      }
      html += '</details>';
    }
    html += '</div>';

    // ── Level 3: Children (progresivo) ──
    const todosHijos = data.hijos || [];
    const hijos = todosHijos.filter(h => !String(h.tipo_relacion || '').endsWith('_probable'));
    const hijosProbables = todosHijos.filter(h => String(h.tipo_relacion || '').endsWith('_probable'));
    const visiblesHijos = hijos.slice(0, treeVisible.hijos);
    if (todosHijos.length > 0) {
      html += '<div class="tree-connector"></div><p class="tree-gen-label">Hijos</p>';
      if (visiblesHijos.length > 0) {
        html += '<div class="tree-level"><div class="tree-branch">';
        visiblesHijos.forEach(h => {
          html += '<div class="tree-branch-child">';
          html += treeNodeHtml(h, { relation: tipoRelacionLabel(h.tipo_relacion) || 'Hijo/a' });
          html += '</div>';
        });
        html += '</div>';
        if (hijos.length > visiblesHijos.length) {
          html += treeMoreButton('hijos', hijos.length - visiblesHijos.length);
        }
        html += '</div>';
      }
      if (hijosProbables.length > 0) {
        const visiblesHijosProb = hijosProbables.slice(0, treeVisible.hijosProbables);
        html += `<details class="tree-probables">
          <summary><span class="material-symbols-outlined" style="font-size:14px" aria-hidden="true">help</span> ${hijosProbables.length} hijo(s) probable(s) — baja confianza</summary>
          <div class="tree-level"><div class="tree-siblings-row tree-siblings-row--probables">`;
        visiblesHijosProb.forEach(h => {
          html += treeNodeHtml(h, { relation: tipoRelacionLabel(h.tipo_relacion) || 'Hijo/a probable', probable: true });
        });
        html += '</div>';
        if (hijosProbables.length > visiblesHijosProb.length) {
          html += treeMoreButton('hijos_probables', hijosProbables.length - visiblesHijosProb.length);
        }
        html += '</div></details>';
      }
    }

    html += '</div>';
    return html;
  }

  function renderTreeList(data) {
    const todosHermanos = data.hermanos || [];
    const todosHijos = data.hijos || [];
    const abuelos = [
      [data.abuelo_paterno, 'Abuelo paterno'],
      [data.abuela_paterna, 'Abuela paterna'],
      [data.abuelo_materno, 'Abuelo materno'],
      [data.abuela_materna, 'Abuela materna'],
    ].filter(([nodo]) => nodo);
    const padres = [
      [data.padre, 'Padre'],
      [data.madre, 'Madre'],
    ].filter(([nodo]) => nodo);

    const tabs = [
      ['padres', 'Padres', padres.length],
      ['abuelos', 'Abuelos', abuelos.length],
      ['hermanos', 'Hermanos', todosHermanos.length],
      ['hijos', 'Hijos', todosHijos.length],
    ];
    if (!tabs.some(([key]) => key === treeListTab)) treeListTab = 'padres';

    let html = '<div class="tree-list">';
    html += '<div class="tree-tabs" role="tablist" aria-label="Secciones del árbol">';
    tabs.forEach(([key, label, count]) => {
      const active = key === treeListTab;
      html += `<button type="button" class="tree-tab${active ? ' tree-tab--active' : ''}" role="tab" aria-selected="${active ? 'true' : 'false'}" data-tree-tab="${key}">
        ${label}<span class="tree-tab__count">${count}</span>
      </button>`;
    });
    html += '</div>';

    html += `<div class="tree-list__section" role="tabpanel" aria-label="${escHtml(tabs.find(([key]) => key === treeListTab)[1])}">`;
    if (treeListTab === 'padres') {
      if (!padres.length) {
        html += '<p class="tree-list__empty">No se encontraron progenitores en el padrón.</p>';
      } else {
        padres.forEach(([nodo, relation]) => { html += treeListNodeHtml(nodo, relation); });
      }
    } else if (treeListTab === 'abuelos') {
      if (!abuelos.length) {
        html += '<p class="tree-list__empty">No se encontraron abuelos en el padrón.</p>';
      } else {
        abuelos.forEach(([nodo, relation]) => { html += treeListNodeHtml(nodo, relation); });
      }
    } else if (treeListTab === 'hermanos') {
      if (!todosHermanos.length) {
        html += '<p class="tree-list__empty">No se encontraron hermanos en el padrón.</p>';
      } else {
        const visibles = todosHermanos.slice(0, treeVisible.hermanos);
        visibles.forEach((nodo) => {
          html += treeListNodeHtml(nodo, tipoRelacionLabel(nodo.tipo_relacion) || 'Hermano/a');
        });
        if (todosHermanos.length > visibles.length) {
          html += treeMoreButton('hermanos', todosHermanos.length - visibles.length);
        }
      }
    } else if (treeListTab === 'hijos') {
      if (!todosHijos.length) {
        html += '<p class="tree-list__empty">No se encontraron hijos en el padrón.</p>';
      } else {
        const visibles = todosHijos.slice(0, treeVisible.hijos);
        visibles.forEach((nodo) => {
          html += treeListNodeHtml(nodo, tipoRelacionLabel(nodo.tipo_relacion) || 'Hijo/a');
        });
        if (todosHijos.length > visibles.length) {
          html += treeMoreButton('hijos', todosHijos.length - visibles.length);
        }
      }
    }
    html += '</div></div>';
    return html;
  }

  function renderTree() {
    if (!treeData || !treeData.persona) return;
    const panel = treeModal ? treeModal.querySelector('.tree-panel') : null;
    if (panel) panel.classList.toggle('tree-panel--list', treeView === 'list');
    if (btnTreeViewGraph) {
      btnTreeViewGraph.classList.toggle('view-switch__btn--active', treeView === 'graph');
      btnTreeViewGraph.setAttribute('aria-pressed', treeView === 'graph' ? 'true' : 'false');
    }
    if (btnTreeViewList) {
      btnTreeViewList.classList.toggle('view-switch__btn--active', treeView === 'list');
      btnTreeViewList.setAttribute('aria-pressed', treeView === 'list' ? 'true' : 'false');
    }
    treeContainer.innerHTML = treeView === 'list'
      ? renderTreeList(treeData)
      : renderTreeGraph(treeData);
    if (treeView === 'graph' && treeNeedsFit) requestAnimationFrame(fitTreeToViewport);
  }

  function renderArbol(data) {
    if (!data || !data.persona) {
      treeContainer.innerHTML = `<div class="tree-empty">
        <span class="material-symbols-outlined tree-empty__icon">person_off</span>
        <p class="tree-empty__title">Sin datos genealógicos</p>
        <p class="tree-empty__desc">No se encontró información familiar para esta persona</p>
      </div>`;
      return;
    }
    treeData = data;
    const p = data.persona;
    const titularNombre = [p.nombres, p.ap_pat, p.ap_mat].filter(Boolean).join(' ').trim();
    if (treeTitularBadge) {
      treeTitularBadge.textContent = `${titularNombre} · DNI ${p.dni || '-'}`;
    }
    renderTreeStats(data);
    renderTree();
  }

  function handleTreeClick(e) {
    const moreBtn = e.target.closest('[data-tree-more]');
    if (moreBtn) {
      const key = moreBtn.getAttribute('data-tree-more');
      const batch = treeBatchSize();
      if (key === 'hermanos') treeVisible.hermanos += batch;
      else if (key === 'hijos') treeVisible.hijos += batch;
      else if (key === 'probables') treeVisible.probables += batch;
      else if (key === 'hijos_probables') treeVisible.hijosProbables += batch;
      renderTree();
      const nextMore = treeContainer.querySelector(`[data-tree-more="${key}"]`);
      if (nextMore) nextMore.focus();
      else if ($('btn-close-tree')) $('btn-close-tree').focus();
      return;
    }

    const tabBtn = e.target.closest('[data-tree-tab]');
    if (tabBtn) {
      treeListTab = tabBtn.getAttribute('data-tree-tab');
      renderTree();
      const activeTab = treeContainer.querySelector('.tree-tab--active');
      if (activeTab) activeTab.focus();
      return;
    }

    const actionBtn = e.target.closest('[data-tree-action]');
    if (actionBtn) {
      e.stopPropagation();
      const action = actionBtn.getAttribute('data-tree-action');
      const nodeDni = actionBtn.getAttribute('data-dni');
      if (!nodeDni) return;
      if (action === 'explore') {
        openTreeModal(nodeDni, { preserveView: true });
      } else if (action === 'detail') {
        closeTreeModal();
        setMode('dni');
        searchInput.value = nodeDni;
        btnClearSearch.classList.add('visible');
        search();
      } else if (action === 'c4') {
        closeTreeModal();
        openC4Modal(nodeDni);
      }
      return;
    }

    const card = e.target.closest('.tree-node, .tree-list-item');
    if (!card) return;
    const nodeDni = card.getAttribute('data-dni');
    if (nodeDni && nodeDni !== treeRootDni && !card.classList.contains('tree-node--ghost') && !card.classList.contains('tree-list-item--ghost')) {
      openTreeModal(nodeDni, { preserveView: true });
    }
  }

  function handleTreeKeydown(e) {
    const card = e.target.closest('.tree-node, .tree-list-item');
    if (!card) return;
    if (e.key === 'Enter' || e.key === ' ') {
      if (e.target.closest('button')) return;
      e.preventDefault();
      card.click();
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const focusables = Array.from(treeContainer.querySelectorAll('.tree-node[tabindex="0"], .tree-list-item[tabindex="0"]'));
    const index = focusables.indexOf(card);
    if (index < 0) return;
    e.preventDefault();
    const delta = (e.key === 'ArrowDown' || e.key === 'ArrowRight') ? 1 : -1;
    const next = focusables[(index + delta + focusables.length) % focusables.length];
    if (next) next.focus();
  }

  if (treeContainer) {
    treeContainer.addEventListener('click', handleTreeClick);
    treeContainer.addEventListener('keydown', handleTreeKeydown);
  }

  /* ═══════════════════════════════════════════════════════════════════
     FICHA DE REFERENCIA C4 — DATOS DEL PADRÓN (NO OFICIAL)
     ═══════════════════════════════════════════════════════════════════ */
  async function openC4Modal(dni) {
    if (!c4Modal) return;
    const requestToken = ++c4RequestToken;
    if (!c4Modal.classList.contains('open')) lastFocusedC4 = document.activeElement;

    c4Modal.classList.add('open');
    c4Modal.removeAttribute('inert');
    c4Modal.setAttribute('aria-hidden', 'false');
    updateBodyScrollLock();
    c4Container.innerHTML = '<div class="c4-loading"><div class="qs-spinner"></div><p>Generando ficha de referencia (no oficial)...</p></div>';
    setTimeout(() => { if (btnCloseC4) btnCloseC4.focus(); }, 60);

    try {
      const res = await apiFetch(`${API_BASE}/persona/${encodeURIComponent(dni)}/c4`, { headers: apiHeaders() });
      if (requestToken !== c4RequestToken) return;
      if (res.ok) {
        const data = await res.json();
        if (requestToken !== c4RequestToken) return;
        renderC4Certificate(data);
        refreshUserInfo();
        return;
      }

      const body = await res.json().catch(() => null);
      if (requestToken !== c4RequestToken) return;
      c4Container.innerHTML = `<div class="c4-loading">
        <span class="material-symbols-outlined" style="font-size:36px;color:var(--text-5)">info</span>
        <p>${escHtml((body && body.detail) || 'No se pudo generar la ficha de referencia')}</p>
      </div>`;
    } catch {
      if (requestToken !== c4RequestToken) return;
      c4Container.innerHTML = `<div class="c4-loading">
        <span class="material-symbols-outlined" style="font-size:36px;color:var(--text-5)">cloud_off</span>
        <p>Error de conexión al generar la ficha</p>
      </div>`;
    }
  }

  function closeC4Modal() {
    if (!c4Modal) return;
    c4RequestToken += 1;
    c4Modal.classList.remove('open');
    updateBodyScrollLock();
    if (lastFocusedC4 && typeof lastFocusedC4.focus === 'function') lastFocusedC4.focus();
    c4Modal.setAttribute('aria-hidden', 'true');
    c4Modal.setAttribute('inert', '');
  }

  if (btnCloseC4) btnCloseC4.addEventListener('click', closeC4Modal);
  if (btnPrintC4) btnPrintC4.addEventListener('click', () => window.print());
  document.querySelectorAll('[data-close-c4]').forEach(el => el.addEventListener('click', closeC4Modal));

  /* ── Logo neutro de la ficha de referencia ────────────────── */
  function generateReferenceLogoSVG() {
    return `<svg viewBox="0 0 240 68" width="180" height="52" xmlns="http://www.w3.org/2000/svg" aria-label="Buscador de Personas">
      <rect x="4" y="4" width="232" height="60" rx="8" fill="#0f172a" stroke="#38bdf8" stroke-width="1.5"/>
      <circle cx="30" cy="30" r="12" fill="none" stroke="#818cf8" stroke-width="2.5"/>
      <path d="M15 54c0-7 6-13 15-13s15 6 15 13" fill="none" stroke="#818cf8" stroke-width="2.5"/>
      <circle cx="45" cy="47" r="7" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
      <line x1="50" y1="52" x2="57" y2="59" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round"/>
      <text x="66" y="30" fill="#f8fafc" font-family="Arial, sans-serif" font-size="15" font-weight="bold">Buscador de Personas</text>
      <text x="66" y="47" fill="#94a3b8" font-family="Arial, sans-serif" font-size="9">Ficha de referencia — no oficial</text>
    </svg>`;
  }

  function parseUbigeoParts(ubigeoStr) {
    if (!ubigeoStr) return { dpto: '-', prov: '-', dist: '-' };
    const str = String(ubigeoStr).trim().toUpperCase();

    if (str.includes('/')) {
      const parts = str.split('/').map(s => s.trim());
      return {
        dpto: parts[0] || '-',
        prov: parts[1] || parts[0] || '-',
        dist: parts[2] || parts[1] || parts[0] || '-'
      };
    }
    if (str.includes('-')) {
      const parts = str.split('-').map(s => s.trim());
      if (parts.length >= 3) {
        return { dpto: parts[0], prov: parts[1], dist: parts[2] };
      }
      if (parts.length === 2) {
        return { dpto: parts[0], prov: parts[0], dist: parts[1] };
      }
    }
    return { dpto: str, prov: str, dist: str };
  }

  function renderC4Certificate(data) {
    const p = data.persona || {};
    const nac = parseUbigeoParts(p.ubigeo_nac);
    const dom = parseUbigeoParts(p.ubigeo_dir);

    const ahora = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const fEmision = data.fecha_generacion || `${pad(ahora.getDate())}/${pad(ahora.getMonth()+1)}/${ahora.getFullYear()} ${pad(ahora.getHours())}:${pad(ahora.getMinutes())}:${pad(ahora.getSeconds())}`;
    const codigoRef = data.codigo_referencia || '';

    const html = `
      <div class="c4-document" id="c4-document">
        <!-- Watermark text -->
        <div class="reniec-watermark-text">REFERENCIA</div>

        <div class="c4-disclaimer" role="note">
          <span class="material-symbols-outlined" style="font-size:16px">info</span>
          <span>${escHtml(data.aviso || 'Documento de referencia generado a partir de los datos del padrón. No es un certificado oficial de RENIEC y no tiene validez legal.')}</span>
        </div>

        <div>
          <!-- 1. Encabezado de referencia -->
          <div class="reniec-sheet__header">
            <div class="reniec-sheet__logo">${generateReferenceLogoSVG()}</div>
            <div class="reniec-sheet__header-titles">
              <h1>FICHA DE REFERENCIA DE IDENTIFICACIÓN</h1>
              <h2>DATOS DEL PADRÓN CONSULTADO — NO OFICIAL</h2>
            </div>
          </div>
          <div class="reniec-sheet__divider"></div>

          <!-- 2. Cuerpo Estructurado de Datos -->
          <div class="reniec-fields-list">
            <!-- DNI -->
            <div class="reniec-row">
              <div class="reniec-label">DNI:</div>
              <div class="reniec-value">${escHtml(p.dni || '-')}</div>
            </div>

            <!-- Apellido Paterno -->
            <div class="reniec-row">
              <div class="reniec-label">Apellido Paterno:</div>
              <div class="reniec-value">${escHtml(p.ap_pat || '-')}</div>
            </div>

            <!-- Apellido Materno -->
            <div class="reniec-row">
              <div class="reniec-label">Apellido Materno:</div>
              <div class="reniec-value">${escHtml(p.ap_mat || '-')}</div>
            </div>

            <!-- Nombres -->
            <div class="reniec-row">
              <div class="reniec-label">Nombres:</div>
              <div class="reniec-value">${escHtml(p.nombres || '-')}</div>
            </div>

            <!-- Nacimiento -->
            <div class="reniec-row reniec-row--nested">
              <div class="reniec-label">Nacimiento:</div>
              <div class="reniec-subfields">
                <div class="reniec-subrow">
                  <span class="reniec-sublabel">Fecha:</span>
                  <span class="reniec-value">${escHtml(p.fecha_nac || '-')}</span>
                </div>
                <div class="reniec-subrow">
                  <span class="reniec-sublabel">Ubigeo:</span>
                  <span class="reniec-value">${escHtml(p.ubigeo_nac || '-')}</span>
                </div>
              </div>
            </div>

            <!-- Estado Civil -->
            <div class="reniec-row">
              <div class="reniec-label">Estado Civil:</div>
              <div class="reniec-value">${escHtml(p.est_civil || '-')}</div>
            </div>

            <!-- Fecha de Inscripción -->
            <div class="reniec-row">
              <div class="reniec-label">Fecha de Inscripción:</div>
              <div class="reniec-value">${escHtml(p.fch_inscripcion || '-')}</div>
            </div>

            <!-- Nombre del Padre -->
            <div class="reniec-row">
              <div class="reniec-label">Nombre del Padre:</div>
              <div class="reniec-value">${escHtml(p.padre || '-')}</div>
            </div>

            <!-- Nombre de la Madre -->
            <div class="reniec-row">
              <div class="reniec-label">Nombre de la Madre:</div>
              <div class="reniec-value">${escHtml(p.madre || '-')}</div>
            </div>

            <!-- Fecha de Emisión del DNI -->
            <div class="reniec-row">
              <div class="reniec-label">Emisión del DNI:</div>
              <div class="reniec-value">${escHtml(p.fch_emision || '-')}</div>
            </div>

            <!-- Domicilio -->
            <div class="reniec-row reniec-row--nested">
              <div class="reniec-label">Domicilio:</div>
              <div class="reniec-subfields">
                <div class="reniec-subrow">
                  <span class="reniec-sublabel">Departamento:</span>
                  <span class="reniec-value">${escHtml(dom.dpto)}</span>
                </div>
                <div class="reniec-subrow">
                  <span class="reniec-sublabel">Provincia:</span>
                  <span class="reniec-value">${escHtml(dom.prov)}</span>
                </div>
                <div class="reniec-subrow">
                  <span class="reniec-sublabel">Distrito:</span>
                  <span class="reniec-value">${escHtml(dom.dist)}</span>
                </div>
                <div class="reniec-subrow">
                  <span class="reniec-sublabel">Dirección:</span>
                  <span class="reniec-value">${escHtml(p.direccion || '-')}</span>
                </div>
              </div>
            </div>

            <!-- Fecha de Caducidad del DNI -->
            <div class="reniec-row">
              <div class="reniec-label">Caducidad del DNI:</div>
              <div class="reniec-value">${escHtml(p.fch_caducidad || '-')}</div>
            </div>
          </div>
        </div>

        <!-- 3. Información de la Consulta Footer -->
        <div class="reniec-sheet__footer">
          <div class="reniec-consult-title">Información de la Consulta:</div>
          <div class="reniec-consult-grid">
            <div class="reniec-consult-row">
              <span class="reniec-consult-lbl">Usuario:</span>
              <span class="reniec-consult-val">${escHtml(_username || '-')}</span>
            </div>
            <div class="reniec-consult-row">
              <span class="reniec-consult-lbl">Código de referencia:</span>
              <span class="reniec-consult-val">${escHtml(codigoRef || '-')}</span>
            </div>
            <div class="reniec-consult-row">
              <span class="reniec-consult-lbl">Entidad:</span>
              <span class="reniec-consult-val">Buscador de Personas</span>
            </div>
            <div class="reniec-consult-row">
              <span class="reniec-consult-lbl">Validez:</span>
              <span class="reniec-consult-val">Documento de referencia sin validez legal</span>
            </div>
          </div>

          <div class="reniec-sheet__bottom-stamp">
            Ficha de referencia generada por Buscador de Personas — no oficial · ${escHtml(fEmision)}
          </div>
        </div>
      </div>
    `;

    c4Container.innerHTML = html;
  }


  function showDetail(p, index, expand = false, options = {}) {
    const token = ++detailRenderToken;
    personaSeleccionada = p;
    if (expand && detailCollapsed && window.innerWidth > 768) setDetailCollapsed(false);
    resultsList.querySelectorAll('.result-item').forEach((el) => {
      const isActive = Number(el.getAttribute('data-index')) === index;
      el.classList.toggle('result-item--active', isActive);
      el.setAttribute('aria-expanded', isActive ? 'true' : 'false');
    });
    resultsList.querySelectorAll('.result-row').forEach((el) => {
      const isActive = Number(el.getAttribute('data-index')) === index;
      el.classList.toggle('result-row--active', isActive);
      el.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    const html = buildDetailHTML(p);
    if (options.syncUrl !== false) syncUrlState();

    if (prefersReducedMotion()) {
      detailContent.innerHTML = html;
      detailEmpty.classList.add('hidden');
      detailContent.classList.remove('hidden');
      detailContent.style.opacity = '1';
      detailContent.style.transform = 'none';
      bindDetailEvents(detailContent, p);
      return;
    }

    // Transición corta y sólo sobre opacity/transform.
    detailContent.style.opacity = '0';
    detailContent.style.transform = 'translateX(12px)';
    setTimeout(() => {
      if (token !== detailRenderToken) return;
      detailContent.innerHTML = html;
      detailEmpty.classList.add('hidden');
      detailContent.classList.remove('hidden');
      detailContent.style.transition = 'opacity 0.25s cubic-bezier(0.22,1,0.36,1), transform 0.25s cubic-bezier(0.22,1,0.36,1)';
      detailContent.style.opacity = '1';
      detailContent.style.transform = 'translateX(0)';
      bindDetailEvents(detailContent, p);
    }, 60);
  }

  /* ── Panel de detalle redimensionable ────────────────────── */
  function applyDetailWidth(width, persist = true) {
    detailWidth = Math.min(640, Math.max(320, Math.round(width)));
    document.documentElement.style.setProperty('--detail-w', `${detailWidth}px`);
    if (detailResizer) detailResizer.setAttribute('aria-valuenow', String(detailWidth));
    if (persist) {
      try { localStorage.setItem('detail_width', String(detailWidth)); } catch { /* sin almacenamiento */ }
    }
  }

  if (detailResizer) {
    let resizing = false;
    let resizeStartX = 0;
    let resizeStartWidth = 0;

    const startResize = (clientX) => {
      if (window.innerWidth <= 768) return;
      resizing = true;
      resizeStartX = clientX;
      resizeStartWidth = detailPanel ? detailPanel.getBoundingClientRect().width : detailWidth;
      detailResizer.classList.add('is-dragging');
      document.body.classList.add('resizing-detail');
    };

    detailResizer.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      detailResizer.setPointerCapture?.(e.pointerId);
      startResize(e.clientX);
    });

    detailResizer.addEventListener('pointermove', (e) => {
      if (!resizing) return;
      // El panel está a la derecha: mover el puntero a la izquierda lo agranda.
      applyDetailWidth(resizeStartWidth - (e.clientX - resizeStartX), false);
    });

    const stopResize = () => {
      if (!resizing) return;
      resizing = false;
      detailResizer.classList.remove('is-dragging');
      document.body.classList.remove('resizing-detail');
      applyDetailWidth(detailWidth);
    };
    detailResizer.addEventListener('pointerup', stopResize);
    detailResizer.addEventListener('pointercancel', stopResize);
    window.addEventListener('pointerup', stopResize);

    detailResizer.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      applyDetailWidth(detailWidth + (e.key === 'ArrowLeft' ? 24 : -24));
    });
  }
  applyDetailWidth(detailWidth);

  /* ── Mobile sheet ────────────────────────────────────────── */
  function openMobileSheet(html, p) {
    lastFocusedElement = document.activeElement;
    mobileSheetContent.innerHTML = html;
    mobileSheet.classList.add('open');
    mobileSheet.removeAttribute('inert');
    mobileSheet.setAttribute('aria-hidden', 'false');
    mobileSheetOverlay.classList.add('open');
    updateBodyScrollLock();
    bindDetailEvents(mobileSheetContent, p);
    setTimeout(() => {
      const closeBtn = mobileSheet.querySelector('.sheet__close');
      if (closeBtn) closeBtn.focus();
    }, 50);
  }

  function closeMobileSheet() {
    mobileSheet.classList.remove('open');
    mobileSheetOverlay.classList.remove('open');
    updateBodyScrollLock();
    if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
      lastFocusedElement.focus();
    }
    mobileSheet.setAttribute('aria-hidden', 'true');
    mobileSheet.setAttribute('inert', '');
  }

  document.querySelectorAll('[data-close-sheet]').forEach((el) =>
    el.addEventListener('click', closeMobileSheet)
  );

  // Mobile Swipe-down to dismiss bottom sheet
  let sheetTouchStartY = 0;
  let sheetTouchCurrentY = 0;

  if (mobileSheet) {
    mobileSheet.addEventListener('touchstart', (e) => {
      if (mobileSheet.scrollTop <= 0) {
        sheetTouchStartY = e.touches[0].clientY;
      } else {
        sheetTouchStartY = 0;
      }
    }, { passive: true });

    mobileSheet.addEventListener('touchmove', (e) => {
      if (!sheetTouchStartY) return;
      sheetTouchCurrentY = e.touches[0].clientY;
      const diffY = sheetTouchCurrentY - sheetTouchStartY;
      if (diffY > 0) {
        mobileSheet.style.transform = `translateY(${diffY}px)`;
      }
    }, { passive: true });

    mobileSheet.addEventListener('touchend', () => {
      if (!sheetTouchStartY) return;
      const diffY = sheetTouchCurrentY - sheetTouchStartY;
      if (diffY > 90) {
        closeMobileSheet();
      }
      mobileSheet.style.transform = '';
      sheetTouchStartY = 0;
      sheetTouchCurrentY = 0;
    });
  }

  /* ── Error handling ──────────────────────────────────────── */
  function handleApiError(res, data) {
    if (res.status === 401) {
      toast('Sesión expirada. Inicia sesión nuevamente.', 'error');
      showLoginScreen();
      return 'Sesión expirada';
    }
    if (res.status === 403) {
      const detail = data && data.detail ? data.detail : 'Sin consultas disponibles';
      toast(detail, 'warn');
      setEstado(detail, 'error');
      _consultasRestantes = 0;
      updateConsultasBadge();
      return detail;
    }
    if (res.status === 429) {
      const retry = res.headers.get('Retry-After');
      const msg = retry ? `Límite alcanzado. Espera ${retry}s.` : 'Demasiadas consultas.';
      toast(msg, 'warn');
      return msg;
    }
    const detail = data && data.detail ? data.detail : `Error del servidor (${res.status})`;
    toast(detail, 'error');
    return detail;
  }

  /* ── Estado en la URL (compartir y atrás/adelante) ───────── */
  function syncUrlState(options = {}) {
    try {
      const url = new URL(window.location);
      const q = searchInput.value.trim();
      if (q) url.searchParams.set('q', q);
      else url.searchParams.delete('q');
      url.searchParams.set('mode', searchMode);
      const dni = personaSeleccionada && personaSeleccionada.dni
        ? personaSeleccionada.dni
        : null;
      if (dni) url.searchParams.set('dni', dni);
      else url.searchParams.delete('dni');
      if (resultsView === 'table') url.searchParams.set('view', 'table');
      else url.searchParams.delete('view');

      const next = url.pathname + url.search + url.hash;
      const current = window.location.pathname + window.location.search + window.location.hash;
      const state = { q, mode: searchMode, dni, view: resultsView };
      // Sólo crea una entrada nueva si la URL realmente cambió.
      if (options.push && next !== current) {
        window.history.pushState(state, '', url);
      } else {
        window.history.replaceState(state, '', url);
      }
    } catch { /* URL no disponible */ }
  }

  function resetSearchView() {
    if (abortCtrl) {
      abortCtrl.abort();
      abortCtrl = null;
    }
    clearTimeout(debounce);
    setLoading(false);
    personaSeleccionada = null;
    resultados = [];
    resultadosVista = [];
    searchInput.value = '';
    btnClearSearch.classList.remove('visible');
    if (dniCounter) {
      dniCounter.textContent = '0/8';
      dniCounter.classList.add('hidden');
      dniCounter.classList.remove('dni-counter--valid');
    }
    resultsList.innerHTML = '';
    resultsSection.classList.remove('visible');
    resultsSection.setAttribute('aria-busy', 'false');
    emptyState.classList.remove('hidden');
    badgeCount.textContent = '0';
    btnExportar.classList.add('hidden');
    btnExportarJson.classList.add('hidden');
    detailContent.classList.add('hidden');
    detailEmpty.classList.remove('hidden');
    setEstado('Listo para buscar');
  }

  function applyUrlState() {
    let params;
    try { params = new URLSearchParams(window.location.search); } catch { return; }
    const mode = params.get('mode');
    let modeChanged = false;
    if ((mode === 'nombre' || mode === 'dni') && mode !== searchMode) {
      setMode(mode, false);
      modeChanged = true;
    }
    const view = params.get('view');
    if (view === 'table' || view === 'list') {
      resultsView = view;
      updateResultsControls();
    }

    const q = params.get('q');
    const dni = params.get('dni');
    if (!q && !dni) {
      if (resultados.length || searchInput.value.trim()) resetSearchView();
      return;
    }
    if (q && (q !== searchInput.value.trim() || modeChanged)) {
      searchInput.value = q;
      btnClearSearch.classList.add('visible');
      search({ pushHistory: false });
      return;
    }

    // Enlace directo por DNI sin búsqueda previa (o DNI ajeno a los resultados).
    if (!q && dni && (!resultados.length || !resultadosVista.some((p) => p.dni === dni))) {
      setMode('dni', false);
      searchInput.value = dni;
      btnClearSearch.classList.add('visible');
      search({ pushHistory: false });
      return;
    }

    if (resultados.length) {
      renderResults(resultados);
      if (dni) {
        const index = resultadosVista.findIndex((p) => p.dni === dni);
        if (index >= 0) showDetail(resultadosVista[index], index, true);
      }
    }
  }

  // Recupera una búsqueda o un DNI directo desde la URL (también tras login).
  function runSearchFromUrl() {
    let params;
    try { params = new URLSearchParams(window.location.search); } catch { return false; }
    const q = params.get('q');
    const dni = params.get('dni');
    const target = q || dni;
    if (!target) return false;

    const mode = params.get('mode');
    if (mode === 'nombre' || mode === 'dni') {
      setMode(mode, false);
    } else {
      setMode(q && !/^\d{8}$/.test(q) ? 'nombre' : 'dni', false);
    }
    searchInput.value = target;
    btnClearSearch.classList.add('visible');
    if (dniCounter && searchMode === 'dni') {
      dniCounter.textContent = `${target.length}/8`;
      dniCounter.classList.toggle('hidden', target.length === 0);
      dniCounter.classList.toggle('dni-counter--valid', target.length === 8);
    }
    search({ pushHistory: false });
    return true;
  }

  function searchCacheKey(q) {
    const limit = searchMode === 'nombre' ? limiteSelect.value : 'dni';
    return `${searchMode}:${q.toLowerCase()}:${limit}`;
  }

  function cacheSearchResults(key, data) {
    if (!Array.isArray(data) || !data.length) return;
    searchCache.delete(key);
    searchCache.set(key, { data, ts: Date.now() });
    while (searchCache.size > SEARCH_CACHE_MAX) {
      const oldest = searchCache.keys().next().value;
      if (oldest === undefined) break;
      searchCache.delete(oldest);
    }
  }

  function applySearchData(data, q, requestedDni, updateUrl, options = {}) {
    resultados = data;
    renderResults(data);
    if (!data.length && searchMode === 'dni') {
      setEstado('DNI no encontrado en el padrón', 'error');
    } else {
      setEstado(`${data.length} persona${data.length !== 1 ? 's' : ''} encontrada${data.length !== 1 ? 's' : ''}`, 'ok');
    }

    // Animated badge count
    const oldCount = parseInt(badgeCount.textContent) || 0;
    animateValue(badgeCount, oldCount, data.length, 400);
    bumpBadge(badgeCount);

    btnExportar.classList.toggle('hidden', data.length === 0);
    btnExportarJson.classList.toggle('hidden', data.length === 0);
    if (data.length > 0) {
      addRecentSearch(q, searchMode);
      const requestedIndex = requestedDni
        ? resultadosVista.findIndex((p) => p.dni === requestedDni)
        : -1;
      const index = requestedIndex >= 0 ? requestedIndex : 0;
      showDetail(resultadosVista[index], index, false, { syncUrl: updateUrl });
      if (options.decrement !== false) decrementConsultas();
    }
  }

  window.addEventListener('popstate', applyUrlState);

  /* ── Search ──────────────────────────────────────────────── */
  async function search(options = {}) {
    const q = searchInput.value.trim();
    const pushHistory = options.pushHistory !== false;
    const updateUrl = options.updateUrl !== false;

    if (searchMode === 'dni') {
      if (!q) { toast('Ingresa un DNI de 8 dígitos', 'warn'); searchInput.focus(); return; }
      if (!/^\d{8}$/.test(q)) { toast('El DNI debe tener exactamente 8 dígitos', 'warn'); searchInput.focus(); return; }
    } else {
      if (q.length < 3) { toast('Ingresa al menos 3 caracteres', 'warn'); return; }
    }

    // Conserva el DNI solicitado sólo si la URL corresponde a esta misma
    // búsqueda; así un enlace directo restaura la persona seleccionada.
    let requestedDni = null;
    try {
      const params = new URLSearchParams(window.location.search);
      const urlDni = params.get('dni');
      const urlQ = params.get('q');
      const sameSearch = urlQ
        ? urlQ === q
        : (searchMode === 'dni' && urlDni === q);
      if (urlDni && sameSearch) requestedDni = urlDni;
    } catch { /* sin URL */ }
    personaSeleccionada = null;
    if (updateUrl) syncUrlState({ push: pushHistory });

    // Reutiliza resultados de esta sesión: atrás/adelante y búsquedas
    // repetidas no vuelven a consumir cuota ni golpean la base de datos.
    const cacheKey = searchCacheKey(q);
    const cached = searchCache.get(cacheKey);
    if (cached && Date.now() - cached.ts < SEARCH_CACHE_TTL) {
      if (abortCtrl) {
        abortCtrl.abort();
        abortCtrl = null;
      }
      clearTimeout(debounce);
      setLoading(false);
      emptyState.classList.add('hidden');
      resultsSection.classList.add('visible');
      resultsSection.setAttribute('aria-busy', 'false');
      applySearchData(cached.data, q, requestedDni, updateUrl, { decrement: false });
      return;
    }

    if (abortCtrl) abortCtrl.abort();
    const controller = new AbortController();
    abortCtrl = controller;
    const isNombre = searchMode === 'nombre';
    if (!isNombre) { setLoading(true); skeleton(); }
    emptyState.classList.add('hidden');
    resultsSection.classList.add('visible');
    resultsSection.setAttribute('aria-busy', 'true');
    setEstado(isNombre ? 'Buscando coincidencias ponderadas...' : 'Consultando padrón nacional...');

    try {
      let data;
      if (searchMode === 'dni') {
        const res = await apiFetch(`${API_BASE}/persona/${encodeURIComponent(q)}`, {
          signal: controller.signal, headers: apiHeaders(),
        });
        if (res.status === 404) {
          data = []; setEstado('DNI no encontrado en el padrón', 'error'); toast('DNI no encontrado', 'warn');
        } else if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw { handled: true, msg: handleApiError(res, body) };
        } else {
          data = [await res.json()]; toast('Persona localizada con éxito', 'success');
        }
      } else {
        const res = await apiFetch(`${API_BASE}/buscar?q=${encodeURIComponent(q)}&limit=${limiteSelect.value}`, {
          signal: controller.signal, headers: apiHeaders(),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw { handled: true, msg: handleApiError(res, body) };
        }
        data = await res.json();
      }

      // Una búsqueda más reciente ya reemplazó a esta: descarta la respuesta.
      if (abortCtrl !== controller) return;

      cacheSearchResults(cacheKey, data);
      applySearchData(data, q, requestedDni, updateUrl);
    } catch (e) {
      if (e.name === 'AbortError') return;
      // Nunca dejes resultados anteriores exportables tras un fallo.
      resultados = [];
      resultadosVista = [];
      resultsList.innerHTML = '';
      badgeCount.textContent = '0';
      btnExportar.classList.add('hidden');
      btnExportarJson.classList.add('hidden');
      if (!e.handled) {
        setEstado('Error al consultar el servidor', 'error');
        toast('Error de conexión con la API', 'error');
      } else if (e.msg) {
        setEstado(e.msg, 'error');
      }
    } finally {
      if (abortCtrl === controller) {
        setLoading(false);
        resultsSection.setAttribute('aria-busy', 'false');
        abortCtrl = null;
      }
    }
  }

  /* ── Search input events ─────────────────────────────────── */
  $('btn-search').addEventListener('click', () => search());

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { clearTimeout(debounce); search(); }
  });

  searchInput.addEventListener('input', () => {
    const val = searchInput.value;
    btnClearSearch.classList.toggle('visible', val.length > 0);

    if (searchMode === 'dni') {
      const clean = val.replace(/\D/g, '').slice(0, 8);
      if (searchInput.value !== clean) searchInput.value = clean;
      const len = clean.length;
      if (dniCounter) {
        dniCounter.textContent = `${len}/8`;
        dniCounter.classList.toggle('hidden', len === 0);
        dniCounter.classList.toggle('dni-counter--valid', len === 8);
      }
    } else {
      if (dniCounter) dniCounter.classList.add('hidden');
      clearTimeout(debounce);
      const q = val.trim();
      if (q.length >= 3) {
        debounce = setTimeout(() => search({ pushHistory: false, updateUrl: false }), 350);
      }
    }
  });

  btnClearSearch.addEventListener('click', () => {
    searchInput.value = '';
    btnClearSearch.classList.remove('visible');
    if (dniCounter) {
      dniCounter.textContent = '0/8';
      dniCounter.classList.add('hidden');
      dniCounter.classList.remove('dni-counter--valid');
    }
    searchInput.focus();
  });

  /* ── CSV & JSON Export ────────────────────────────────────── */
  function csvCell(value) {
    let s = String(value == null ? '' : value);
    // Neutraliza fórmulas al abrir el CSV en Excel/LibreOffice.
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return `"${s.replace(/"/g, '""')}"`;
  }

  btnExportar.addEventListener('click', () => {
    if (!resultadosVista.length) return;
    const h = ['DNI', 'Dígito RUC', 'Nombres', 'Ape. Paterno', 'Ape. Materno', 'Sexo', 'Estado Civil', 'Fecha Nacimiento', 'Edad', 'Padre', 'Madre', 'Dirección', 'Ubigeo Dom', 'Ubigeo Nac', 'Fch Emisión', 'Fch Inscripción', 'Fch Caducidad'];
    const r = resultadosVista.map((p) => [
      p.dni || '', p.dig_ruc || '', p.nombres || '', p.ap_pat || '', p.ap_mat || '',
      p.sexo || '', p.est_civil || '', p.fecha_nac || '', p.edad_texto || p.edad_anios || '',
      p.padre || '', p.madre || '', p.direccion || '', p.ubigeo_dir || '', p.ubigeo_nac || '',
      p.fch_emision || '', p.fch_inscripcion || '', p.fch_caducidad || '',
    ]);
    const csv = [h.map(csvCell).join(','), ...r.map((row) => row.map(csvCell).join(','))].join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: `padron_personas_${new Date().toISOString().slice(0, 10)}.csv`,
    });
    a.click(); a.remove();
    toast('Reporte CSV con todos los campos descargado', 'success');
  });

  btnExportarJson.addEventListener('click', () => {
    if (!resultadosVista.length) return;
    const blob = new Blob([JSON.stringify(resultadosVista, null, 2)], { type: 'application/json' });
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: `padron_personas_${new Date().toISOString().slice(0, 10)}.json`,
    });
    a.click(); a.remove();
    toast('Datos completos exportados a JSON', 'success');
  });

  /* ── Quick Search Modal (Ctrl+K) ─────────────────────────── */
  function openQS() {
    if (!qsModal.classList.contains('open')) lastFocusedQS = document.activeElement;
    qsModal.classList.add('open');
    qsModal.removeAttribute('inert');
    qsModal.setAttribute('aria-hidden', 'false');
    updateBodyScrollLock();
    qsInput.value = '';
    qsResults.innerHTML = '<p class="qs-empty">Escribe para buscar al instante...</p>';
    setTimeout(() => qsInput.focus(), 100);
  }

  function closeQS() {
    qsModal.classList.remove('open');
    updateBodyScrollLock();
    if (qsAbort) qsAbort.abort();
    if (lastFocusedQS && typeof lastFocusedQS.focus === 'function') lastFocusedQS.focus();
    qsModal.setAttribute('aria-hidden', 'true');
    qsModal.setAttribute('inert', '');
  }

  async function qsSearch(query) {
    if (qsAbort) qsAbort.abort();
    if (!query || query.length < 3) {
      qsResults.innerHTML = '<p class="qs-empty">Mínimo 3 caracteres...</p>';
      return;
    }

    const controller = new AbortController();
    qsAbort = controller;
    qsResults.innerHTML = '<div style="padding:32px"><div class="qs-spinner"></div></div>';
    const isDni = /^\d{8}$/.test(query.trim());

    try {
      let data;
      if (isDni) {
        const res = await apiFetch(`${API_BASE}/persona/${encodeURIComponent(query.trim())}`, {
          signal: controller.signal, headers: apiHeaders(),
        });
        if (res.status === 404) data = [];
        else if (!res.ok) throw new Error();
        else data = [await res.json()];
      } else {
        const res = await apiFetch(`${API_BASE}/buscar?q=${encodeURIComponent(query)}&limit=6`, {
          signal: controller.signal, headers: apiHeaders(),
        });
        if (!res.ok) throw new Error();
        data = await res.json();
      }

      if (qsAbort !== controller) return;
      if (!data.length) {
        qsResults.innerHTML = '<p class="qs-empty">Sin resultados coincidentes</p>';
        return;
      }

      qsResults.innerHTML = data.map((p, i) => {
        const n = nombre(p);
        const g = sexoLetra(p.sexo);
        return `<button class="qs-item" data-i="${i}">
          <div class="qs-item__avatar">
            <span class="material-symbols-outlined">${g === 'F' ? 'woman' : 'person'}</span>
          </div>
          <div class="qs-item__body">
            <p class="qs-item__name">${escHtml(n || '-')}</p>
            <p class="qs-item__dni">DNI ${escHtml(p.dni || '-')}</p>
          </div>
          <span class="qs-item__meta" style="font-size:11px;color:var(--text-5);">${escHtml(p.sexo || '')} &middot; ${p.edad_anios ? p.edad_anios + 'a' : ''}</span>
        </button>`;
      }).join('');

      qsResults.querySelectorAll('.qs-item').forEach((btn, i) => {
        btn.addEventListener('click', () => {
          closeQS();
          setMode(/^\d{8}$/.test(query.trim()) ? 'dni' : 'nombre');
          addRecentSearch(query.trim(), searchMode);
          resultados = data;
          searchInput.value = query;
          btnClearSearch.classList.add('visible');
          emptyState.classList.add('hidden');
          resultsSection.classList.add('visible');
          personaSeleccionada = null;
          renderResults(data);
          syncUrlState({ push: true });
          setEstado(`${data.length} resultado${data.length !== 1 ? 's' : ''}`, 'ok');
          badgeCount.textContent = data.length;
          btnExportar.classList.remove('hidden');
          btnExportarJson.classList.remove('hidden');
          if (resultadosVista.length) showDetail(resultadosVista[0], 0, true);
        });
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      qsResults.innerHTML = '<p class="qs-empty qs-error">Error de conexión</p>';
    }
  }

  document.querySelector('[data-close-modal]').addEventListener('click', closeQS);
  $('btn-quick-search').addEventListener('click', openQS);

  qsInput.addEventListener('input', (e) => {
    clearTimeout(qsTimer);
    qsTimer = setTimeout(() => qsSearch(e.target.value.trim()), 300);
  });
  qsInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeQS();
    if (e.key === 'Enter') { clearTimeout(qsTimer); qsSearch(qsInput.value.trim()); }
  });

  /* ── Keyboard shortcuts & navigation ─────────────────────── */
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openQS();
      return;
    }
    if (e.key === 'Escape') {
      if (c4Modal && c4Modal.classList.contains('open')) { closeC4Modal(); return; }
      if (treeModal && treeModal.classList.contains('open')) { closeTreeModal(); return; }
      if (qsModal && qsModal.classList.contains('open')) { closeQS(); return; }
      if (mobileSheet && mobileSheet.classList.contains('open')) { closeMobileSheet(); return; }
      if (adminOverlay && adminOverlay.classList.contains('show')) { closeAdminPanel(); return; }
    }

    const modalOpen = (treeModal && treeModal.classList.contains('open')) ||
      (c4Modal && c4Modal.classList.contains('open')) ||
      (qsModal && qsModal.classList.contains('open')) ||
      (mobileSheet && mobileSheet.classList.contains('open')) ||
      (adminOverlay && adminOverlay.classList.contains('show'));
    if (modalOpen) {
      if (e.key === 'Tab') trapFocus(e, activeModalElement());
      return;
    }

    // Atajos de productividad (sólo fuera de campos de texto).
    if (!isTypingTarget(e.target) && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (e.key === '/') {
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
        return;
      }
      if ((e.key === 't' || e.key === 'T') && personaSeleccionada) {
        e.preventDefault();
        openTreeModal(personaSeleccionada.dni);
        return;
      }
      if ((e.key === 'c' || e.key === 'C') && personaSeleccionada) {
        e.preventDefault();
        openC4Modal(personaSeleccionada.dni);
        return;
      }
      if (e.key === '?') {
        e.preventDefault();
        toast('Atajos: / buscar · ↑↓ navegar · T árbol · C ficha · Ctrl+K búsqueda rápida · Esc cerrar', 'info', { duration: 6500 });
        return;
      }
    }

    // Navegación con flechas en la lista de resultados.
    if (resultadosVista.length > 0) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (isTypingTarget(e.target) && document.activeElement !== searchInput) return;
        e.preventDefault();
        if (document.activeElement === searchInput) searchInput.blur();

        let curIdx = resultadosVista.findIndex((p) => personaSeleccionada && p.dni === personaSeleccionada.dni);
        if (e.key === 'ArrowDown') {
          curIdx = curIdx < 0 ? 0 : (curIdx + 1) % resultadosVista.length;
        } else {
          curIdx = curIdx <= 0 ? resultadosVista.length - 1 : curIdx - 1;
        }

        showResultAtIndex(curIdx);
        const items = resultsList.querySelectorAll('.result-item, .result-row');
        if (items[curIdx]) {
          items[curIdx].scrollIntoView({ block: 'nearest', behavior: scrollBehavior() });
        }
      }
    }
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth >= 769) {
      if (mobileSheet && mobileSheet.classList.contains('open')) closeMobileSheet();
      updateBodyScrollLock();
    }
  });

  /* ── Service Worker (PWA) ────────────────────────────────── */
  if ('serviceWorker' in navigator && window.location.protocol === 'https:') {
    const showUpdateToast = (registration) => {
      if (!registration || !registration.waiting) return;
      toast('Nueva versión disponible. Recarga para actualizar.', 'info', {
        duration: 15000,
        actionLabel: 'Actualizar',
        onAction: () => {
          swRefreshing = true;
          registration.waiting.postMessage({ type: 'SKIP_WAITING' });
        },
      });
    };

    window.addEventListener('load', async () => {
      try {
        const registration = await navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' });
        if (registration.waiting) showUpdateToast(registration);
        registration.addEventListener('updatefound', () => {
          const worker = registration.installing;
          if (!worker) return;
          worker.addEventListener('statechange', () => {
            if (worker.state === 'installed' && navigator.serviceWorker.controller) {
              showUpdateToast(registration);
            }
          });
        });
      } catch { /* sin service worker */ }
    });

    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (swRefreshing) {
        window.location.reload();
        return;
      }
      // Primera instalación: no recargar, el cache ya está listo.
    });
  }

  /* ── Init ────────────────────────────────────────────────── */
  // Init parallax
  initParallax();

  // Ripple on interactive buttons
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-action, .btn-outline, .btn-ruc, .chip');
    if (btn) addRipple(e, btn);
  });

  /* ── Login / Logout / Admin Panel ────────────────────────── */
  const loginOverlay = $('login-overlay');
  const loginForm = $('login-form');
  const loginUser = $('login-user');
  const loginPass = $('login-pass');
  const loginError = $('login-error');
  const btnLoginEl = $('btn-login');
  const consultasBadge = $('consultas-badge');
  const consultasCount = $('consultas-count');
  const btnOpenAdmin = $('btn-open-admin');
  const btnLogout = $('btn-logout');
  const adminOverlay = $('admin-overlay');
  const adminBackdrop = $('admin-backdrop');
  const btnCloseAdmin = $('btn-close-admin');
  const adminTableBody = $('admin-table-body');
  const btnCrearUsuario = $('btn-crear-usuario');
  const adminMsg = $('admin-msg');

  function updateConsultasBadge() {
    if (_userRol === 'admin') {
      consultasCount.textContent = '∞';
      consultasBadge.className = 'consultas-badge';
    } else {
      consultasCount.textContent = _consultasRestantes;
      consultasBadge.className = 'consultas-badge' +
        (_consultasRestantes <= 0 ? ' consultas-badge--empty' :
         _consultasRestantes <= 10 ? ' consultas-badge--warn' : '');
    }
  }

  function decrementConsultas() {
    if (_userRol === 'admin') return;
    _consultasRestantes = Math.max(0, _consultasRestantes - 1);
    updateConsultasBadge();
  }

  async function refreshUserInfo() {
    try {
      const res = await apiFetch(`${API_BASE}/api/auth/me`, { headers: apiHeaders() });
      if (res.ok) {
        const data = await res.json();
        applySession(data);
        updateConsultasBadge();
        return true;
      }
      if (res.status === 401) {
        showLoginScreen();
      }
      return false;
    } catch {
      return false;
    }
  }

  function clearSensitiveState() {
    // Al cerrar sesión o expirar la cookie, no dejamos datos personales en
    // memoria, en el DOM ni en el historial local de búsquedas.
    searchCache.clear();
    treeCache.clear();
    treeData = null;
    treeRootDni = null;
    treeRequestToken += 1;
    c4RequestToken += 1;
    resultados = [];
    resultadosVista = [];
    resetSearchView();
    if (detailContent) detailContent.innerHTML = '';
    if (mobileSheetContent) mobileSheetContent.innerHTML = '';
    if (treeContainer) treeContainer.innerHTML = '';
    if (treeTitularBadge) treeTitularBadge.textContent = '';
    if (treeStatsBar) treeStatsBar.innerHTML = '';
    if (c4Container) c4Container.innerHTML = '';
    if (qsResults) qsResults.innerHTML = '<p class="qs-empty">Escribe para buscar al instante...</p>';
    if (adminTableBody) adminTableBody.innerHTML = '';
    lastFocusedElement = null;
    lastFocusedC4 = null;
    lastFocusedQS = null;
    lastFocusedAdmin = null;
    try { localStorage.removeItem('recent_searches'); } catch { /* sin almacenamiento */ }
    renderRecentSearches();
  }

  function showLoginScreen() {
    clearAuth();
    if (loginError) loginError.classList.remove('show');
    if (loginPass) {
      loginPass.value = '';
      loginPass.type = 'password';
    }
    if (eyeIcon) eyeIcon.textContent = 'visibility';
    if (btnTogglePassword) {
      btnTogglePassword.setAttribute('aria-pressed', 'false');
      btnTogglePassword.setAttribute('aria-label', 'Mostrar contraseña');
    }
    closeAdminPanel({ restoreFocus: false });
    if (c4Modal && c4Modal.classList.contains('open')) closeC4Modal();
    if (treeModal && treeModal.classList.contains('open')) closeTreeModal();
    if (qsModal && qsModal.classList.contains('open')) closeQS();
    if (mobileSheet && mobileSheet.classList.contains('open')) closeMobileSheet();
    clearSensitiveState();
    if (btnOpenAdmin) {
      btnOpenAdmin.classList.add('hidden');
      btnOpenAdmin.setAttribute('aria-expanded', 'false');
    }
    if (loginOverlay) {
      loginOverlay.classList.remove('hidden');
      loginOverlay.removeAttribute('inert');
      loginOverlay.setAttribute('aria-hidden', 'false');
    }
    document.body.classList.add('login-visible');
    if (appHeader) appHeader.setAttribute('inert', '');
    if (appMain) appMain.setAttribute('inert', '');
    if (loginUser) loginUser.focus();
  }

  function hideLoginScreen() {
    if (loginOverlay) {
      loginOverlay.classList.add('hidden');
      loginOverlay.setAttribute('aria-hidden', 'true');
      loginOverlay.setAttribute('inert', '');
    }
    document.body.classList.remove('login-visible');
    if (appHeader) appHeader.removeAttribute('inert');
    if (appMain) appMain.removeAttribute('inert');
    updateConsultasBadge();
    if (_userRol === 'admin') {
      btnOpenAdmin.classList.remove('hidden');
    } else {
      btnOpenAdmin.classList.add('hidden');
    }
  }

  const btnTogglePassword = $('btn-toggle-password');
  const eyeIcon = $('eye-icon');
  if (btnTogglePassword && eyeIcon && loginPass) {
    btnTogglePassword.addEventListener('click', (e) => {
      e.preventDefault();
      const isPass = loginPass.type === 'password';
      loginPass.type = isPass ? 'text' : 'password';
      eyeIcon.textContent = isPass ? 'visibility_off' : 'visibility';
      btnTogglePassword.setAttribute('aria-pressed', isPass ? 'true' : 'false');
      btnTogglePassword.setAttribute('aria-label', isPass ? 'Ocultar contraseña' : 'Mostrar contraseña');
    });
  }

  // Login form
  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    loginError.classList.remove('show');
    btnLoginEl.disabled = true;
    btnLoginEl.innerHTML = `
      <span class="qs-spinner" style="width:16px;height:16px;margin:0;border-width:2px;display:inline-block"></span>
      <span>Verificando...</span>
    `;

    try {
      const res = await apiFetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUser.value.trim(), password: loginPass.value }),
      });

      if (res.ok) {
        const data = await res.json();
        applySession(data);
        hideLoginScreen();
        loginForm.reset();
        loginPass.type = 'password';
        if (eyeIcon) eyeIcon.textContent = 'visibility';
        if (btnTogglePassword) {
          btnTogglePassword.setAttribute('aria-pressed', 'false');
          btnTogglePassword.setAttribute('aria-label', 'Mostrar contraseña');
        }
        checkConnection();
        if (!runSearchFromUrl()) searchInput.focus();
      } else {
        const err = await res.json().catch(() => ({}));
        loginError.textContent = err.detail || 'Usuario o contraseña incorrectos';
        loginError.classList.add('show');
      }
    } catch {
      loginError.textContent = 'Error de conexión con el servidor';
      loginError.classList.add('show');
    } finally {
      btnLoginEl.disabled = false;
      btnLoginEl.innerHTML = `
        <span>Iniciar Sesión</span>
        <span class="material-symbols-outlined btn-login__icon">arrow_forward</span>
      `;
    }
  });

  // Logout
  btnLogout.addEventListener('click', async () => {
    try {
      await apiFetch(`${API_BASE}/api/auth/logout`, { method: 'POST' });
    } catch { /* la sesión local se limpia igualmente */ }
    showLoginScreen();
  });

  // Admin Panel
  function openAdminPanel(opener) {
    if (!adminOverlay || adminOverlay.classList.contains('show')) return;
    if (document.body.classList.contains('login-visible')) return;
    lastFocusedAdmin = opener || (document.activeElement && document.activeElement !== document.body
      ? document.activeElement
      : btnOpenAdmin);
    adminOverlay.classList.add('show');
    adminOverlay.removeAttribute('inert');
    adminOverlay.setAttribute('aria-hidden', 'false');
    if (btnOpenAdmin) btnOpenAdmin.setAttribute('aria-expanded', 'true');
    updateBodyScrollLock();
    loadAdminUsers();
    setTimeout(() => { if (btnCloseAdmin) btnCloseAdmin.focus(); }, 60);
  }

  function closeAdminPanel(options = {}) {
    if (!adminOverlay) return;
    const wasOpen = adminOverlay.classList.contains('show');
    adminOverlay.classList.remove('show');
    adminOverlay.setAttribute('aria-hidden', 'true');
    adminOverlay.setAttribute('inert', '');
    if (btnOpenAdmin) btnOpenAdmin.setAttribute('aria-expanded', 'false');
    if (!wasOpen) return;
    updateBodyScrollLock();
    if (options.restoreFocus !== false && lastFocusedAdmin && typeof lastFocusedAdmin.focus === 'function') {
      lastFocusedAdmin.focus();
    }
    lastFocusedAdmin = null;
  }

  btnOpenAdmin.addEventListener('click', (event) => openAdminPanel(event.currentTarget));
  btnCloseAdmin.addEventListener('click', () => closeAdminPanel());
  adminBackdrop.addEventListener('click', () => closeAdminPanel());

  function showAdminMsg(msg, ok) {
    adminMsg.textContent = msg;
    adminMsg.className = 'admin-msg ' + (ok ? 'admin-msg--ok' : 'admin-msg--err');
    setTimeout(() => { adminMsg.className = 'admin-msg'; }, 3000);
  }

  async function loadAdminUsers() {
    try {
      const res = await apiFetch(`${API_BASE}/api/admin/usuarios`, { headers: apiHeaders() });
      if (!res.ok) return;
      const users = await res.json();
      adminTableBody.innerHTML = users.map(u => {
        const rolBadge = u.rol === 'admin'
          ? '<span class="badge-rol badge-rol--admin">Admin</span>'
          : '<span class="badge-rol badge-rol--user">User</span>';
        const statusBadge = u.activo
          ? '<span class="badge-status badge-status--active">Activo</span>'
          : '<span class="badge-status badge-status--inactive">Inactivo</span>';
        const restantes = Math.max(0, Number(u.consultas_max) - Number(u.consultas_usadas));
        const isAdmin = u.rol === 'admin';
        const id = Number(u.id);
        const max = Number(u.consultas_max);
        return `<tr>
          <td>${escHtml(id)}</td>
          <td><strong>${escHtml(u.username)}</strong></td>
          <td>${rolBadge}</td>
          <td class="consultas-cell">${escHtml(u.consultas_usadas)} / ${escHtml(u.consultas_max)} <small style="color:var(--text-5)">(${escHtml(restantes)} rest.)</small></td>
          <td>${statusBadge}</td>
          <td>
            <div class="admin-actions-cell">
              ${!isAdmin ? `
                <button class="btn-admin-action" data-admin-action="add" data-id="${escHtml(id)}" data-max="${escHtml(max)}" title="Agregar 100 consultas" aria-label="Agregar 100 consultas a ${escHtml(u.username)}">
                  <span class="material-symbols-outlined" aria-hidden="true">add_circle</span>
                </button>
                <button class="btn-admin-action" data-admin-action="toggle" data-id="${escHtml(id)}" data-active="${u.activo ? '1' : '0'}" title="${u.activo ? 'Desactivar' : 'Activar'}" aria-label="${u.activo ? 'Desactivar' : 'Activar'} a ${escHtml(u.username)}">
                  <span class="material-symbols-outlined" aria-hidden="true">${u.activo ? 'block' : 'check_circle'}</span>
                </button>
                <button class="btn-admin-action btn-admin-action--danger" data-admin-action="delete" data-id="${escHtml(id)}" data-username="${escHtml(u.username)}" title="Eliminar" aria-label="Eliminar a ${escHtml(u.username)}">
                  <span class="material-symbols-outlined" aria-hidden="true">delete</span>
                </button>
              ` : '<span style="color:var(--text-5);font-size:11px">—</span>'}
            </div>
          </td>
        </tr>`;
      }).join('');

      adminTableBody.querySelectorAll('[data-admin-action]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const action = btn.getAttribute('data-admin-action');
          const id = parseInt(btn.getAttribute('data-id') || '', 10);
          if (!Number.isInteger(id) || id <= 0) return;
          if (action === 'add') {
            const currentMax = parseInt(btn.getAttribute('data-max') || '0', 10);
            adminAddConsultas(id, Number.isFinite(currentMax) ? currentMax : 0);
          } else if (action === 'toggle') {
            adminToggle(id, btn.getAttribute('data-active') !== '1');
          } else if (action === 'delete') {
            adminDelete(id, btn.getAttribute('data-username') || '');
          }
        });
      });
    } catch {
      adminTableBody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--red)">Error al cargar usuarios</td></tr>';
    }
  }

  async function adminAddConsultas(id, currentMax) {
    const res = await apiFetch(`${API_BASE}/api/admin/usuarios/${id}`, {
      method: 'PUT',
      headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ consultas_max: currentMax + 100 }),
    });
    if (res.ok) { showAdminMsg('+100 consultas agregadas', true); loadAdminUsers(); }
    else showAdminMsg('Error al actualizar', false);
  }

  async function adminToggle(id, newState) {
    const res = await apiFetch(`${API_BASE}/api/admin/usuarios/${id}`, {
      method: 'PUT',
      headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ activo: newState }),
    });
    if (res.ok) { showAdminMsg(newState ? 'Usuario activado' : 'Usuario desactivado', true); loadAdminUsers(); }
    else showAdminMsg('Error al actualizar', false);
  }

  async function adminDelete(id, username) {
    if (!confirm(`¿Eliminar al usuario "${username}"?`)) return;
    const res = await apiFetch(`${API_BASE}/api/admin/usuarios/${id}`, {
      method: 'DELETE',
      headers: apiHeaders(),
    });
    if (res.ok) { showAdminMsg(`Usuario "${username}" eliminado`, true); loadAdminUsers(); }
    else showAdminMsg('Error al eliminar', false);
  }

  // Create user
  btnCrearUsuario.addEventListener('click', async () => {
    const username = $('admin-new-user').value.trim();
    const password = $('admin-new-pass').value;
    const consultas = parseInt($('admin-new-consultas').value) || 100;

    if (!username || !password) { showAdminMsg('Completa usuario y contraseña', false); return; }

    const res = await apiFetch(`${API_BASE}/api/admin/usuarios`, {
      method: 'POST',
      headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, consultas_max: consultas }),
    });

    if (res.ok) {
      showAdminMsg(`Usuario "${username}" creado con ${consultas} consultas`, true);
      $('admin-new-user').value = '';
      $('admin-new-pass').value = '';
      $('admin-new-consultas').value = '100';
      loadAdminUsers();
    } else {
      const err = await res.json().catch(() => ({}));
      showAdminMsg(err.detail || 'Error al crear usuario', false);
    }
  });

  // La interceptación de 401 se centraliza en apiFetch.

  /* ── Boot ──────────────────────────────────────────────── */
  async function bootstrap() {
    clearLegacyAuthStorage();

    const urlParams = new URLSearchParams(window.location.search);
    const initialQ = urlParams.get('q');
    const initialMode = urlParams.get('mode');

    // Sin modo explícito, un texto no numérico se interpreta como nombre.
    if (initialMode === 'nombre' || initialMode === 'dni') {
      setMode(initialMode, false);
    } else {
      setMode(initialQ && !/^\d{8}$/.test(initialQ) ? 'nombre' : 'dni', false);
    }

    const initialView = urlParams.get('view');
    if (initialView === 'table' || initialView === 'list') resultsView = initialView;
    updateResultsControls();
    applyDetailWidth(detailWidth);

    checkConnection();
    setInterval(checkConnection, 30000);

    // La cookie HttpOnly es la única fuente de verdad de la sesión.
    const autenticado = await refreshUserInfo();
    if (!autenticado) {
      showLoginScreen();
      return;
    }

    hideLoginScreen();

    // Restaura ?q= o ?dni= después de autenticar; si no hay enlace, enfoca.
    if (!runSearchFromUrl()) searchInput.focus();
  }

  bootstrap();
})();
