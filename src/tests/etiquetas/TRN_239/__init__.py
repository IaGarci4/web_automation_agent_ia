"""
TRN-239 · Etiqueta de pruebas de la API Lunex.

Migración de riesgo: el back end de notificaciones de recargas pasa de Urano
(.NET, WCF/SOAP) a una API FastAPI publicada en **zeus-services**:

    https://zeus-services.maxilabs.net/api/v1/lunex/

No cuelga del gateway Argo, aunque la documentación lo dijera: Argo devuelve
404 en todas las rutas de Payments. Ver `README.md`.

Lo que hay que demostrar no es que «funciona», sino que **no hay diferencias
de datos** con el legacy.

A diferencia de las demás etiquetas, esta **no usa navegador**. Las pruebas
van directo contra la API, porque la notificación es servidor-a-servidor: la
recarga por la interfaz de Hermes cuesta dinero real y ni siquiera captura lo
que se quiere medir.
"""
