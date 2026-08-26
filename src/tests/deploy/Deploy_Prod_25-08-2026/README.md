# Deploy Prod 25/08/2026

Casos de prueba para el **deploy a producción del 25 de agosto de 2026**.

> El nombre de la carpeta usa guiones (`25-08-2026`) porque `/` no es un
> carácter válido en nombres de carpeta.

## Qué va aquí

Casos puntuales que hay que validar **para este deploy** (además del sanity
general y de las etiquetas de Jira). Cada archivo:

- se llama `test_<algo>.py`,
- lleva el marcador `@pytest.mark.deploy`,
- usa la fixture `logged_page` (sesión persistente) o `logged_page_multi`,
- guarda evidencias numeradas con la clase `Evidencia`.

Plantilla mínima:

```python
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import Evidencia

logger = get_logger("DEPLOY-2026-08-25")
EVIDENCE = "deploy_25-08-2026/mi_caso"


@pytest.mark.deploy
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_mi_caso(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE)
    ...
    await evi.shot("resultado")
```

## Cómo correr

```powershell
# Todos los casos de este deploy
pytest src/tests/deploy/Deploy_Prod_25-08-2026 -v -s --headed

# Por marcador (todos los deploys)
pytest -m deploy -v -s

# En producción
$env:HERMES_ENV="prod"; pytest src/tests/deploy/Deploy_Prod_25-08-2026 -v -s
```

## Casos de este deploy

| Caso | Qué valida | Estado |
|------|-----------|--------|
| _(pendiente)_ | | |
