"""
CP09-CatalogoErrores — provocar cada Errorcode del requerimiento, a propósito.

## Por qué este caso «pasa cuando falla»

La Integration Guide (Confluence) publica un catálogo de Errorcodes. Cada uno
protege un flujo de validación: firma, esquema, unicidad, estados, etc. Cuando
se migra el back end, lo más fácil de romper sin que nadie lo note es
precisamente eso — que una validación deje de disparar y empiece a **aceptar**
lo que antes rechazaba.

Así que aquí se manda basura a propósito y **se espera el rechazo**. Si la API
responde con error (Errorcode != 0), el paso es OK: la defensa sigue en pie. Si
la API **acepta** la basura, es FALLA: la migración bajó la guardia.

Como bonus, se comprueba si el Errorcode devuelto **coincide** con el que el
documento asigna a ese caso. Que rechace ya es lo importante; que además
devuelva el código correcto se anota (si difiere, el mensaje al cliente cambió).

## Catálogo (del documento)

    0  Success                      (no se prueba aquí: es el happy path)
    1  Request is null              body vacío o malformado
    2  Transaction already exists   Key o TransactionID ya usado
    3  Action is not recognized     Action debe ser 'lunex'
    4  Session is invalid           MD5 no cuadra
    5  Validation error             falta un campo requerido
    6  Key is invalid               Key duplicada o inválida
    7  ExternalID is not recognized no se pudo parsear agente/usuario
    8  SKU Type is not recognized   SKUType∉(ITU,DTU) → debe dar 8 (regla r8);
                                     si la API da 10, es DEFECTO a reportar
    9  Status is not recognized     Status∉(SUCCESS,VOID) → debe dar 9 (regla r9);
                                     si la API acepta, es DEFECTO a reportar
    10 Agent is not configured      agente que EXISTE pero sin esquema —
                                     no aislable sin dato de BD (query en el .md)
    12 Transaction not cancellable  no existe o no se puede cancelar
    15 Internal error               no se fuerza; un Amount basura debe rechazar
                                     limpio (no aceptar, no colgarse)

El código C# del legado (Prometeo, DTU_ITU_COMISIONES) confirma el ORDEN de
validación, así que cada código tiene dueño en el flujo y una desviación es un
DEFECTO a reportar a DEV — no un «pendiente» en verde. Esto sale a producción.
"""

import random

import pytest

from config.logger import get_logger

from . import parametros as P
from .flujos import bodies as B
from .flujos import lunex_api as API

logger = get_logger("TRN-239")


def _base(cnt, productos) -> dict:
    """Un cuerpo VÁLIDO del que partir para romper UNA sola cosa."""
    itu = [p for p in productos if p[2] == "ITU"] or P.PRODUCTOS_ITU
    return B.alta(cnt, random.choice(itu))


@pytest.mark.etiqueta
@pytest.mark.api_lunex
@pytest.mark.caso_trn239(P.CP09, "Catálogo de errores: cada entrada inválida "
                                 "debe ser rechazada con su Errorcode")
def test_CP09_CatalogoErrores(caso, cnt, productos):
    # ── Caso 2 aparte: necesita un alta válida previa para repetirla ─────────
    previa = _base(cnt, productos)
    rp = API.registrar(previa)
    caso.evi.http("err02_alta_previa", url=rp.url, peticion=previa,
                  respuesta=rp.cuerpo, estado=rp.estado, ms=rp.ms, paso=2)
    # Reenvío del MISMO TransactionID → debe dar «ya existe».
    repetida = _base(cnt, productos)
    repetida["TransactionID"] = previa["TransactionID"]

    # ── Escenarios de un solo disparo ────────────────────────────────────────
    # (código_esperado, nombre, qué_se_rompe, cuerpo, es_cancelacion)
    def rompe(**cambios):
        c = _base(cnt, productos)
        c.update(cambios)
        return c

    def clave_invalida():
        # Key=0 CON su Md5 recalculado, para romper SOLO la Key y no arrastrar
        # un fallo de firma (que daría Errorcode 4 en vez de 6).
        c = _base(cnt, productos)
        c["Key"] = 0
        c["Md5"] = B.md5_firma(0)
        return c

    # Cada escenario rompe UNA cosa. Para aislar 1/5 hay que fallar SIN romper
    # la resolución del agente (que dispara 10). El 8 y el 9 esperan su código
    # exacto (r8/r9 del código C#); si sale otro, es defecto (ver más abajo).
    # (esperado, nombre, qué se rompe, cuerpo dict, es_cancel, cuerpo crudo)
    escenarios = [
        (1,  "Request is null",            "cuerpo HTTP vacío",                 None,                                                  False, ""),
        (2,  "Transaction already exists", "TransactionID repetido",            repetida,                                              False, None),
        (3,  "Action is not recognized",   "Action='no_lunex'",                 rompe(Action="no_lunex"),                              False, None),
        (4,  "Session is invalid",         "Md5 inválido",                      rompe(Md5="00000000000000000000000000000000"),        False, None),
        (5,  "Validation error",           "TransactionDate malformado (no toca SKU/agente)", rompe(TransactionDate="fecha-invalida"), False, None),
        (6,  "Key is invalid",             "Key=0 (con Md5 recalculado)",       clave_invalida(),                                      False, None),
        (7,  "ExternalID is not recognized","ExternalID='NOPARSE'",             rompe(ExternalID="NOPARSE"),                           False, None),
        (8,  "SKU Type is not recognized", "SKUType='ZZZ'",                     rompe(SKUType="ZZZ"),                                  False, None),
        (9,  "Status is not recognized",   "Status='ZZZ' (basura pura)",        rompe(Status="ZZZ"),                                   False, None),
        (10, "Agent is not configured",    "ExternalID de un agente sin esquema", rompe(ExternalID=B.external_id(id_agent=999999)),   False, None),
        (12, "Transaction not cancellable","cancelar un TransactionID inexistente", B.cancelacion(cnt, "9999999999", "8510", "ITU"),  True,  None),
        (15, "Internal error",             "Amount no numérico ('abc')",        rompe(Amount="abc"),                                   False, None),
    ]

    # ── Fuente de verdad: el CÓDIGO C# del legado (Prometeo) ─────────────────
    # Orden real de validación de LunexService.svc:
    #   r1(1 body) → r3(3 Action) → r9(9 Status∈SUCCESS/VOID) → r4(4 Md5) →
    #   Amount>0 → r5(5 modelo) → r6(6 Key) → r7(7 ExternalID) →
    #   r8(8 SKUType∈ITU/DTU) → esquema de comisión (10 si el agente no tiene).
    # Cada código tiene dueño en el flujo. Una desviación (aceptar algo inválido,
    # o devolver otro código) es un DEFECTO a reportar a DEV — NO un "pendiente"
    # pintado de verde. Esto sale a producción: no se oculta nada.
    #
    # El ÚNICO que no se puede aislar desde el arnés es el 10: exige un agente
    # REAL sin esquema de comisión (dato de BD que no tenemos; la query está en
    # DTU_ITU_COMISIONES_TRN-239.md). Un agente inexistente da 15 — que es en sí
    # un hallazgo (error no controlado).
    DOCS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15}

    for esperado, nombre, que_rompe, cuerpo, es_cancel, crudo in escenarios:
        if crudo is not None:
            r = API.registrar_crudo(crudo)
            peticion = f"(cuerpo crudo: {crudo!r})"
        elif es_cancel:
            r = API.cancelar(cuerpo)
            peticion = cuerpo
        else:
            r = API.registrar(cuerpo)
            peticion = cuerpo
        ev = caso.evi.http(f"err{esperado:02d}", url=r.url, peticion=peticion,
                           respuesta=r.cuerpo or r.texto[:500],
                           estado=r.estado, ms=r.ms, paso=esperado,
                           modificado=f"para Errorcode {esperado}: {que_rompe}")

        try:
            cod = int(r.errorcode)
        except (TypeError, ValueError):
            cod = None

        # Datos para reproducir, siempre — es lo que pediste incluir sobre
        # todo cuando la API acepta algo que debía rechazar.
        op = "CancelTransaction" if es_cancel else "RegisterTransaction"
        repro = (f"REPRODUCIR → POST {r.url} · se rompe: {que_rompe} · "
                 f"HTTP {r.estado} · Errorcode={r.errorcode}. El cuerpo exacto "
                 f"está en la evidencia; reenvíalo cambiando Key y "
                 f"TransactionID por valores nuevos.")

        if not r.endpoint_existe:
            caso.paso(f"Errorcode {esperado} · {nombre}", False,
                      f"no hay endpoint publicado ({op}, HTTP {r.estado}): no se "
                      f"pudo probar. {repro}", ev)
        elif esperado == 15:
            # 15 = «error interno inesperado»; no se fuerza a propósito. Lo que
            # se prueba es que un Amount basura se maneje LIMPIO: rechazo
            # documentado = OK; aceptarlo o colgarse = DEFECTO.
            if cod in DOCS and cod != 0:
                caso.paso(f"Errorcode {esperado} · {nombre}", True,
                          f"la API rechazó de forma estructurada con Errorcode "
                          f"{cod} (no se colgó ni devolvió 5xx crudo). {repro}",
                          ev)
            elif cod == 0:
                caso.paso(f"Errorcode {esperado} · {nombre}", False,
                          f"DEFECTO: la API ACEPTÓ un Amount no numérico "
                          f"(Errorcode 0); el código valida Amount>0. Reportar a "
                          f"DEV. {repro}", ev)
                caso.anotar("DEFECTO (Amount): la API acepta un Amount no "
                            "numérico. Reportar a DEV.")
            else:
                caso.paso(f"Errorcode {esperado} · {nombre}", False,
                          f"respuesta cruda (Errorcode {r.errorcode}, HTTP "
                          f"{r.estado}): error no controlado. Reportar a DEV. "
                          f"{repro}", ev)
        elif esperado == 10:
            # 10 solo se dispara con un agente REAL sin esquema (dato de BD).
            # No lo tenemos, así que no se puede confirmar en verde sin hardcode.
            if cod == 10:
                caso.paso(f"Errorcode {esperado} · {nombre}", True,
                          f"la API rechazó con Errorcode 10, exacto. {repro}", ev)
            else:
                es15 = (" — y con un agente INEXISTENTE la API devolvió 15 "
                        "(error interno no controlado): defecto candidato"
                        if cod == 15 else f" (la API devolvió {r.errorcode})")
                caso.paso(f"Errorcode {esperado} · {nombre}", False,
                          f"NO aislado: el 10 exige un agente REAL sin esquema de "
                          f"comisión (dato de BD, ver DTU_ITU_COMISIONES){es15}. "
                          f"{repro}", ev)
                caso.anotar(
                    "code 10: PENDIENTE dato de BD (agente real sin esquema, "
                    "query en DTU_ITU_COMISIONES). El agente inexistente devuelve "
                    "15 (no controlado) — reportar a DEV.")
        elif cod == esperado:
            # Rechazó con el código correcto: la validación sigue en pie.
            caso.paso(f"Errorcode {esperado} · {nombre}", True,
                      f"la API rechazó con Errorcode {cod}, coherente con el "
                      f"código C# del legado. {repro}", ev)
        elif cod == 0:
            # ACEPTÓ una petición inválida que el código C# valida y rechaza.
            # Es un DEFECTO que sale a producción → FALLA, reportar a DEV.
            caso.paso(f"Errorcode {esperado} · {nombre}", False,
                      f"DEFECTO: la API ACEPTÓ (Errorcode 0) una petición "
                      f"inválida que el legado rechaza con {esperado} («{nombre}»). "
                      f"Sale a producción → reportar a DEV. {repro}", ev)
            caso.anotar(
                f"DEFECTO code {esperado} «{nombre}»: la API acepta input "
                f"inválido que el legado rechaza. Reportar a DEV.")
        elif cod in DOCS:
            # Rechazó, pero con OTRO código documentado. El código C# valida
            # «{nombre}» en su punto del flujo; si sale otro, o la migración
            # cambió el orden o hay un defecto. Se reporta a DEV.
            caso.paso(f"Errorcode {esperado} · {nombre}", False,
                      f"DEFECTO CANDIDATO: rechazó con Errorcode {cod}, pero el "
                      f"código C# valida «{nombre}» y debería dar {esperado}. "
                      f"Reportar a DEV. {repro}", ev)
            caso.anotar(
                f"DEFECTO code {esperado} «{nombre}»: la API devuelve {cod} en "
                f"vez de {esperado}. Reportar a DEV.")
        else:
            # Código fuera del catálogo, o 5xx: flujo roto.
            caso.paso(f"Errorcode {esperado} · {nombre}", False,
                      f"respuesta FUERA del catálogo (Errorcode {r.errorcode}, "
                      f"HTTP {r.estado}): flujo roto. Reportar a DEV. {repro}", ev)

    caso.exigir()
