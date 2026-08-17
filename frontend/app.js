(function () {
  'use strict';

  /* ── Config ──────────────────────────────────────────────── */
  const API_BASE =
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'http://127.0.0.1:8000'
      : window.location.origin;

  let _sessionToken = null;

  async function fetchSessionToken() {
    try {
      const res = await fetch(`${API_BASE}/api/frontend-token`);
      if (res.ok) {
        const data = await res.json();
        if (data.token) {
          _sessionToken = data.token;
          if (data.expires_in > 60) {
            setTimeout(fetchSessionToken, (data.expires_in - 60) * 1000);
          }
        }
      }
    } catch {
      setTimeout(fetchSessionToken, 5000);
    }
  }

  function apiHeaders(extra) {
    const h = extra || {};
    if (_sessionToken) h['Authorization'] = `Bearer ${_sessionToken}`;
    return h;
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

  let resultados = [];
  let personaSeleccionada = null;
  let searchMode = 'dni';
  let abortCtrl = null;
  let debounce = null;
  let qsTimer = null;
  let qsAbort = null;

  /* ── Helpers ─────────────────────────────────────────────── */
  function nombre(p) {
    return [p.nombres, p.ap_pat, p.ap_mat].filter(Boolean).join(' ').trim();
  }
  function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
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

  /* ── Toast ───────────────────────────────────────────────── */
  const TOAST_ICONS = { info: 'info', success: 'check_circle', error: 'error', warn: 'warning' };

  function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast toast--${type}`;
    el.innerHTML = `<span class="material-symbols-outlined">${TOAST_ICONS[type]}</span><span>${msg}</span>`;
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
      const res = await fetch(`${API_BASE}/api/status`, { signal: c.signal });
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

  /* ── Mode switching ──────────────────────────────────────── */
  function setMode(mode) {
    searchMode = mode;
    searchInput.placeholder = mode === 'dni' ? 'Escribe un DNI (8 dígitos)...' : 'Escribe apellidos o nombres completos...';
    searchInput.inputMode = mode === 'dni' ? 'numeric' : 'text';
    modeDni.classList.toggle('mode-btn--active', mode === 'dni');
    modeNombre.classList.toggle('mode-btn--active', mode === 'nombre');
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

      html += `<div class="result-item slide-up stagger-${Math.min(i + 1, 8)}${active}" data-index="${i}">
        <div class="result-item__inner">
          <div class="result-item__avatar">
            <span class="material-symbols-outlined">${g === 'F' ? 'woman' : 'person'}</span>
          </div>
          <div class="result-item__body">
            <p class="result-item__name">${nHtml}</p>
            <div class="result-item__meta">
              <span class="result-item__dni">DNI ${escHtml(p.dni || '-')}</span>
              <span class="status-dot ${dot}"></span>
              <span>${escHtml(p.sexo || '-')}</span>
              ${p.edad_anios != null ? `<span>&middot; ${p.edad_anios} años</span>` : ''}
              ${p.est_civil ? `<span>&middot; ${escHtml(p.est_civil)}</span>` : ''}
            </div>
          </div>
          <span class="material-symbols-outlined" style="font-size:18px;color:var(--text-6)">chevron_right</span>
        </div>
        ${p.direccion ? `<p class="result-item__address"><span class="material-symbols-outlined">location_on</span>${escHtml(p.direccion)}</p>` : ''}
      </div>`;
    });

    resultsList.innerHTML = html;
    resultsList.querySelectorAll('.result-item').forEach((el, i) => {
      el.addEventListener('click', () => showDetail(data[i], i));
    });
  }

  /* ── RUC consultation ────────────────────────────────────── */
  async function consultarRUC(btn, resultadoEl, dni) {
    btn.disabled = true;
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin" style="animation:spin 1s infinite linear">progress_activity</span> Consultando SUNAT...';
    resultadoEl.classList.add('hidden');

    try {
      const res = await fetch(`${API_BASE}/scraping/ruc/${encodeURIComponent(dni)}`, { headers: apiHeaders() });
      const data = await res.json();

      if (res.status === 429) {
        const retry = res.headers.get('Retry-After');
        const msg = retry ? `Límite alcanzado. Intenta en ${retry} seg.` : 'Límite de consultas alcanzado. Intenta más tarde.';
        resultadoEl.innerHTML = `<div class="ruc-alert ruc-alert--warn"><span class="material-symbols-outlined">hourglass_empty</span><span>${msg}</span></div>`;
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
        <!-- Digital DNI Card Visual -->
        <div class="dni-card-visual">
          <div class="dni-card__chip"></div>
          <div class="dni-card__header">
            <div class="dni-card__avatar">
              <span class="material-symbols-outlined" style="font-size:34px; color: ${g === 'F' ? 'var(--pink)' : 'var(--blue)'}">${g === 'F' ? 'woman' : 'person'}</span>
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
          <button class="btn-action" id="btn-copy-dni" title="Copiar DNI">
            <span class="material-symbols-outlined">content_copy</span>
            <span>Copiar DNI</span>
          </button>
          <button class="btn-action" id="btn-print-sheet" title="Imprimir ficha">
            <span class="material-symbols-outlined">print</span>
            <span>Imprimir</span>
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

          <!-- 5. Documento y Fechas RENIEC -->
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
          `--- FICHA RENIEC ---`,
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

    const printBtn = container.querySelector('#btn-print-sheet');
    if (printBtn) {
      printBtn.addEventListener('click', () => {
        window.print();
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
  }

  function showDetail(p, index) {
    personaSeleccionada = p;
    resultsList.querySelectorAll('.result-item').forEach((el, i) => {
      el.classList.toggle('result-item--active', i === index);
    });

    const html = buildDetailHTML(p);
    detailContent.innerHTML = html;
    detailEmpty.classList.add('hidden');
    detailContent.classList.remove('hidden');
    bindDetailEvents(detailContent, p);

    if (window.innerWidth < 769) {
      openMobileSheet(html, p);
    }
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

  /* ── Error handling ──────────────────────────────────────── */
  function handleApiError(res, data) {
    if (res.status === 401) {
      toast('Sesión expirada. Renovando credenciales...', 'error');
      setTimeout(() => fetchSessionToken(), 1000);
      return 'Sesión expirada';
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
    if (!isNombre) { setLoading(true); skeleton(); }
    emptyState.classList.add('hidden');
    resultsSection.classList.add('visible');
    setEstado(isNombre ? 'Buscando coincidencias ponderadas...' : 'Consultando padrón nacional...');

    try {
      let data;
      if (searchMode === 'dni') {
        const res = await fetch(`${API_BASE}/persona/${encodeURIComponent(q)}`, {
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
        const res = await fetch(`${API_BASE}/buscar?q=${encodeURIComponent(q)}&limit=${limiteSelect.value}`, {
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
      badgeCount.textContent = data.length;
      btnExportar.classList.remove('hidden');
      btnExportarJson.classList.remove('hidden');
      if (data.length > 0) showDetail(data[0], 0);
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
      searchInput.value = val.replace(/\D/g, '').slice(0, 8);
    } else {
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
    searchInput.focus();
  });

  // Suggestion chips
  document.querySelectorAll('.chip[data-query]').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.getAttribute('data-query');
      setMode('nombre');
      searchInput.value = q;
      btnClearSearch.classList.add('visible');
      search();
    });
  });

  document.querySelectorAll('.chip[data-example="dni"]').forEach(chip => {
    chip.addEventListener('click', () => {
      setMode('dni');
      searchInput.focus();
    });
  });

  /* ── CSV & JSON Export ────────────────────────────────────── */
  btnExportar.addEventListener('click', () => {
    if (!resultados.length) return;
    const h = ['DNI', 'Dígito RUC', 'Nombres', 'Ape. Paterno', 'Ape. Materno', 'Sexo', 'Estado Civil', 'Fecha Nacimiento', 'Edad', 'Padre', 'Madre', 'Dirección', 'Ubigeo Dom', 'Ubigeo Nac', 'Fch Emisión', 'Fch Inscripción', 'Fch Caducidad'];
    const r = resultados.map((p) => [
      p.dni || '', p.dig_ruc || '', p.nombres || '', p.ap_pat || '', p.ap_mat || '',
      p.sexo || '', p.est_civil || '', p.fecha_nac || '', p.edad_texto || p.edad_anios || '',
      p.padre || '', p.madre || '', p.direccion || '', p.ubigeo_dir || '', p.ubigeo_nac || '',
      p.fch_emision || '', p.fch_inscripcion || '', p.fch_caducidad || '',
    ]);
    const csv = [h.join(','), ...r.map((row) =>
      row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')
    )].join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: `padron_reniec_completo_${new Date().toISOString().slice(0, 10)}.csv`,
    });
    a.click(); a.remove();
    toast('Reporte CSV con todos los campos descargado', 'success');
  });

  btnExportarJson.addEventListener('click', () => {
    if (!resultados.length) return;
    const blob = new Blob([JSON.stringify(resultados, null, 2)], { type: 'application/json' });
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: `padron_reniec_completo_${new Date().toISOString().slice(0, 10)}.json`,
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
        const res = await fetch(`${API_BASE}/persona/${encodeURIComponent(query.trim())}`, {
          signal: qsAbort.signal, headers: apiHeaders(),
        });
        if (res.status === 404) data = [];
        else if (!res.ok) throw new Error();
        else data = [await res.json()];
      } else {
        const res = await fetch(`${API_BASE}/buscar?q=${encodeURIComponent(query)}&limit=6`, {
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
  fetchSessionToken().then(() => {
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

    if (initialQ) {
      searchInput.value = initialQ;
      btnClearSearch.classList.add('visible');
      search();
    } else {
      searchInput.focus();
    }
  });
})();
