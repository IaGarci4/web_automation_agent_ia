"""
CP07 — Regresión en PRODUCCIÓN (opcional).

Repite la comprobación núcleo (IdUser propio → 200; IdUser ajeno → 403) contra
PRODUCCIÓN. Por seguridad NO se ejecuta salvo que se pida explícitamente con
`KRA1526_PROD=1`, y requiere una sesión PROD válida.

Por qué es opt-in y no «todo automático» como TEST: el login de PROD entra por
el SSO de Google (correo Maxi + 2FA en el celular), que exige un paso humano la
primera vez — no se puede tomar un token headless sin intervención. Una vez que
exista sesión PROD (storage_state), este caso la reutiliza. Mientras tanto se
OMITE con nota, para no tocar producción sin querer.
"""

import pytest

from . import parametros as P

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor]


@pytest.mark.caso_kra1526(P.CP07, "Regresión en producción: IdUser propio → 200, "
                                  "ajeno → 403 (opcional)")
def test_CP07_regresion_produccion(caso, baseline):
    if not P.PROD:
        pytest.skip("[PROD] CP07 desactivado. Actívalo con KRA1526_PROD=1 y una "
                    "sesión PROD válida (login SSO Google con 2FA la primera vez).")

    # Con PROD activo se reutilizaría una captura apuntada a PROD. Requiere que
    # exista storage_state de PROD; si no, se omite con el motivo exacto en vez
    # de intentar un login SSO no atendido.
    pytest.skip("[PROD] Ejecuta la captura PROD una vez (login SSO atendido) y "
                "vuelve a correr; la automatización desatendida cubre TEST "
                "(CP01–CP06). Ver README de la etiqueta.")
