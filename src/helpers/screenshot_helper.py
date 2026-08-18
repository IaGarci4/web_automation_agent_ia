"""
ScreenshotHelper — captura de evidencias con resaltado visual.

Modos:
  screenshot_only()           → captura simple, sin resaltado
  screenshot_with_highlight() → captura + rectángulo verde sobre el elemento

Soporta búsqueda de texto en DOM o resaltado directo por locator/bbox.
Corrige coordenadas por Device Pixel Ratio (DPR) para pantallas HiDPI / Windows scaling.

Uso:
    screenshot = ScreenshotHelper(page)

    # Sin resaltado
    await screenshot.screenshot_only("evidence/step01.png")

    # Resaltado por texto en DOM
    await screenshot.screenshot_with_highlight("evidence/step02.png", search_text="ELEKTRA")

    # Resaltado por locator de Playwright
    btn = page.get_by_test_id("test-id-button")
    await screenshot.screenshot_with_highlight("evidence/step03.png", locators=[btn])
"""

import os
from typing import Optional
from PIL import Image, ImageDraw
from config.logger import get_logger

logger = get_logger("screenshot_helper")

GLOBAL_SELECTOR = "td, th, tr, li, span, p, div, label, button, a, h1, h2, h3, h4"


class ScreenshotHelper:
    def __init__(self, page):
        self.page = page

    # ── Espera de "pantalla lista" ────────────────────────────────────────────

    async def wait_ready(self, timeout: int = 10_000) -> None:
        """
        Espera a que la pantalla esté ESTABLE antes de capturar, para no
        fotografiar un loader, una pantalla en blanco o un estado intermedio
        antes de llegar a la pantalla objetivo. Verifica:
          1. document.readyState == 'complete'
          2. que NO haya loader/overlay bloqueante visible
          3. que el body tenga contenido real (no esté en blanco)
        Best-effort: si algo no se cumple en `timeout`, captura igual.
        """
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
        script = """
        () => {
            if (document.readyState !== 'complete') return false;
            // Loaders/overlays que no deben salir en la foto
            const sels = ['#maxi-loader', '.p-component-overlay', '.p-dialog-mask-scrollblocker'];
            for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                    const st = getComputedStyle(el);
                    if (st.display !== 'none' && st.visibility !== 'hidden'
                        && st.opacity !== '0') return false;
                }
            }
            // Pantalla no en blanco: hay texto visible suficiente
            const txt = (document.body && document.body.innerText || '').trim();
            return txt.length > 15;
        }
        """
        try:
            await self.page.wait_for_function(script, timeout=timeout)
        except Exception:
            pass  # captura igual aunque no se estabilice del todo
        # micro-pausa para que termine cualquier animación de entrada
        await self.page.wait_for_timeout(250)

    async def screenshot_only(
        self,
        screenshot_path: str,
        full_page: bool = False,
        timeout: int = 500,
        ready: bool = True,
    ) -> None:
        """Captura simple. Por defecto espera 'pantalla lista' (ready=True)."""
        os.makedirs(os.path.dirname(os.path.abspath(screenshot_path)), exist_ok=True)
        if ready:
            await self.wait_ready()
        elif timeout > 0:
            await self.page.wait_for_timeout(timeout)
        await self.page.screenshot(path=screenshot_path, full_page=full_page)
        logger.info(f"[Screenshot] Guardado: {screenshot_path}")

    async def screenshot_with_highlight(
        self,
        screenshot_path: str,
        search_text: Optional[str] = None,
        selector: Optional[str] = None,
        bbox: Optional[dict] = None,
        locators: Optional[list] = None,
        highlight_color: tuple = (144, 238, 144, 100),
        outline_color: tuple = (46, 125, 50, 255),
        outline_width: int = 3,
        full_page: bool = False,
        scroll_into_view: bool = True,
        timeout: int = 500,
        ready: bool = True,
    ) -> Optional[dict]:
        """
        Captura con resaltado verde sobre el elemento objetivo.
        Por defecto espera 'pantalla lista' (ready=True) antes de capturar.
        """
        os.makedirs(os.path.dirname(os.path.abspath(screenshot_path)), exist_ok=True)
        if ready:
            await self.wait_ready()
        effective_selector = selector or GLOBAL_SELECTOR

        # ── Buscar bbox por texto ─────────────────────────────────────────────
        if bbox is None and search_text:
            bbox = await self._find_bbox_by_text(search_text, effective_selector, scroll_into_view)
            if bbox is None:
                logger.warning(
                    f"[Screenshot] '{search_text}' no encontrado — screenshot sin resaltado."
                )

        # ── Recolectar bboxes de locators ─────────────────────────────────────
        # timeout corto: si el elemento ya no existe (ej. campos de login tras
        # navegar), se omite el resaltado en ~2s en vez de bloquear 30s
        locator_bboxes = []
        if locators:
            for locator in locators:
                try:
                    lb = await locator.bounding_box(timeout=2_000)
                    if lb:
                        locator_bboxes.append(lb)
                except Exception:
                    logger.info(
                        "[Screenshot] Locator no disponible — screenshot sin ese resaltado."
                    )

        if timeout > 0:
            await self.page.wait_for_timeout(timeout)

        # ── Device Pixel Ratio ────────────────────────────────────────────────
        try:
            dpr = await self.page.evaluate("window.devicePixelRatio") or 1.0
        except Exception:
            dpr = 1.0

        # ── Captura base ──────────────────────────────────────────────────────
        await self.page.screenshot(path=screenshot_path, full_page=full_page)
        logger.info(f"[Screenshot] Guardado: {screenshot_path}")

        # ── Dibujar resaltados ────────────────────────────────────────────────
        if bbox:
            self._draw_highlight(screenshot_path, bbox, highlight_color, outline_color, outline_width, dpr)
        for lb in locator_bboxes:
            self._draw_highlight(screenshot_path, lb, highlight_color, outline_color, outline_width, dpr)

        return bbox

    # ── Internos ──────────────────────────────────────────────────────────────

    async def _find_bbox_by_text(
        self, search_text: str, selector: str, scroll_into_view: bool
    ) -> Optional[dict]:
        return await self.page.evaluate(
            """([selector, text, scrollIntoView]) => {
                const elements = document.querySelectorAll(selector);
                for (const el of elements) {
                    const content = (el.innerText || el.textContent || '').trim();
                    if (content.toUpperCase().includes(text.toUpperCase())) {
                        if (scrollIntoView) {
                            el.scrollIntoView({ behavior: 'instant', block: 'center' });
                        }
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            return { x: r.x, y: r.y, width: r.width, height: r.height };
                        }
                    }
                }
                return null;
            }""",
            [selector, search_text, scroll_into_view],
        )

    def _draw_highlight(
        self,
        screenshot_path: str,
        bbox: dict,
        highlight_color: tuple,
        outline_color: tuple,
        outline_width: int,
        dpr: float = 1.0,
    ) -> None:
        img = Image.open(screenshot_path).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        x = round(bbox["x"] * dpr)
        y = round(bbox["y"] * dpr)
        w = round(bbox["width"] * dpr)
        h = round(bbox["height"] * dpr)
        draw.rectangle([x, y, x + w, y + h], fill=highlight_color)
        draw.rectangle([x, y, x + w, y + h], outline=outline_color, width=outline_width)
        Image.alpha_composite(img, overlay).convert("RGB").save(screenshot_path)
