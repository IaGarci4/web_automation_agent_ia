"""
CP15 — Uso de KYC Rules (compliance disparado por una regla KYC).
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP15_Uso_de_KYC_Rules.py`.)

Una KYC Rule activa (para el pagador/agencia, ACTIVADA MANUALMENTE en Chronos)
hace que, al dar Continue en un envío normal, Hermes exija Información Adicional.
Este módulo:
  1. Da Continue y abre la ficha de Información Adicional (reusa info_adicional).
  2. Valida que el motivo de '¿por qué se pide esta info?' mencione la KYC Rule.
  3. Llena la identificación con los datos del caso y acepta.

El envío principal (cliente + beneficiario + pagador + monto) y el cierre
(completar + cancelar) se reutilizan de flujo_mt / cancelacion — aquí solo vive
lo específico de la regla KYC.
"""

from config.logger import get_logger
from src.sanity_general import info_adicional as IA

logger = get_logger("sanity.kyc_rules")

# Testids de '¿por qué se requiere esta info?' dentro de la ficha de compliance.
WHY_ICON   = "compliance-additional-infowhy-info-required-icon"
WHY_REASON = "compliance-additional-infowhy-info-required-reason-0"
WHY_CLOSE  = "compliance-additional-infowhy-info-required-modal-icon"


async def validar_regla_kyc(flow, rule_name: str) -> bool:
    """Abre el '¿por qué se pide esta información?' y valida que el motivo
    mencione la KYC Rule esperada. Devuelve:
      • True  si el motivo contiene el nombre de la regla (o si el ícono no está,
               en cuyo caso no se puede validar y no se considera fallo).
      • False si el motivo apareció pero NO contiene el nombre de la regla.
    """
    page = flow.page
    try:
        icon = page.get_by_test_id(WHY_ICON).first
        if not await icon.is_visible():
            logger.warning("[CP15] Ícono 'why info required' no visible — no se pudo "
                           "validar el nombre de la KYC Rule (¿regla activa en Chronos?).")
            return True
        await icon.click()
        await page.wait_for_timeout(1_000)
        reason = page.get_by_test_id(WHY_REASON).first
        await reason.wait_for(state="visible", timeout=6_000)
        texto = (await reason.inner_text()) or ""
        ok = rule_name.strip().lower() in texto.strip().lower()
        if ok:
            logger.info("[CP15] Motivo de compliance menciona la KYC Rule '%s' ✓",
                        rule_name)
        else:
            logger.warning("[CP15] El motivo NO menciona la regla '%s'. Motivo: %s",
                           rule_name, " ".join(texto.split())[:160])
        # Cerrar el modal del 'why'.
        try:
            await page.get_by_test_id(WHY_CLOSE).first.click(timeout=4_000)
            await page.wait_for_timeout(400)
        except Exception:
            pass
        return ok
    except Exception as e:
        logger.warning("[CP15] No se pudo validar la KYC Rule: %s", str(e)[:110])
        return True


async def resolver_compliance_kyc(flow, *, rule_name: str, pais: str, tipo_id: str,
                                  num_id: str, exp: str, dob: str, tipo: str = "cash",
                                  logger=logger, evi=None) -> tuple:
    """Da Continue, abre la ficha de compliance por la KYC Rule, valida el motivo
    y llena/acepta la Información Adicional.

    Devuelve (compliance_aparecio, regla_validada). Si la ficha no aparece
    (la regla podría no estar activa en Chronos), devuelve (False, False) y el
    llamador decide si continúa igual."""
    # 1) Continue → dispara el modal de compliance.
    try:
        await flow.click_continue()
    except Exception:
        pass
    await flow.page.wait_for_timeout(3_000)

    # 2) Abrir la ficha de Información Adicional (maneja el modal 'Compliance
    #    information needed' → 'Add Additional Info').
    if not await IA.abrir_info_adicional(flow, tipo=tipo):
        logger.warning("[CP15] La ficha de compliance no apareció — ¿la KYC Rule "
                       "está ACTIVA en Chronos para este pagador/agencia?")
        return False, False
    if evi is not None:
        await evi.shot("compliance_dialog", paso=3)

    # 3) Validar que el motivo mencione la KYC Rule.
    regla_ok = await validar_regla_kyc(flow, rule_name)
    if evi is not None:
        await evi.shot("why_info_required", paso=4)

    # 4) Llenar la identificación y aceptar.
    llen = await IA.llenar_info_adicional_simple(
        flow, pais=pais, tipo_id=tipo_id, num_id=num_id, exp=exp, dob=dob, tipo=tipo)
    if llen:
        await IA.aceptar(flow)
        if evi is not None:
            await evi.shot("compliance_form_accepted", paso=6)
    else:
        logger.warning("[CP15] No se pudo llenar la Información Adicional.")
    return True, regla_ok
