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
  const searchInput       = $('search-input');
  const btnClearSearch    = $('btn-clear-search');
  const modeDni           = $('mode-dni');
  const modeNombre        = $('mode-nombre');
  const limitRow          = $('limit-row');
  const limiteSelect      = $('limite');
  const resultsSection    = $('results-section');
  const resultsList       = $('results-list');
  const badgeCount        = $('badge-count');
  const estadoTexto       = $('estado-texto');
  const btnExportar       = $('btn-exportar');
  const btnExportarJson   = $('btn-exportar-json');
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
    if (start === end) { el.textContent = end; return; }
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

  function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast toast--${type}`;
    const icon = document.createElement('span');
    icon.className = 'material-symbols-outlined';
    icon.textContent = TOAST_ICONS[type] || TOAST_ICONS.info;
    const text = document.createElement('span');
    text.textContent = String(msg == null ? '' : msg);
    el.append(icon, text);
    toastContainer.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateX(20px)';
      setTimeout(() => el.remove(), 300);
    }, 3500);
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
          <span>${r.mode === 'dni' ? '🆔' : '👤'}</span>
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
  function setMode(mode) {
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
    searchInput.focus();
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

  /* ── Render results list ─────────────────────────────────── */
  function renderResults(data) {
    if (!data || data.length === 0) {
      resultsList.innerHTML = `<div class="empty-state" style="padding:54px 16px">
        <span class="material-symbols-outlined" style="font-size:42px;color:var(--text-6);margin-bottom:12px">search_off</span>
        <p style="font-weight:600;color:var(--text-4)">No se encontraron registros</p>
        <p style="font-size:12px;color:var(--text-5);margin-top:4px">Intenta verificar el número de documento o escribe otros apellidos</p>
      </div>`;
      badgeCount.textContent = '0';
      return;
    }

    const busqueda = searchInput.value.trim().toLowerCase();
    let html = '';
    data.forEach((p, i) => {
      const n = nombre(p);
      let nHtml = escHtml(n || '-');
      if (busqueda && n) {
        const safe = busqueda.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const re = new RegExp(`(${safe})`, 'gi');
        nHtml = escHtml(n).replace(re, '<mark>$1</mark>');
      }
      const g = sexoLetra(p.sexo);
      const dot = g === 'M' ? 'status-dot--male' : g === 'F' ? 'status-dot--female' : 'status-dot--neutral';
      const active = personaSeleccionada && personaSeleccionada.dni === p.dni ? ' result-item--active' : '';

      // Monogram initials & semantic styling
      const primerNombre = (p.nombres || '').trim().split(/\s+/)[0] || '';
      const primerApe = (p.ap_pat || '').trim() || '';
      const iniciales = ((primerNombre[0] || '') + (primerApe[0] || '')).toUpperCase() || (g === 'F' ? 'F' : 'M');
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

      // Inline detail summary for mobile
      const fechaNac = p.fecha_nac ? `${escHtml(p.fecha_nac)} (${p.edad_anios || '-'} años)` : '-';
      const padres = [p.padre ? `P: ${p.padre}` : '', p.madre ? `M: ${p.madre}` : ''].filter(Boolean).join(' · ') || 'No registrados';
      const ubigeoDir = p.ubigeo_dir || p.ubigeo_nac || '-';

      html += `<div class="result-item slide-up stagger-${Math.min(i + 1, 8)}${active}" data-index="${i}">
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
          <span class="material-symbols-outlined result-item__chevron">chevron_right</span>
        </div>
        ${p.direccion ? `<p class="result-item__address"><span class="material-symbols-outlined">location_on</span>${escHtml(p.direccion)}</p>` : ''}
        
        <!-- Mobile Inline Expandable Detail -->
        <div class="result-item__inline-detail">
          <div style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--text-3);">
            <div><strong style="color:var(--text-4)">Nacimiento:</strong> ${fechaNac}</div>
            <div><strong style="color:var(--text-4)">Padres:</strong> ${escHtml(padres)}</div>
            <div><strong style="color:var(--text-4)">Ubigeo:</strong> ${escHtml(ubigeoDir)}</div>
          </div>
          <div class="inline-actions-grid">
            <button class="btn-inline-action btn-inline-action--primary" data-inline-action="tree" data-dni="${escHtml(p.dni)}">
              <span class="material-symbols-outlined" style="font-size:15px">account_tree</span>
              <span>Árbol</span>
            </button>
            <button class="btn-inline-action btn-inline-action--c4" data-inline-action="c4" data-dni="${escHtml(p.dni)}" title="Ficha de referencia (no oficial)">
              <span class="material-symbols-outlined" style="font-size:15px">print</span>
              <span>C4</span>
            </button>
            <button class="btn-inline-action" data-inline-action="copy" data-index="${i}">
              <span class="material-symbols-outlined" style="font-size:15px">content_copy</span>
              <span>Copiar</span>
            </button>
          </div>
        </div>
      </div>`;
    });

    resultsList.innerHTML = html;
    resultsList.querySelectorAll('.result-item').forEach((el, i) => {
      el.addEventListener('click', (e) => {
        const actionBtn = e.target.closest('[data-inline-action]');
        if (actionBtn) {
          const action = actionBtn.getAttribute('data-inline-action');
          const dni = actionBtn.getAttribute('data-dni');
          if (action === 'tree') {
            openTreeModal(dni);
          } else if (action === 'c4') {
            openC4Modal(dni);
          } else if (action === 'copy') {
            const p = data[i];
            const fullSummary = `DATOS DE IDENTIFICACIÓN (DNI)\n` +
              `────────────────────────────────────────\n` +
              `DNI: ${p.dni || '-'}\n` +
              `NOMBRES: ${p.nombres || '-'}\n` +
              `APELLIDOS: ${p.ap_pat || '-'} ${p.ap_mat || '-'}\n` +
              `FECHA NAC: ${p.fecha_nac || '-'}\n` +
              `DIRECCIÓN: ${p.direccion || '-'}\n` +
              `UBIGEO: ${p.ubigeo_dir || '-'}`;
            navigator.clipboard.writeText(fullSummary).then(() => toast('Ficha copiada', 'success'));
          }
          return;
        }

        // On mobile (<= 768px): toggle inline expansion smoothly without intrusive modal popups
        if (window.innerWidth <= 768) {
          const isExpanded = el.classList.contains('result-item--expanded');
          resultsList.querySelectorAll('.result-item').forEach(item => item.classList.remove('result-item--expanded'));
          if (!isExpanded) {
            el.classList.add('result-item--expanded');
            personaSeleccionada = data[i];
            setTimeout(() => {
              el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, 80);
          }
          return;
        }

        // On desktop (> 768px): normal showDetail
        showDetail(data[i], i);
      });
    });
  }

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
          <button class="btn-action" id="btn-tree" title="Ver árbol genealógico">
            <span class="material-symbols-outlined">account_tree</span>
            <span>Árbol</span>
          </button>
          <button class="btn-action" id="btn-c4-direct" title="Ver ficha de referencia (no oficial)">
            <span class="material-symbols-outlined" style="color:#38bdf8">description</span>
            <span>C4</span>
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

  function bindDetailEvents(container, p) {
    const copyBtn = container.querySelector('#btn-copy-dni');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(String(p.dni)).then(() => {
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

        navigator.clipboard.writeText(fullSummary).then(() => {
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

        navigator.clipboard.writeText(fullReport).then(() => {
          toast('Reporte formateado copiado al portapapeles', 'success');
        }).catch(() => toast('Error al copiar reporte', 'error'));
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
    applyTreeTransform();
  }

  function setTreeZoom(delta) {
    treeZoom = Math.min(2.2, Math.max(0.4, treeZoom + delta));
    applyTreeTransform();
  }

  // Pan & Zoom controls
  if (btnTreeZoomIn) btnTreeZoomIn.addEventListener('click', () => setTreeZoom(0.15));
  if (btnTreeZoomOut) btnTreeZoomOut.addEventListener('click', () => setTreeZoom(-0.15));
  if (btnTreeReset) btnTreeReset.addEventListener('click', resetTreeTransform);

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
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.08 : -0.08;
      setTreeZoom(delta);
    }, { passive: false });

    // Touch Support (Pinch to Zoom & Drag)
    treeViewport.addEventListener('touchstart', (e) => {
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

  function openTreeModal(dni) {
    if (!treeModal) return;
    treeModal.classList.add('open');
    document.body.style.overflow = 'hidden';
    resetTreeTransform();
    treeContainer.innerHTML = '<div class="tree-loading"><div class="qs-spinner"></div><p>Construyendo red genealógica interactiva...</p></div>';
    if (treeTitularBadge) treeTitularBadge.textContent = `DNI ${dni}`;
    if (treeStatsBar) treeStatsBar.innerHTML = '';
    fetchArbol(dni);
  }

  function closeTreeModal() {
    if (!treeModal) return;
    treeModal.classList.remove('open');
    document.body.style.overflow = '';
  }

  document.querySelectorAll('[data-close-tree]').forEach(el => el.addEventListener('click', closeTreeModal));
  if ($('btn-close-tree')) $('btn-close-tree').addEventListener('click', closeTreeModal);

  async function fetchArbol(dni) {
    try {
      const res = await apiFetch(`${API_BASE}/persona/${encodeURIComponent(dni)}/arbol?limite=200`, { headers: apiHeaders() });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        treeContainer.innerHTML = `<div class="tree-empty">
          <span class="material-symbols-outlined tree-empty__icon">error</span>
          <p class="tree-empty__title">${escHtml(body?.detail || 'Error al cargar el árbol')}</p>
        </div>`;
        return;
      }
      const data = await res.json();
      renderArbol(data);
      refreshUserInfo();
    } catch {
      treeContainer.innerHTML = `<div class="tree-empty">
        <span class="material-symbols-outlined tree-empty__icon">cloud_off</span>
        <p class="tree-empty__title">Error de conexión</p>
        <p class="tree-empty__desc">No se pudo conectar al servidor para construir el árbol genealógico</p>
      </div>`;
    }
  }

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
    const ubigeo = nodo.ubigeo_dir && !opts.small ? `<div class="tree-node__ubigeo"><span class="material-symbols-outlined" style="font-size:10px">location_on</span>${escHtml(nodo.ubigeo_dir)}</div>` : '';

    const confianza = Number(nodo.confianza);
    const tieneConfianza = nodo.encontrado && !opts.isMain && Number.isFinite(confianza);
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
           <span class="material-symbols-outlined" style="font-size:11px">alt_route</span>
           ${alternativas.length} alternativa${alternativas.length !== 1 ? 's' : ''}
         </div>`
      : '';

    // Action buttons inside node
    const actionsHtml = nodo.dni && nodo.encontrado ? `
      <div class="tree-node__actions">
        <button class="btn-node-mini" data-tree-action="explore" data-dni="${escHtml(nodo.dni)}" title="Explorar árbol de ${escHtml(n)}">
          <span class="material-symbols-outlined" style="font-size:11px">account_tree</span>
          <span>Árbol</span>
        </button>
        <button class="btn-node-mini" data-tree-action="detail" data-dni="${escHtml(nodo.dni)}" title="Ver Ficha Completa">
          <span class="material-symbols-outlined" style="font-size:11px">visibility</span>
          <span>Ficha</span>
        </button>
        <button class="btn-node-mini" data-tree-action="c4" data-dni="${escHtml(nodo.dni)}" title="Generar ficha de referencia (no oficial)">
          <span class="material-symbols-outlined" style="font-size:11px">print</span>
          <span>C4</span>
        </button>
      </div>` : '';

    return `
      <div class="tree-node ${gClass} ${mainClass} ${relClass} ${ghostClass} ${smClass} ${probableClass}" data-dni="${escHtml(nodo.dni || '')}" title="${escHtml(n)}">
        ${relation}
        <div class="tree-node__avatar">
          <span class="material-symbols-outlined" style="font-size:20px">${icon}</span>
        </div>
        <div class="tree-node__name">${escHtml(n)}</div>
        <div class="tree-node__meta">${meta}${age}</div>
        ${confidenceHtml}
        ${alternativasHtml}
        ${ubigeo}
        ${actionsHtml}
      </div>
    `;
  }

  function renderArbol(data) {
    const p = data.persona;
    if (!p) {
      treeContainer.innerHTML = `<div class="tree-empty">
        <span class="material-symbols-outlined tree-empty__icon">person_off</span>
        <p class="tree-empty__title">Sin datos genealógicos</p>
        <p class="tree-empty__desc">No se encontró información familiar para esta persona</p>
      </div>`;
      return;
    }

    // 1. Titular badge
    const titularNombre = [p.nombres, p.ap_pat, p.ap_mat].filter(Boolean).join(' ').trim();
    if (treeTitularBadge) {
      treeTitularBadge.textContent = `${titularNombre} · DNI ${p.dni || '-'}`;
    }

    // 2. Stats bar chips calculation
    if (treeStatsBar) {
      const gpCount = [data.abuelo_paterno, data.abuela_paterna, data.abuelo_materno, data.abuela_materna].filter(x => x && x.encontrado).length;
      const parentsCount = [data.padre, data.madre].filter(x => x && x.encontrado).length;
      const todosHermanos = data.hermanos || [];
      const sibCount = todosHermanos.filter(h => h.tipo_relacion !== 'hermano_probable').length;
      const probCount = todosHermanos.length - sibCount;
      const todosHijos = data.hijos || [];
      const childrenCount = todosHijos.filter(h => !String(h.tipo_relacion || '').endsWith('_probable')).length;
      const childProbCount = todosHijos.length - childrenCount;

      let statsHtml = `
        <span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#a855f7">person</span><strong>1</strong> Titular</span>
        <span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#6366f1">family_restroom</span><strong>${parentsCount}</strong> Padres</span>
        <span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#eab308">elderly</span><strong>${gpCount}</strong> Abuelos</span>
      `;
      if (sibCount > 0) {
        statsHtml += `<span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#10b981">group</span><strong>${sibCount}</strong> Hermanos</span>`;
      }
      if (probCount > 0) {
        statsHtml += `<span class="tree-stat-chip tree-stat-chip--probable"><span class="material-symbols-outlined" style="font-size:13px; color:#fbbf24">help</span><strong>${probCount}</strong> Probables</span>`;
      }
      if (childrenCount > 0) {
        statsHtml += `<span class="tree-stat-chip"><span class="material-symbols-outlined" style="font-size:13px; color:#0284c7">child_care</span><strong>${childrenCount}</strong> Hijos</span>`;
      }
      if (childProbCount > 0) {
        statsHtml += `<span class="tree-stat-chip tree-stat-chip--probable"><span class="material-symbols-outlined" style="font-size:13px; color:#fbbf24">help</span><strong>${childProbCount}</strong> Hijos prob.</span>`;
      }
      treeStatsBar.innerHTML = statsHtml;

      const advertencias = (data.meta && data.meta.advertencias) || [];
      if (advertencias.length) {
        const warn = document.createElement('div');
        warn.className = 'tree-warnings';
        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined';
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
        html += '</div>';
        html += '<div class="tree-gp-connector"></div>';
        html += '</div>';
      }
      if (hasGPMat) {
        html += '<div class="tree-gp-couple">';
        html += '<p class="tree-gp-label">Línea Materna</p>';
        html += '<div class="tree-gp-pair">';
        if (data.abuelo_materno) html += treeNodeHtml(data.abuelo_materno, { small: true, relation: 'Abuelo Mat.' });
        if (data.abuela_materna) html += treeNodeHtml(data.abuela_materna, { small: true, relation: 'Abuela Mat.' });
        html += '</div>';
        html += '<div class="tree-gp-connector"></div>';
        html += '</div>';
      }
      html += '</div></div>';
      html += '<div class="tree-connector"></div>';
    }

    // ── Level 1: Parents ──
    if (data.padre || data.madre) {
      html += '<p class="tree-gen-label">Padres</p>';
      html += '<div class="tree-level"><div class="tree-couple">';
      if (data.padre) html += treeNodeHtml(data.padre, { relation: 'Padre' });
      if (data.madre) html += treeNodeHtml(data.madre, { relation: 'Madre' });
      html += '</div></div>';
      html += '<div class="tree-connector"></div>';
    }

    // ── Level 2: Person + Siblings ──
    const todosHermanos = data.hermanos || [];
    const hermanos = todosHermanos.filter(h => h.tipo_relacion !== 'hermano_probable');
    const probables = todosHermanos.filter(h => h.tipo_relacion === 'hermano_probable');
    html += '<p class="tree-gen-label">Persona' + (hermanos.length > 0 ? ' y Hermanos' : '') + '</p>';
    html += '<div class="tree-level"><div class="tree-siblings-row">';
    hermanos.forEach((h, i) => {
      if (i === Math.floor(hermanos.length / 2)) {
        html += treeNodeHtml(p, { isMain: true, relation: 'Titular' });
      }
      html += treeNodeHtml(h, { relation: tipoRelacionLabel(h.tipo_relacion) || 'Hermano/a' });
    });
    if (hermanos.length === 0) {
      html += treeNodeHtml(p, { isMain: true, relation: 'Titular' });
    }
    html += '</div>';
    if (probables.length > 0) {
      html += `<details class="tree-probables">
        <summary><span class="material-symbols-outlined" style="font-size:14px">help</span> ${probables.length} hermano(s) probable(s) — baja confianza</summary>
        <div class="tree-siblings-row tree-siblings-row--probables">`;
      probables.forEach(h => {
        html += treeNodeHtml(h, { relation: 'Hermano probable', probable: true });
      });
      html += '</div></details>';
    }
    html += '</div>';

    // ── Level 3: Children ──
    const todosHijos = data.hijos || [];
    const hijos = todosHijos.filter(h => !String(h.tipo_relacion || '').endsWith('_probable'));
    const hijosProbables = todosHijos.filter(h => String(h.tipo_relacion || '').endsWith('_probable'));
    if (todosHijos.length > 0) {
      html += '<div class="tree-connector"></div>';
      html += '<p class="tree-gen-label">Hijos</p>';
      if (hijos.length > 0) {
        html += '<div class="tree-level"><div class="tree-branch">';
        hijos.forEach(h => {
          html += '<div class="tree-branch-child">';
          html += treeNodeHtml(h, { relation: tipoRelacionLabel(h.tipo_relacion) || 'Hijo/a' });
          html += '</div>';
        });
        html += '</div></div>';
      }
      if (hijosProbables.length > 0) {
        html += `<details class="tree-probables">
          <summary><span class="material-symbols-outlined" style="font-size:14px">help</span> ${hijosProbables.length} hijo(s) probable(s) — baja confianza</summary>
          <div class="tree-level"><div class="tree-siblings-row tree-siblings-row--probables">`;
        hijosProbables.forEach(h => {
          html += treeNodeHtml(h, { relation: tipoRelacionLabel(h.tipo_relacion) || 'Hijo/a probable', probable: true });
        });
        html += '</div></div></details>';
      }
    }

    html += '</div>';
    treeContainer.innerHTML = html;

    // Bind interactive actions on nodes
    treeContainer.querySelectorAll('.btn-node-mini').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const action = btn.getAttribute('data-tree-action');
        const nodeDni = btn.getAttribute('data-dni');
        if (!nodeDni) return;

        if (action === 'explore') {
          // Dynamic Expansion: Shift tree around this person without closing modal
          openTreeModal(nodeDni);
        } else if (action === 'detail') {
          // Navigate to full detail
          closeTreeModal();
          setMode('dni');
          searchInput.value = nodeDni;
          btnClearSearch.classList.add('visible');
          search();
        } else if (action === 'c4') {
          // Open C4 for this person
          closeTreeModal();
          openC4Modal(nodeDni);
        }
      });
    });

    // Clicking the card body directly explores or navigates
    treeContainer.querySelectorAll('.tree-node:not(.tree-node--ghost)').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-node-mini')) return;
        const nodeDni = card.getAttribute('data-dni');
        if (nodeDni && nodeDni !== p.dni) {
          openTreeModal(nodeDni);
        }
      });
    });
  }


  /* ═══════════════════════════════════════════════════════════════════
     FICHA DE REFERENCIA C4 — DATOS DEL PADRÓN (NO OFICIAL)
     ═══════════════════════════════════════════════════════════════════ */
  async function openC4Modal(dni) {
    if (!c4Modal) return;

    c4Modal.classList.add('open');
    document.body.style.overflow = 'hidden';
    c4Container.innerHTML = '<div class="c4-loading"><div class="qs-spinner"></div><p>Generando ficha de referencia (no oficial)...</p></div>';

    try {
      const res = await apiFetch(`${API_BASE}/persona/${encodeURIComponent(dni)}/c4`, { headers: apiHeaders() });
      if (res.ok) {
        const data = await res.json();
        renderC4Certificate(data);
        refreshUserInfo();
        return;
      }

      const body = await res.json().catch(() => null);
      c4Container.innerHTML = `<div class="c4-loading">
        <span class="material-symbols-outlined" style="font-size:36px;color:var(--text-5)">info</span>
        <p>${escHtml((body && body.detail) || 'No se pudo generar la ficha de referencia')}</p>
      </div>`;
    } catch {
      c4Container.innerHTML = `<div class="c4-loading">
        <span class="material-symbols-outlined" style="font-size:36px;color:var(--text-5)">cloud_off</span>
        <p>Error de conexión al generar la ficha</p>
      </div>`;
    }
  }

  function closeC4Modal() {
    if (!c4Modal) return;
    c4Modal.classList.remove('open');
    document.body.style.overflow = '';
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


  function showDetail(p, index) {
    personaSeleccionada = p;
    resultsList.querySelectorAll('.result-item').forEach((el, i) => {
      el.classList.toggle('result-item--active', i === index);
    });

    const html = buildDetailHTML(p);

    // Smooth transition on detail panel
    detailContent.style.opacity = '0';
    detailContent.style.transform = 'translateX(12px)';
    setTimeout(() => {
      detailContent.innerHTML = html;
      detailEmpty.classList.add('hidden');
      detailContent.classList.remove('hidden');
      detailContent.style.transition = 'opacity 0.35s cubic-bezier(0.22,1,0.36,1), transform 0.35s cubic-bezier(0.22,1,0.36,1)';
      detailContent.style.opacity = '1';
      detailContent.style.transform = 'translateX(0)';
      bindDetailEvents(detailContent, p);
    }, 80);
  }

  /* ── Mobile sheet ────────────────────────────────────────── */
  function openMobileSheet(html, p) {
    mobileSheetContent.innerHTML = html;
    mobileSheet.classList.add('open');
    mobileSheetOverlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    bindDetailEvents(mobileSheetContent, p);
  }

  function closeMobileSheet() {
    mobileSheet.classList.remove('open');
    mobileSheetOverlay.classList.remove('open');
    document.body.style.overflow = '';
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

  /* ── Search ──────────────────────────────────────────────── */
  async function search() {
    const q = searchInput.value.trim();

    if (searchMode === 'dni') {
      if (!q) { toast('Ingresa un DNI de 8 dígitos', 'warn'); searchInput.focus(); return; }
      if (!/^\d{8}$/.test(q)) { toast('El DNI debe tener exactamente 8 dígitos', 'warn'); searchInput.focus(); return; }
    } else {
      if (q.length < 3) { toast('Ingresa al menos 3 caracteres', 'warn'); return; }
    }

    // Actualizar URL sin recargar la página
    try {
      const url = new URL(window.location);
      url.searchParams.set('q', q);
      url.searchParams.set('mode', searchMode);
      window.history.replaceState({}, '', url);
    } catch {}

    if (abortCtrl) abortCtrl.abort();
    abortCtrl = new AbortController();
    const isNombre = searchMode === 'nombre';
    const searchStartTime = performance.now();
    if (!isNombre) { setLoading(true); skeleton(); }
    emptyState.classList.add('hidden');
    resultsSection.classList.add('visible');
    setEstado(isNombre ? 'Buscando coincidencias ponderadas...' : 'Consultando padrón nacional...');

    try {
      let data;
      if (searchMode === 'dni') {
        const res = await apiFetch(`${API_BASE}/persona/${encodeURIComponent(q)}`, {
          signal: abortCtrl.signal, headers: apiHeaders(),
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
          signal: abortCtrl.signal, headers: apiHeaders(),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw { handled: true, msg: handleApiError(res, body) };
        }
        data = await res.json();
      }

      resultados = data;
      renderResults(data);
      setEstado(`${data.length} persona${data.length !== 1 ? 's' : ''} encontrada${data.length !== 1 ? 's' : ''}`, 'ok');

      // Animated badge count
      const oldCount = parseInt(badgeCount.textContent) || 0;
      animateValue(badgeCount, oldCount, data.length, 400);
      bumpBadge(badgeCount);

      btnExportar.classList.remove('hidden');
      btnExportarJson.classList.remove('hidden');
      if (data.length > 0) {
        addRecentSearch(q, searchMode);
        showDetail(data[0], 0);
        decrementConsultas();
      }
    } catch (e) {
      if (e.name === 'AbortError') return;
      if (!e.handled) {
        resultsList.innerHTML = '';
        setEstado('Error al consultar el servidor', 'error');
        toast('Error de conexión con la API', 'error');
      }
    } finally {
      if (!isNombre) setLoading(false);
      abortCtrl = null;
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
        debounce = setTimeout(() => search(), 350);
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
    if (!resultados.length) return;
    const h = ['DNI', 'Dígito RUC', 'Nombres', 'Ape. Paterno', 'Ape. Materno', 'Sexo', 'Estado Civil', 'Fecha Nacimiento', 'Edad', 'Padre', 'Madre', 'Dirección', 'Ubigeo Dom', 'Ubigeo Nac', 'Fch Emisión', 'Fch Inscripción', 'Fch Caducidad'];
    const r = resultados.map((p) => [
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
    if (!resultados.length) return;
    const blob = new Blob([JSON.stringify(resultados, null, 2)], { type: 'application/json' });
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: `padron_personas_${new Date().toISOString().slice(0, 10)}.json`,
    });
    a.click(); a.remove();
    toast('Datos completos exportados a JSON', 'success');
  });

  /* ── Quick Search Modal (Ctrl+K) ─────────────────────────── */
  function openQS() {
    qsModal.classList.add('open');
    qsInput.value = '';
    qsResults.innerHTML = '<p class="qs-empty">Escribe para buscar al instante...</p>';
    setTimeout(() => qsInput.focus(), 100);
  }

  function closeQS() {
    qsModal.classList.remove('open');
    if (qsAbort) qsAbort.abort();
  }

  async function qsSearch(query) {
    if (qsAbort) qsAbort.abort();
    if (!query || query.length < 3) {
      qsResults.innerHTML = '<p class="qs-empty">Mínimo 3 caracteres...</p>';
      return;
    }

    qsAbort = new AbortController();
    qsResults.innerHTML = '<div style="padding:32px"><div class="qs-spinner"></div></div>';
    const isDni = /^\d{8}$/.test(query.trim());

    try {
      let data;
      if (isDni) {
        const res = await apiFetch(`${API_BASE}/persona/${encodeURIComponent(query.trim())}`, {
          signal: qsAbort.signal, headers: apiHeaders(),
        });
        if (res.status === 404) data = [];
        else if (!res.ok) throw new Error();
        else data = [await res.json()];
      } else {
        const res = await apiFetch(`${API_BASE}/buscar?q=${encodeURIComponent(query)}&limit=6`, {
          signal: qsAbort.signal, headers: apiHeaders(),
        });
        if (!res.ok) throw new Error();
        data = await res.json();
      }

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
          resultados = data;
          searchInput.value = query;
          btnClearSearch.classList.add('visible');
          emptyState.classList.add('hidden');
          resultsSection.classList.add('visible');
          renderResults(data);
          setEstado(`${data.length} resultado${data.length !== 1 ? 's' : ''}`, 'ok');
          badgeCount.textContent = data.length;
          btnExportar.classList.remove('hidden');
          btnExportarJson.classList.remove('hidden');
          showDetail(data[0], 0);
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
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); openQS(); return; }
    if (e.key === 'Escape') {
      if (c4Modal && c4Modal.classList.contains('open')) { closeC4Modal(); return; }
      if (treeModal.classList.contains('open')) { closeTreeModal(); return; }
      if (qsModal.classList.contains('open')) { closeQS(); return; }
      if (mobileSheet.classList.contains('open')) { closeMobileSheet(); return; }
    }

    // Navegación con flechas en la lista de resultados
    if (resultados.length > 0 && !qsModal.classList.contains('open')) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
        if (activeTag !== 'input' || document.activeElement === searchInput) {
          e.preventDefault();
          if (document.activeElement === searchInput) searchInput.blur();

          let curIdx = resultados.findIndex((p) => personaSeleccionada && p.dni === personaSeleccionada.dni);
          if (e.key === 'ArrowDown') {
            curIdx = curIdx < 0 ? 0 : (curIdx + 1) % resultados.length;
          } else {
            curIdx = curIdx <= 0 ? resultados.length - 1 : curIdx - 1;
          }

          showDetail(resultados[curIdx], curIdx);
          const items = resultsList.querySelectorAll('.result-item');
          if (items[curIdx]) {
            items[curIdx].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
          }
        }
      }
    }
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth >= 769) {
      closeMobileSheet();
      document.body.style.overflow = '';
    }
  });

  /* ── Service Worker (PWA) ────────────────────────────────── */
  if ('serviceWorker' in navigator && window.location.protocol === 'https:') {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
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

  function showLoginScreen() {
    clearAuth();
    if (adminOverlay) adminOverlay.classList.remove('show');
    if (btnOpenAdmin) btnOpenAdmin.classList.add('hidden');
    if (loginOverlay) loginOverlay.classList.remove('hidden');
    if (loginUser) loginUser.focus();
  }

  function hideLoginScreen() {
    loginOverlay.classList.add('hidden');
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
        if (eyeIcon) eyeIcon.textContent = 'visibility';
        checkConnection();
        searchInput.focus();
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
    clearAuth();
    showLoginScreen();
  });

  // Admin Panel
  btnOpenAdmin.addEventListener('click', () => {
    adminOverlay.classList.add('show');
    loadAdminUsers();
  });
  btnCloseAdmin.addEventListener('click', () => adminOverlay.classList.remove('show'));
  adminBackdrop.addEventListener('click', () => adminOverlay.classList.remove('show'));

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
                <button class="btn-admin-action" data-admin-action="add" data-id="${escHtml(id)}" data-max="${escHtml(max)}" title="Agregar 100 consultas">
                  <span class="material-symbols-outlined">add_circle</span>
                </button>
                <button class="btn-admin-action" data-admin-action="toggle" data-id="${escHtml(id)}" data-active="${u.activo ? '1' : '0'}" title="${u.activo ? 'Desactivar' : 'Activar'}">
                  <span class="material-symbols-outlined">${u.activo ? 'block' : 'check_circle'}</span>
                </button>
                <button class="btn-admin-action btn-admin-action--danger" data-admin-action="delete" data-id="${escHtml(id)}" data-username="${escHtml(u.username)}" title="Eliminar">
                  <span class="material-symbols-outlined">delete</span>
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

    if (initialMode === 'nombre' || initialMode === 'dni') {
      setMode(initialMode);
    } else {
      setMode('dni');
    }

    checkConnection();
    setInterval(checkConnection, 30000);

    // La cookie HttpOnly es la única fuente de verdad de la sesión.
    const autenticado = await refreshUserInfo();
    if (!autenticado) {
      showLoginScreen();
      return;
    }

    hideLoginScreen();

    if (initialQ) {
      searchInput.value = initialQ;
      btnClearSearch.classList.add('visible');
      search();
    } else {
      searchInput.focus();
    }
  }

  bootstrap();
})();
