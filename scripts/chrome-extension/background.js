/**
 * BACKGROUND SERVICE WORKER - HERMES2 Action Recorder
 *
 * Responsabilidades:
 * 1. Detectar cada navegación (onCompleted)
 * 2. Inyectar recorder-core.js en MAIN world (bypasea CSP del sitio)
 * 3. Pasar el estado guardado al recorder en cada inyección
 * 4. Manejar mensajes del content.js (guardar/leer estado)
 * 5. Gestionar descarga del JSON final
 */

const STORAGE_KEY = '__hermes2_recorder_state';

// ─────────────────────────────────────────────
// INYECCIÓN EN CADA NAVEGACIÓN
// ─────────────────────────────────────────────

chrome.webNavigation.onCompleted.addListener(async (details) => {
  // Solo inyectar en el frame principal (no iframes)
  if (details.frameId !== 0) return;

  try {
    // Leer estado guardado ANTES de inyectar
    const result = await chrome.storage.local.get(STORAGE_KEY);
    const savedState = result[STORAGE_KEY] || null;

    // Inyectar en MAIN world — esto NO puede ser bloqueado por CSP del sitio
    await chrome.scripting.executeScript({
      target: { tabId: details.tabId },
      world: 'MAIN',
      files: ['recorder-core.js']
    });

    // Pasar el estado guardado al recorder via función separada
    await chrome.scripting.executeScript({
      target: { tabId: details.tabId },
      world: 'MAIN',
      func: restoreRecorderState,
      args: [savedState]
    });

  } catch (err) {
    // Casos esperados que NO son errores reales: tabs chrome://, páginas de
    // la galería de extensiones, tabs cerradas a mitad de navegación, etc.
    const expected = [
      'Cannot access',
      'chrome://',
      'extensions gallery',
      'No tab with id',
      'The tab was closed',
      'showing error page',
      'Frame with ID',
    ];
    const msg = err && err.message ? err.message : String(err);
    if (!expected.some(p => msg.includes(p))) {
      console.error('[HERMES2 Recorder] Error al inyectar:', err);
    }
  }
});

/**
 * Esta función se serializa y ejecuta en MAIN world del tab.
 * Recibe el estado guardado y restaura el recorder.
 */
function restoreRecorderState(savedState) {
  if (window.__recorderCoreLoaded && savedState) {
    window.__recorderRestoreState(savedState);
  }
}

// ─────────────────────────────────────────────
// MENSAJES DESDE content.js
// ─────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  if (message.type === 'RECORDER_SAVE_STATE') {
    // content.js pide guardar el estado del recorder
    chrome.storage.local.set({ [STORAGE_KEY]: message.state })
      .then(() => sendResponse({ ok: true }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true; // Async response
  }

  if (message.type === 'RECORDER_CLEAR_STATE') {
    // Grabación finalizada — limpiar estado guardado
    chrome.storage.local.remove(STORAGE_KEY)
      .then(() => sendResponse({ ok: true }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === 'RECORDER_GET_STATE') {
    // content.js pide leer el estado (para pasarlo al popup)
    chrome.storage.local.get(STORAGE_KEY)
      .then(result => sendResponse({ state: result[STORAGE_KEY] || null }))
      .catch(err => sendResponse({ state: null }));
    return true;
  }

  if (message.type === 'RECORDER_DOWNLOAD') {
    // Service Workers NO tienen URL.createObjectURL (es API del DOM).
    // Usamos un data URL base64 que sí funciona en service worker.
    const { data, filename } = message;
    const json = JSON.stringify(data, null, 2);
    const base64 = btoa(unescape(encodeURIComponent(json)));
    const dataUrl = 'data:application/json;base64,' + base64;

    chrome.downloads.download({
      url: dataUrl,
      filename: filename,
      saveAs: false
    }, (downloadId) => {
      if (chrome.runtime.lastError) {
        sendResponse({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        sendResponse({ ok: true, downloadId });
      }
    });
    return true;
  }

});

// ─────────────────────────────────────────────
// FIX v1.1: tabs.onUpdated eliminado.
// webNavigation.onCompleted cubre todas las navegaciones correctamente.
// Tener ambos causaba doble inyección del recorder → estado duplicado.
// ─────────────────────────────────────────────
