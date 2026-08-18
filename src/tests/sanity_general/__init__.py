"""
Suite `sanity_general` — rescate del sanity manual de HERMES2-qa (CP01…CP22)
hacia el agente de IA, con capa estable de Información Adicional / Cuestionarios
y (próximamente) Chronos.

Convención de ejecución:
  • Todo el sanity     → `pytest src/tests/sanity_general -m sanity_general -v -s`
  • Un caso puntual    → `pytest src/tests/sanity_general -k CP01 -v -s`

Cada archivo es un CP independiente (test_CPNN_*.py) con el marker `sanity_general`.
El formulario principal se REUTILIZA de src/pagadores/flujo_mt.py; la capa flaky
(Info Adicional) usa src/sanity_general/info_adicional.py (fix por data-testid).
"""
