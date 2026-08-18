/**
 * RECORDER CORE v2 - Inyectado en MAIN world via manifest (document_start)
 *
 * Cambios v2 (fix: se perdían acciones tras navegar):
 *  - Se inyecta DECLARATIVAMENTE en cada página (manifest content_scripts
 *    con world MAIN) — ya no depende de que el background llegue a tiempo.
 *  - Listeners SIEMPRE activos desde document_start (capturan según estado).
 *  - BUFFER de acciones tempranas: si el usuario hace click antes de que
 *    llegue el estado restaurado, la acción se guarda en buffer y se
 *    incorpora al restaurar (antes se perdía).
 *  - Restauración con guard: nunca pisa más acciones con menos.
 *  - Guardado también en pagehide (beforeunload solo es best-effort).
 *
 * Expone en consola:
 *   recorder.start("nombre_flujo")
 *   recorder.stop()
 *   recorder.status()
 *   recorder.export()
 */

(function () {
  'use strict';

  // Evitar doble inicialización (manifest + fallback del background)
  if (window.__recorderCoreLoaded) return;
  window.__recorderCoreLoaded = true;

  // ─────────────────────────────────────────────
  // OBJETO PRINCIPAL
  // ─────────────────────────────────────────────

  window.recorder = {
    grabando: false,
    acciones: [],
    elementos: {},
    inicio: null,
    flujoNombre: null,
    paginasVisitadas: [],
    _listenersActivos: false,

    // Buffer de acciones capturadas ANTES de que llegue el estado restaurado.
    // Si la grabación estaba activa, se incorporan; si no, se descartan.
    _restorePending: true,
    _buffer: [],

    // ── CONTROL ──────────────────────────────

    start: function (nombre) {
      this.grabando = true;
      this.flujoNombre = nombre || 'flujo_' + Date.now();
      this.acciones = [];
      this.elementos = {};
      this.paginasVisitadas = [];
      this.inicio = Date.now();
      this._restorePending = false;
      this._buffer = [];

      this._registrarPagina('start');
      this._setupListeners();
      this._guardarEstado();

      console.clear();
      console.log('%c╔══════════════════════════════════════════╗', 'color:#e74c3c');
      console.log('%c║  🔴  GRABACIÓN INICIADA                  ║', 'color:#e74c3c; font-weight:bold; font-size:14px');
      console.log('%c╚══════════════════════════════════════════╝', 'color:#e74c3c');
      console.log('%cFlujo: ' + this.flujoNombre, 'color:#3498db; font-weight:bold');
      console.log('%c✓ Extensión activa — survives navigation', 'color:#27ae60; font-weight:bold');
      console.log('%c  recorder.stop()   → detener y descargar JSON', 'color:#95a5a6');
      console.log('%c  recorder.status() → ver estado actual', 'color:#95a5a6');
    },

    stop: function () {
      if (!this.grabando && this.acciones.length === 0) {
        console.warn('⚠️ No hay grabación activa.');
        return null;
      }
      this.grabando = false;
      const duracion = ((Date.now() - this.inicio) / 1000).toFixed(1);

      const datos = {
        flujo: this.flujoNombre,
        acciones: this.acciones,
        elementos: this.elementos,
        paginas: this.paginasVisitadas,
        metadata: {
          total_acciones: this.acciones.length,
          total_elementos: Object.keys(this.elementos).length,
          total_paginas: this.paginasVisitadas.length,
          duracion_segundos: parseFloat(duracion),
          timestamp: new Date().toISOString(),
          user_agent: navigator.userAgent
        }
      };

      const filename = this.flujoNombre + '.json';

      // Un solo mecanismo de descarga — sin duplicados.
      // Primero intenta via extensión (chrome.downloads API).
      // Si la extensión no confirma en 1.5s, activa el fallback blob.
      let downloadedByExtension = false;

      window.addEventListener('message', function onDownloadAck(event) {
        if (event.data && event.data.type === '__HERMES2_RECORDER_DOWNLOAD_ACK') {
          downloadedByExtension = true;
          window.removeEventListener('message', onDownloadAck);
        }
      });

      window.postMessage({
        type: '__HERMES2_RECORDER',
        action: 'DOWNLOAD',
        data: datos,
        filename: filename
      }, '*');

      // Fallback solo si la extensión no confirmó descarga en 1.5s
      setTimeout(() => {
        if (downloadedByExtension) return;
        try {
          const json = JSON.stringify(datos, null, 2);
          const blob = new Blob([json], { type: 'application/json' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          console.log('%c[Recorder] Fallback download activado', 'color:#e67e22');
        } catch (e) { /* ignorar */ }
      }, 1500);

      // Limpiar estado guardado
      window.postMessage({ type: '__HERMES2_RECORDER', action: 'CLEAR_STATE' }, '*');

      console.log('%c╔══════════════════════════════════════════╗', 'color:#27ae60');
      console.log('%c║  ⏹️  GRABACIÓN DETENIDA                  ║', 'color:#27ae60; font-weight:bold; font-size:14px');
      console.log('%c╚══════════════════════════════════════════╝', 'color:#27ae60');
      console.log('%cAcciones:  ' + datos.metadata.total_acciones, 'color:#3498db');
      console.log('%cElementos: ' + datos.metadata.total_elementos, 'color:#3498db');
      console.log('%cPáginas:   ' + datos.metadata.total_paginas, 'color:#3498db');
      console.log('%cDuración:  ' + duracion + 's', 'color:#3498db');
      console.log('%c✓ Descargando: ' + filename, 'color:#27ae60; font-weight:bold');

      return datos;
    },

    status: function () {
      console.log('%c════ ESTADO DEL RECORDER ════', 'color:#9b59b6; font-weight:bold');
      console.log('Grabando:  ' + (this.grabando ? '🔴 SÍ' : '⏹️ NO'));
      console.log('Flujo:     ' + (this.flujoNombre || '—'));
      console.log('Acciones:  ' + this.acciones.length);
      console.log('Elementos: ' + Object.keys(this.elementos).length);
      console.log('Página:    ' + window.location.href);
      if (this.acciones.length > 0) {
        console.log('Última:    ' + this.acciones[this.acciones.length - 1].tipo +
          ' → ' + this.acciones[this.acciones.length - 1].nombre);
      }
      return {
        grabando: this.grabando,
        flujoNombre: this.flujoNombre,
        totalAcciones: this.acciones.length,
        totalElementos: Object.keys(this.elementos).length,
        pagina: window.location.href
      };
    },

    export: function () {
      const datos = {
        flujo: this.flujoNombre,
        acciones: this.acciones,
        elementos: this.elementos,
        paginas: this.paginasVisitadas
      };
      console.log(JSON.stringify(datos, null, 2));
      return datos;
    },

    // ── LISTENERS (siempre activos desde document_start) ──────────

    _setupListeners: function () {
      if (this._listenersActivos) return;
      this._listenersActivos = true;

      const self = this;

      // CLICK
      document.addEventListener('click', function (e) {
        if (!e.target) return;
        if (!self.grabando && !self._restorePending) return;
        try { self._capturarClick(e); } catch (err) {
          console.warn('⚠️ [Recorder] Error en click (ignorado):', err.message);
        }
      }, true);

      // INPUT (captura texto mientras escribe)
      document.addEventListener('input', function (e) {
        if (!self.grabando && !self._restorePending) return;
        const el = e.target;
        if (!['INPUT', 'TEXTAREA'].includes(el.tagName)) return;
        try { self._capturarInput(e); } catch (err) { /* ignorar */ }
      }, true);

      // CHANGE (selects, checkboxes, radios)
      document.addEventListener('change', function (e) {
        if (!self.grabando && !self._restorePending) return;
        const el = e.target;
        if (!['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) return;
        try { self._capturarChange(e); } catch (err) { /* ignorar */ }
      }, true);

      // SCROLL (rueda del mouse O barra lateral — ambos disparan 'scroll').
      // Debounce: se registra la posición final cuando el scroll se detiene.
      let scrollTimer = null;
      document.addEventListener('scroll', function (e) {
        if (!self.grabando && !self._restorePending) return;
        const tgt = e.target;
        clearTimeout(scrollTimer);
        scrollTimer = setTimeout(function () {
          try { self._capturarScroll(tgt); } catch (err) { /* ignorar */ }
        }, 400);
      }, true);

      // Guardar estado antes de navegar — pagehide es más confiable que
      // beforeunload (que puede no completar el postMessage)
      window.addEventListener('pagehide', function () {
        if (self.grabando) {
          self._registrarPagina('pagehide');
          self._guardarEstado();
        }
      });
      window.addEventListener('beforeunload', function () {
        if (self.grabando) {
          self._registrarPagina('beforeunload');
          self._guardarEstado();
        }
      });
    },

    _capturarScroll: function (tgt) {
      // ¿Scroll de la ventana o de un contenedor con scroll propio?
      const esDoc = (tgt === document || tgt === document.documentElement
        || tgt === document.body || tgt === window);
      let x, y, selector;
      if (esDoc) {
        x = window.scrollX; y = window.scrollY; selector = '';
      } else {
        x = tgt.scrollLeft; y = tgt.scrollTop;
        selector = this._generarSelector(tgt);
      }
      // Ignorar scroll insignificante o posición repetida
      if (y < 40 && x < 40) return;
      const last = this.acciones[this.acciones.length - 1];
      if (last && last.tipo === 'scroll' && last.scrollY === y && last.selector === selector) return;

      const accion = {
        tipo: 'scroll', nombre: 'scroll', selector: selector,
        scrollX: Math.round(x), scrollY: Math.round(y),
        tag: 'scroll', html: '', texto: '',
        url: window.location.href, timestamp: new Date().toISOString()
      };
      this._registrarAccion(accion, 'scroll');
      if (this.grabando) console.log('%c✓ SCROLL: y=' + Math.round(y)
        + (selector ? ' en ' + selector : ' (ventana)'), 'color:#9b59b6');
    },

    // ── REGISTRO DE ACCIONES (con buffer pre-restauración) ────────

    _registrarAccion: function (accion, nombre) {
      if (this.grabando) {
        this.acciones.push(accion);
        this._registrarElemento(nombre, accion);
        this._guardarEstado();
      } else if (this._restorePending) {
        // Aún no sabemos si había grabación activa — guardar en buffer
        this._buffer.push({ accion: accion, nombre: nombre });
      }
    },

    // ── CAPTURADORES ─────────────────────────

    _capturarClick: function (event) {
      const el = event.target;
      if (this._debeIgnorar(el)) return;

      const nombre = this._generarNombre(el);
      const accion = {
        tipo: 'click',
        nombre: nombre,
        selector: this._generarSelector(el),
        candidatos: this._auditarElemento(el),
        texto: (el.innerText || el.value || '').substring(0, 100).trim(),
        tag: el.tagName.toLowerCase(),
        html: el.outerHTML.substring(0, 500),
        url: window.location.href,
        timestamp: new Date().toISOString()
      };

      this._registrarAccion(accion, nombre);
      if (this.grabando) console.log('%c✓ CLICK: ' + nombre, 'color:#e67e22');
    },

    _capturarInput: function (event) {
      const el = event.target;
      if (this._debeIgnorar(el)) return;

      // Debounce: actualizar la última acción de input si es el mismo elemento
      const nombre = this._generarNombre(el);
      const valor = el.type === 'password' ? '[PASSWORD]' : el.value;
      const ultimaAccion = this.acciones[this.acciones.length - 1];

      if (this.grabando && ultimaAccion && ultimaAccion.tipo === 'input'
          && ultimaAccion.nombre === nombre) {
        ultimaAccion.valor = valor;
        ultimaAccion.timestamp = new Date().toISOString();
        this._guardarEstado();
        return;
      }

      const accion = {
        tipo: 'input',
        nombre: nombre,
        selector: this._generarSelector(el),
        candidatos: this._auditarElemento(el),
        valor: valor,
        tag: el.tagName.toLowerCase(),
        inputType: el.type || 'text',
        html: el.outerHTML.substring(0, 500),
        url: window.location.href,
        timestamp: new Date().toISOString()
      };

      this._registrarAccion(accion, nombre);
    },

    _capturarChange: function (event) {
      const el = event.target;
      const nombre = this._generarNombre(el);
      const valor = el.type === 'password' ? '[PASSWORD]' : el.value;

      const accion = {
        tipo: 'change',
        nombre: nombre,
        selector: this._generarSelector(el),
        candidatos: this._auditarElemento(el),
        valor: valor,
        tag: el.tagName.toLowerCase(),
        html: el.outerHTML.substring(0, 500),
        url: window.location.href,
        timestamp: new Date().toISOString()
      };

      this._registrarAccion(accion, nombre);
      if (this.grabando) {
        console.log('%c✓ CHANGE: ' + nombre + ' = "' + valor + '"', 'color:#1abc9c');
      }
    },

    // ── HELPERS ──────────────────────────────

    _generarNombre: function (el) {
      try {
        // testid primero — ids como 'id-button' o 'typography' se repiten en
        // decenas de elementos y causaban colisiones de nombre
        const testId = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy');
        if (testId) return testId;
        const GENERIC_IDS = ['id-button', 'typography', 'id-input', 'id-label'];
        if (el.id && GENERIC_IDS.indexOf(el.id) === -1 && !this._esIdDinamico(el.id)) return el.id;
        if (el.name) return el.name;
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return ariaLabel.replace(/\s+/g, '_').toLowerCase();

        // className seguro (SVG, Web Components, etc.)
        let classStr = '';
        if (el.className) {
          if (typeof el.className === 'string') classStr = el.className;
          else if (el.className.baseVal) classStr = el.className.baseVal; // SVG
          else classStr = String(el.className);
        }
        const clase = classStr.split(' ').filter(c => c && c.length > 2 && !c.startsWith('ng-'))[0];
        if (clase) return clase;

        const texto = (el.innerText || el.value || '').substring(0, 20).trim().replace(/\s+/g, '_');
        if (texto) return texto.toLowerCase();

        return el.tagName.toLowerCase() + '_' + Math.random().toString(36).substr(2, 6);
      } catch (e) {
        return el.tagName.toLowerCase() + '_err';
      }
    },

    // ¿El id parece generado dinámicamente por Angular? (dropdown_0, input_3,
    // tab_12...) Esos ids cambian entre renders — NO son localizadores estables.
    _esIdDinamico: function (id) {
      return /(?:^|_|-)\d+$/.test(id) || /^\d/.test(id);
    },

    // Audita el elemento y sus ancestros: junta TODOS los localizadores
    // candidatos para que el intérprete elija el más estable.
    _auditarElemento: function (el) {
      const attr = function (e, a) {
        try { return (e && e.getAttribute && e.getAttribute(a)) || ''; } catch (_) { return ''; }
      };
      const cand = {
        testid          : attr(el, 'data-testid') || attr(el, 'data-test') || attr(el, 'data-cy'),
        id              : (el.id || ''),
        idDinamico      : el.id ? this._esIdDinamico(el.id) : false,
        name            : attr(el, 'name'),
        formcontrolname : attr(el, 'formcontrolname'),
        ariaLabel       : attr(el, 'aria-label'),
        placeholder     : attr(el, 'placeholder'),
        role            : attr(el, 'role'),
        ancestorTestid  : '',
        ancestorTag     : '',
        ancestorFormcontrol: ''
      };
      try {
        const anc = el.closest('[data-testid]');
        if (anc && anc !== el) {
          cand.ancestorTestid = anc.getAttribute('data-testid');
          cand.ancestorTag    = anc.tagName.toLowerCase();
        }
        const ancFc = el.closest('[formcontrolname]');
        if (ancFc) cand.ancestorFormcontrol = ancFc.getAttribute('formcontrolname');
      } catch (_) { /* ignorar */ }
      return cand;
    },

    _generarSelector: function (el) {
      try {
        // 1. data-testid propio — el más estable e independiente del idioma
        const testId = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy');
        if (testId) return `[data-testid="${testId}"]`;

        // 2. id ESTABLE (no generado: dropdown_0, input_3, etc.)
        if (el.id && !this._esIdDinamico(el.id)) return '#' + CSS.escape(el.id);

        // 3. data-testid del ancestro más cercano (clicks en spans/divs internos)
        const anc = el.closest('[data-testid]');
        if (anc) return `[data-testid="${anc.getAttribute('data-testid')}"]`;

        // 4. formcontrolname propio o del ancestro (forms Angular)
        const fc = el.getAttribute('formcontrolname') ||
          (el.closest('[formcontrolname]') && el.closest('[formcontrolname]').getAttribute('formcontrolname'));
        if (fc) return `[formcontrolname="${fc}"]`;

        // 5. name / aria-label
        if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`;
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return `[aria-label="${ariaLabel}"]`;

        // 6. id dinámico — mejor que nada, pero el intérprete lo despriorizará
        if (el.id) return '#' + CSS.escape(el.id);

        return el.tagName.toLowerCase();
      } catch (e) {
        return el.tagName.toLowerCase();
      }
    },

    _registrarElemento: function (nombre, accion) {
      if (!this.elementos[nombre]) {
        this.elementos[nombre] = {
          selector: accion.selector,
          tag: accion.tag,
          html: accion.html,
          acciones: []
        };
      }
      this.elementos[nombre].acciones.push(accion.tipo);
    },

    _registrarPagina: function (evento) {
      this.paginasVisitadas.push({
        url: window.location.href,
        titulo: document.title,
        evento: evento,
        timestamp: new Date().toISOString()
      });
    },

    _debeIgnorar: function (el) {
      try {
        const ignorarTags = ['SCRIPT', 'STYLE', 'META', 'LINK', 'HEAD'];
        if (ignorarTags.includes(el.tagName)) return true;
        // No ignorar elementos ocultos — algunos botones de app tienen offsetParent null
        return false;
      } catch (e) {
        return true;
      }
    },

    // ── PERSISTENCIA ─────────────────────────

    _guardarEstado: function () {
      const estado = {
        grabando: this.grabando,
        acciones: this.acciones,
        elementos: this.elementos,
        paginasVisitadas: this.paginasVisitadas,
        flujoNombre: this.flujoNombre,
        inicio: this.inicio
      };

      // Notificar al content.js (isolated world) para que guarde en chrome.storage
      window.postMessage({
        type: '__HERMES2_RECORDER',
        action: 'SAVE_STATE',
        state: estado
      }, '*');
    }
  };

  // ─────────────────────────────────────────────
  // RESTAURACIÓN DE ESTADO
  // Llamada por: content.js (RESTORE postMessage) o background.js (fallback)
  // Guard: nunca pisa un estado en memoria con MÁS acciones que el guardado.
  // ─────────────────────────────────────────────

  window.__recorderRestoreState = function (savedState) {
    const r = window.recorder;

    // Sin estado guardado o grabación inactiva → descartar buffer y salir
    if (!savedState || !savedState.grabando) {
      r._restorePending = false;
      r._buffer = [];
      return;
    }

    // Guard anti-pisado: si la memoria ya tiene más acciones (restauración
    // duplicada o tardía), no sobrescribir
    const savedCount = (savedState.acciones || []).length;
    if (r.grabando && r.acciones.length >= savedCount) {
      r._restorePending = false;
      return;
    }

    r.acciones = savedState.acciones || [];
    r.elementos = savedState.elementos || {};
    r.paginasVisitadas = savedState.paginasVisitadas || [];
    r.flujoNombre = savedState.flujoNombre || null;
    r.inicio = savedState.inicio || null;
    r.grabando = true;

    // Incorporar acciones capturadas mientras llegaba el estado
    if (r._buffer.length > 0) {
      for (const item of r._buffer) {
        r.acciones.push(item.accion);
        r._registrarElemento(item.nombre, item.accion);
      }
      console.log('%c[Recorder] ' + r._buffer.length +
        ' acción(es) tempranas incorporadas desde buffer', 'color:#e67e22');
    }
    r._buffer = [];
    r._restorePending = false;

    r._registrarPagina('navigation');
    r._guardarEstado();

    console.log('%c╔══════════════════════════════════════════╗', 'color:#27ae60');
    console.log('%c║  ✅  GRABACIÓN RESTAURADA                ║', 'color:#27ae60; font-weight:bold; font-size:13px');
    console.log('%c╚══════════════════════════════════════════╝', 'color:#27ae60');
    console.log('%cFlujo:    ' + r.flujoNombre, 'color:#3498db');
    console.log('%cAcciones: ' + r.acciones.length + ' (acumuladas)', 'color:#3498db');
    console.log('%cPágina:   ' + window.location.href, 'color:#95a5a6');
  };

  // ─────────────────────────────────────────────
  // MENSAJES: comandos del popup y restauración desde content.js
  // ─────────────────────────────────────────────

  window.addEventListener('message', function (event) {
    if (event.source !== window) return;
    if (!event.data) return;

    // Estado restaurado enviado por content.js
    if (event.data.type === '__HERMES2_RECORDER_RESTORE') {
      window.__recorderRestoreState(event.data.state);
      // ACK para que content.js deje de reintentar
      window.postMessage({ type: '__HERMES2_RECORDER_RESTORE_ACK' }, '*');
      return;
    }

    if (event.data.type !== '__HERMES2_RECORDER_CMD') return;

    const { command, args } = event.data;

    switch (command) {
      case 'START':
        window.recorder.start(args && args[0] ? args[0] : undefined);
        break;
      case 'STOP':
        window.recorder.stop();
        break;
      case 'EXPORT':
        window.recorder.export();
        break;
      case 'GET_STATUS':
        window.postMessage({
          type: '__HERMES2_RECORDER_STATUS',
          status: {
            grabando: window.recorder.grabando,
            flujoNombre: window.recorder.flujoNombre,
            totalAcciones: window.recorder.acciones.length,
            totalElementos: Object.keys(window.recorder.elementos).length
          }
        }, '*');
        break;
    }
  });

  // ─────────────────────────────────────────────
  // ARRANQUE: listeners activos desde ya + timeout del buffer
  // ─────────────────────────────────────────────

  window.recorder._setupListeners();

  // Si en 3s nadie restauró estado, asumir que no había grabación activa
  setTimeout(function () {
    if (window.recorder._restorePending) {
      window.recorder._restorePending = false;
      window.recorder._buffer = [];
    }
  }, 3000);

  console.log('%c[HERMES2 Recorder v2] ✓ Listo — recorder.start("flujo")', 'color:#27ae60; font-size:11px');

})();
