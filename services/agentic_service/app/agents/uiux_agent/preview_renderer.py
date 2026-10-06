"""
UI/UX Agent preview renderer.

Purpose:
Render one page's already-assembled, self-contained HTML document (see page_html_builder.py) into
a PNG screenshot for the "Page Previews" thumbnail gallery. Mirrors plantuml_service's idiom
(deterministic file-in/bytes-out, raise RuntimeError on failure) -- same pattern, new content
type.

Simplified render path: this used to mount live JSX via vendored React/ReactDOM/Babel-standalone
(~2.6MB of vendored JS, plus a Babel-transform-then-React-mount step that could itself fail). A
page is now a plain, already-fully-formed HTML document, so this only ever has to screenshot
already-painted HTML/CSS -- Playwright's most basic and reliable capability, and a real
reliability win on top of being simpler. This is now a secondary, best-effort artifact -- the
PRIMARY preview is the raw HTML itself, rendered live via <iframe srcDoc> in the frontend, which
needs no browser-automation step at all.

Playwright's sync API is used here (like a plain function), and the async UIUXAgent calls it via
asyncio.to_thread -- the sync API cannot run inside an already-running asyncio event loop.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


class PreviewRenderError(RuntimeError):
    """Raised when a page could not be rendered to PNG."""


class UIUXPreviewRenderer:
    """
    Renders an already-assembled page HTML document into a single PNG.
    """

    def render_page_png(self, page_html: str) -> bytes:
        """
        page_html: the full, self-contained HTML document for one page (see
        page_html_builder.UIUXPageHtmlBuilder.build) -- the exact same content saved as the
        UI_PAGE_HTML artifact.

        Returns PNG bytes. Raises PreviewRenderError on failure.
        """

        if not page_html or not page_html.strip():
            raise PreviewRenderError("Cannot render an empty page document.")

        with tempfile.TemporaryDirectory() as tmp_dir:
            html_path = Path(tmp_dir) / "preview.html"
            html_path.write_text(page_html, encoding="utf-8")

            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        page = browser.new_page(viewport={"width": 900, "height": 700})

                        # Same generous-timeout precedent already established for this agent's
                        # rendering: real testing showed content that renders correctly and
                        # quickly in isolation can still hit Playwright's default action timeout
                        # under real pipeline CPU contention (Ollama/MongoDB/LangGraph all
                        # competing for cycles) -- kept even though this render path is now much
                        # simpler, since the contention cause is unrelated to what's rendered.
                        page.set_default_timeout(90000)

                        console_errors: list[str] = []
                        page.on(
                            "console",
                            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                        )
                        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

                        page.goto(html_path.as_uri())
                        page.wait_for_timeout(300)  # allow Tailwind's Play-CDN class scan to settle

                        body_locator = page.locator("body")
                        if body_locator.count() == 0 or not body_locator.first.inner_html().strip():
                            raise PreviewRenderError(
                                "Preview body rendered empty. "
                                f"Browser console errors: {console_errors}"
                            )

                        return page.screenshot(full_page=True)
                    finally:
                        browser.close()
            except PreviewRenderError:
                raise
            except Exception as error:
                raise PreviewRenderError(f"Playwright preview rendering failed: {error}") from error


uiux_preview_renderer = UIUXPreviewRenderer()
