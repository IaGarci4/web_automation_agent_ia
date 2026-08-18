/**
 * POPUP JS - HERMES2 Action Recorder
 * Controla la UI del popup de la extensión.
 */

(function () {
  'use strict';

  const $ = id => document.getElementById(id);

  const btnStart   = $('btnStart');
  const btnStop    = $('btnStop');
  const btnExport  = $('btnExport');
  const flujoInput = $('flujoInput');
  const inputRow   = $('inputRow');
  const statusDot  = $('statusDot');
  const statusText = $('statusText');
  const flujoText  = $('flujoText');
  const accionesCount  = $('accionesCount');
  const elementosCount = $('elementosCount');
  const msgEl      = $('msg');

  let grabando = false;

  // ─────────────────────────────────────────────
  // HELPERS
  // ─────────────────────────────────────────────

  function showMsg(text, type = '') {
    msgEl.textContent = text;
    msgEl.className = 'msg ' + type;
    if (type === 'ok') setTimeout(() => { msgEl.textContent = ''; }, 3000);
  }

  function updateUI(state) {
    if (!state) {
      statusDot.className = 'dot';
      statusText.textContent = 'Sin página activa';
      flujoText.textContent = '—';
      accionesCount.textContent = '0';
      elementosCount.textContent = '0';
      setGrabando(false);
      return;
    }

    grabando = state.grabando || false;
    setGrabando(grabando);

    statusText.textContent = grabando ? 'Grabando' : 'En espera';
    statusText.className = 'value ' + (grabando ? 'red' : 'green');
    flujoText.textContent = state.flujoNombre || '—';
    accionesCount.textContent = state.totalAcciones || 0;
    elementosCount.textContent = state.totalElementos || 0;
  }

  function setGrabando(isGrabando) {
    grabando = isGrabando;
    statusDot.className = 'dot ' + (isGrabando ? 'active' : '');
    btnStart.disabled  = isGrabando;
    btnStop.disabled   = !isGrabando;
    btnExport.disabled = !isGrabando;
    inputRow.style.display = isGrabando ? 'none' : 'block';
  }

  // ─────────────────────────────────────────────
  // OBTENER STATUS DEL TAB ACTIVO
  // ─────────────────────────────────────────────

  async function refreshStatus() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.id) { updateUI(null); return; }

      let response = await chrome.tabs.sendMessage(tab.id, { type: 'POPUP_GET_STATUS' })
        .catch(() => null);

      // Si no responde, intentar inyectar el content script y reintentar
      if (!response) {
        const ok = await injectContentScript(tab.id).catch(() => false);
        if (ok) {
          response = await chrome.tabs.sendMessage(tab.id, { type: 'POPUP_GET_STATUS' })
            .catch(() => null);
        }
      }

      if (response && response.status) {
        updateUI(response.status);
      } else {
        // Intentar leer del storage directamente
        const result = await chrome.storage.local.get('__hermes2_recorder_state');
        const state = result['__hermes2_recorder_state'];
        if (state) {
          updateUI({
            grabando: state.grabando,
            flujoNombre: state.flujoNombre,
            totalAcciones: (state.acciones || []).length,
            totalElementos: Object.keys(state.elementos || {}).length
          });
        } else {
          updateUI({ grabando: false, flujoNombre: null, totalAcciones: 0, totalElementos: 0 });
        }
      }
    } catch (e) {
      updateUI(null);
    }
  }

  // ─────────────────────────────────────────────
  // ENVIAR COMANDO AL TAB ACTIVO
  // ─────────────────────────────────────────────

  async function injectContentScript(tabId) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['content.js']
      });
      // Esperar un momento para que el content script se inicialice
      await new Promise(resolve => setTimeout(resolve, 300));
      return true;
    } catch (e) {
      return false;
    }
  }

  async function sendCommand(command, args = []) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      showMsg('⚠️ No hay pestaña activa', 'err');
      return false;
    }

    // Primer intento
    try {
      await chrome.tabs.sendMessage(tab.id, { type: 'POPUP_COMMAND', command, args });
      return true;
    } catch (_) {
      // Content script no está inyectado — inyectarlo programáticamente y reintentar
    }

    const injected = await injectContentScript(tab.id);
    if (!injected) {
      showMsg('⚠️ No se puede acceder a esta página (chrome:// u otra restringida)', 'err');
      return false;
    }

    // Segundo intento tras inyección
    try {
      await chrome.tabs.sendMessage(tab.id, { type: 'POPUP_COMMAND', command, args });
      return true;
    } catch (e) {
      showMsg('⚠️ Error al comunicar. Recarga la página manualmente (F5).', 'err');
      return false;
    }
  }

  // ─────────────────────────────────────────────
  // BOTONES
  // ─────────────────────────────────────────────

  btnStart.addEventListener('click', async () => {
    const nombre = flujoInput.value.trim();

    // Nombre obligatorio
    if (!nombre) {
      flujoInput.focus();
      flujoInput.style.borderColor = '#e74c3c';
      showMsg('⚠️ Escribe el nombre del flujo antes de grabar', 'err');
      setTimeout(() => { flujoInput.style.borderColor = ''; }, 2000);
      return;
    }

    // Bloquear botón inmediatamente para evitar doble clic
    btnStart.disabled = true;
    btnStart.textContent = '⏳ Iniciando...';

    const ok = await sendCommand('START', [nombre]);

    // VERIFICAR que el recorder realmente arrancó (no solo que el mensaje
    // llegó al content script). Si el recorder no está en la página, antes
    // decía "Grabando" y no grababa nada.
    let confirmed = false;
    if (ok) {
      await new Promise(r => setTimeout(r, 500));
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        const response = await chrome.tabs.sendMessage(
          tab.id, { type: 'POPUP_GET_STATUS' }
        ).catch(() => null);
        confirmed = !!(response && response.status && response.status.grabando);
      } catch (e) { confirmed = false; }
    }

    if (confirmed) {
      showMsg('✓ Grabando: ' + nombre, 'ok');
      flujoInput.value = '';
      setTimeout(refreshStatus, 400);
    } else {
      showMsg('⚠️ El recorder no arrancó. Recarga la página (F5) y reintenta.', 'err');
      btnStart.disabled = false;
      btnStart.textContent = '🔴 Iniciar Grabación';
    }
  });

  // Limpiar error visual al escribir
  flujoInput.addEventListener('input', () => {
    flujoInput.style.borderColor = '';
    if (msgEl.classList.contains('err')) msgEl.textContent = '';
  });

  btnStop.addEventListener('click', async () => {
    btnStop.disabled = true;
    btnStop.textContent = '⏳ Exportando...';
    await sendCommand('STOP');
    showMsg('✓ JSON descargando...', 'ok');
    setTimeout(refreshStatus, 600);
  });

  btnExport.addEventListener('click', async () => {
    await sendCommand('EXPORT');
    showMsg('✓ JSON en la consola del tab activo', 'ok');
  });

  // ─────────────────────────────────────────────
  // INIT
  // ─────────────────────────────────────────────

  refreshStatus();
  // Actualizar cada 2 segundos mientras el popup está abierto
  const interval = setInterval(refreshStatus, 2000);
  window.addEventListener('unload', () => clearInterval(interval));

})();
