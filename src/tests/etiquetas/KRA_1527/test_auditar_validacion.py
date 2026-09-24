"""
AUDITORÍA (DevTools) del validador de direcciones — sin adivinar.

Por cada dirección: llena el cliente, resuelve la dirección, y VUELCA la verdad:
  · DOM del campo de dirección: value, aria-invalid, clases, y el HTML del
    contenedor (para ver el nodo real del mensaje "Dirección no verificada").
  · Todos los nodos de texto que digan "no verificad / valid address / invalid",
    con su etiqueta, clase y si están VISIBLES.
  · Estado del botón Continuar (habilitado/deshabilitado).
  · Llamadas de RED cuyo URL parezca de verificación (address/valid/verify/
    suggest), con status y un extracto del body.

Escribe todo a reports/evidence/KRA-1527/auditoria_direccion_<i>.json para que
podamos ver EXACTAMENTE cómo Hermes marca el error y construir el detector bien.

Ejecutar:
    $env:KRA1527_AUDIT="1"; $env:KRA1527_AUDIT_ITER="5"
    pytest src/tests/etiquetas/KRA_1527/test_auditar_validacion.py -s
"""

import asyncio
import json
import os
from pathlib import Path

import pytest
from faker import Faker

from config import settings
from config.logger import get_logger
from src.helpers.direcciones_us import candidatos
from .flujos.transferencia_page import HmTransferelektraPage

logger = get_logger("KRA-1527.audit")

OUT = settings.EVIDENCE_DIR / "KRA-1527"

_JS_DUMP = r"""
() => {
  const out = {error_nodes: []};
  const addr = document.querySelector('[data-testid="transfer-customer-address-0-input"]');
  if (addr) {
    out.addr_value = addr.value || '';
    out.addr_ariaInvalid = addr.getAttribute('aria-invalid');
    out.addr_class = addr.className;
    let cont = addr;
    for (let i=0;i<4 && cont.parentElement;i++) cont = cont.parentElement;
    out.container_html = (cont ? cont.outerHTML : '').replace(/\s+/g,' ').slice(0,5000);
  } else {
    out.addr_value = '(no encontré el input)';
  }
  const re = /no\s*verificad|selecciona una direcci|valid address|not\s*verified|invalid|verific/i;
  const seen = new Set();
  document.querySelectorAll('*').forEach(el => {
    if (el.children.length === 0) {
      const t = (el.textContent||'').trim();
      if (t && re.test(t) && !seen.has(t)) {
        seen.add(t);
        out.error_nodes.push({text: t.slice(0,140), tag: el.tagName,
                              cls: (el.className||'').toString().slice(0,120),
                              visible: !!(el.offsetParent)});
      }
    }
  });
  const btn = document.querySelector('[data-testid="transfer-continue-button-0-button"] button, [data-testid="transfer-continue-button-0-button"]');
  if (btn) { out.continue_disabled = btn.disabled === true || btn.getAttribute('disabled')!==null; }
  const zip = document.querySelector('[data-testid="transfer-customer-zip-code-0-input"]');
  const city = document.querySelector('[data-testid="transfer-customer-city-0-input"]');
  out.zip_value = zip ? (zip.value||'') : '';
  out.city_value = city ? (city.value||'') : '';
  return out;
}
"""


@pytest.mark.audit_dir
@pytest.mark.asyncio
async def test_auditar_validacion(logged_page):
    if os.getenv("KRA1527_AUDIT", "0").strip().lower() not in ("1", "true", "si", "sí", "yes"):
        pytest.skip("Auditoría desactivada. Actívala con KRA1527_AUDIT=1.")

    n = int(os.getenv("KRA1527_AUDIT_ITER", "5") or "5")
    flow = HmTransferelektraPage(logged_page)
    page = logged_page
    fake = Faker("en_US")
    doms = candidatos(max(n, 5))
    OUT.mkdir(parents=True, exist_ok=True)

    # Capturar llamadas de red de verificación.
    red = []

    async def _grab(resp):
        u = resp.url.lower()
        if any(k in u for k in ("address", "valid", "verify", "verif", "suggest")):
            try:
                body = await resp.text()
            except Exception:
                body = ""
            red.append({"url": resp.url, "status": resp.status,
                        "body": (body or "")[:600]})

    def _on(resp):
        try:
            asyncio.ensure_future(_grab(resp))
        except Exception:
            pass

    page.on("response", _on)

    resumen = []
    for i in range(1, n + 1):
        dom = doms[(i - 1) % len(doms)]
        red.clear()
        await flow.navigate()
        await flow.fill_transfer_customer_cellphone_0_cellphone_input(fake.numerify("210555####"))
        await flow.fill_transfer_customer_name_0_input(fake.first_name())
        await flow.fill_transfer_customer_first_lastname_0_input(fake.last_name())
        await flow.fill_transfer_customer_second_lastname_0_input(fake.last_name())
        try:
            await flow.click_close_table()
        except Exception:
            pass

        # Resolver dirección (la lógica actual) y luego avanzar a beneficiario.
        try:
            await flow.resolver_direccion_cliente(dom["direccion"], zip_preferido=dom["zip"])
        except Exception as e:
            logger.warning("[Audit %d] resolver: %s", i, str(e)[:120])
        try:
            await flow.fill_transfer_beneficiary_country_0_dropdown_input("MEXICO")
        except Exception:
            pass
        await page.wait_for_timeout(4_000)   # dar tiempo a que pinte el error si va a salir

        try:
            estado = await page.evaluate(_JS_DUMP)
        except Exception as e:
            estado = {"error_eval": str(e)[:200]}
        estado["semilla"] = dom
        estado["red_verificacion"] = list(red)

        archivo = OUT / f"auditoria_direccion_{i}.json"
        archivo.write_text(json.dumps(estado, ensure_ascii=False, indent=2),
                           encoding="utf-8")

        vis_err = [e for e in estado.get("error_nodes", []) if e.get("visible")]
        logger.info("[Audit %d/%d] zip=%s addr='%s' aria-invalid=%s · nodos_error_visibles=%d · continue_disabled=%s → %s",
                    i, n, estado.get("zip_value"), estado.get("addr_value"),
                    estado.get("addr_ariaInvalid"), len(vis_err),
                    estado.get("continue_disabled"), archivo.name)
        for e in vis_err[:3]:
            logger.info("      ERROR VISIBLE: '%s' <%s class=%s>",
                        e["text"], e["tag"], e["cls"])
        resumen.append({"i": i, "zip": estado.get("zip_value"),
                        "addr": estado.get("addr_value"),
                        "aria_invalid": estado.get("addr_ariaInvalid"),
                        "err_visibles": len(vis_err),
                        "continue_disabled": estado.get("continue_disabled")})

    try:
        page.remove_listener("response", _on)
    except Exception:
        pass

    (OUT / "auditoria_resumen.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("═" * 60)
    logger.info("[Audit] Terminado. Revisa: %s", OUT / "auditoria_direccion_1.json")
    logger.info("[Audit] Resumen: %s", OUT / "auditoria_resumen.json")
    logger.info("═" * 60)
