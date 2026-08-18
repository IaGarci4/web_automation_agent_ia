/**
 * CONTENT SCRIPT v2.1 - Isolated World Bridge
 *
 * Corre en el isolated world de Chrome (tiene acceso a chrome.* APIs).
 * Se comunica con recorder-core.js (MAIN world) via window.postMessage.
 *
 * Cambios v2.1:
 *  - TODAS las llamadas chrome.runtime.* van con try/catch síncrono además
 *    del .catch() asíncrono. Cuando se recarga la extensión con pestañas
 *    abiertas, el content script viejo queda huérfano y sendMessage lanza
 *    'Extension context invalidated' de forma SÍNCRONA — eso generaba
 *    errores en chrome://extensions aunque la grabación funcionara.
 *  - Guard anti doble sendResponse en POPUP_GET_STATUS.
 *
 * Responsabilidades:
 *  - Restaurar estado del recorder en cada carga de página (con reintentos)
 *  - Escuchar mensajes de recorder-core.js (SAVE_STATE, CLEAR_STATE, DOWNLOAD)
 *  - Guardar/leer estado en chrome.storage.local via background.js
 *  - Reenviar comandos del popup al recorder en MAIN world
 */

(function () {
  'use strict';

  // ─────────────────────────────────────────────
  // ENVÍO SEGURO AL BACKGROUND
  // try/catch síncrono (contexto invalidado) + .catch asíncrono (SW dormido)
  // ─────────────────────────────────────────────

  function safeSendMessage(message) {
    try {
      return chrome.runtime.sendMessage(message).catch(() => null);
    } catch (e) {
      // 'Extension context invalidated' — la extensión fue recargada y este
      // content script quedó huérfano. Recargar la página (F5) lo renueva.
      return Promise.resolve(null);
    }
  }

  // ─────────────────────────────────────────────
  // RESTAURACIÓN AL CARGAR LA PÁGINA (con reintentos + ACK)
  // ─────────────────────────────────────────────

  let restoreAcked = false;

  window.addEventListener('message', function (event) {
    if (event.source !== window) return;
    if (event.data && event.data.type === '__HERMES2_RECORDER_RESTORE_ACK') {
      restoreAcked = true;
    }
  });

  function deliverState(state) {
    if (restoreAcked) return;
    window.postMessage({
      type: '__HERMES2_RECORDER_RESTORE',
      state: state
    }, '*');
  }

  function restoreFromStorage() {
    safeSendMessage({ type: 'RECORDER_GET_STATE' }).then((response) => {
      if (response && response.state !== undefined) {
        const state = response.state;
        // Entregar con reintentos — recorder-core puede no estar listo aún
        deliverState(state);
        setTimeout(() => deliverState(state), 150);
        setTimeout(() => deliverState(state), 500);
        setTimeout(() => deliverState(state), 1200);
      } else {
        // Background dormido o sin respuesta — un reintento
        setTimeout(() => {
          safeSendMessage({ type: 'RECORDER_GET_STATE' }).then((r2) => {
            deliverState(r2 ? r2.state : null);
          });
        }, 300);
      }
    });
  }

  restoreFromStorage();

  // ─────────────────────────────────────────────
  // MENSAJES DESDE MAIN WORLD (recorder-core.js)
  // ─────────────────────────────────────────────

  window.addEventListener('message', function (event) {
    // Solo mensajes de la misma ventana
    if (event.source !== window) return;
    if (!event.data || event.data.type !== '__HERMES2_RECORDER') return;

    const msg = event.data;

    switch (msg.action) {

      case 'SAVE_STATE':
        safeSendMessage({
          type: 'RECORDER_SAVE_STATE',
          state: msg.state
        }).then((response) => {
          if (!response) {
            // Background dormido — un reintento corto
            setTimeout(() => {
              safeSendMessage({ type: 'RECORDER_SAVE_STATE', state: msg.state });
            }, 200);
          }
        });
        break;

      case 'CLEAR_STATE':
        safeSendMessage({ type: 'RECORDER_CLEAR_STATE' });
        break;

      case 'DOWNLOAD':
        safeSendMessage({
          type: 'RECORDER_DOWNLOAD',
          data: msg.data,
          filename: msg.filename
        }).then((response) => {
          // Notificar al recorder-core que la extensión manejó la descarga.
          // Esto evita que el fallback blob se active innecesariamente.
          if (response && response.ok) {
            window.postMessage({ type: '__HERMES2_RECORDER_DOWNLOAD_ACK' }, '*');
          }
        });
        break;
    }
  });

  // ─────────────────────────────────────────────
  // COMANDOS DESDE EL POPUP
  // ─────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

    if (message.type === 'POPUP_COMMAND') {
      // Reenviar al MAIN world
      window.postMessage({
        type: '__HERMES2_RECORDER_CMD',
        command: message.command,
        args: message.args || []
      }, '*');
      sendResponse({ ok: true });
    }

    if (message.type === 'POPUP_GET_STATUS') {
      // Pedir estado al recorder en MAIN world
      window.postMessage({ type: '__HERMES2_RECORDER_CMD', command: 'GET_STATUS' }, '*');

      // Guard: sendResponse solo puede llamarse UNA vez
      let responded = false;
      const respondOnce = (payload) => {
        if (responded) return;
        responded = true;
        try { sendResponse(payload); } catch (e) { /* canal cerrado */ }
      };

      // El recorder responderá con un postMessage
      const handler = function (event) {
        if (event.source !== window) return;
        if (!event.data || event.data.type !== '__HERMES2_RECORDER_STATUS') return;
        window.removeEventListener('message', handler);
        respondOnce({ status: event.data.status });
      };
      window.addEventListener('message', handler);

      // Timeout por si el recorder no responde
      setTimeout(() => {
        window.removeEventListener('message', handler);
        respondOnce({ status: null });
      }, 500);

      return true; // Async
    }
  });

})();
