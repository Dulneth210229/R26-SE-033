"""
PDF rendering service.

Purpose:
Render a self-contained HTML document (no external CSS/CDN dependency -- every
caller embeds its own <style> block) into real PDF bytes via a headless
Chromium (Playwright). Used by the Requirement/Domain/Architecture Agent
download-as-PDF routes so a human gets a genuinely formatted document instead
of a raw JSON file.

Runs on a dedicated worker thread via ThreadPoolExecutor, mirroring
coder_agent/render_checker.py's own established, already-proven fix:
Playwright's sync API refuses to run on a thread with an already-running
asyncio event loop. Every real caller here is a plain synchronous FastAPI
route handler (so no event loop is actually active), but this guard is cheap
and keeps this module safe regardless of how it's called in the future.
"""

from __future__ import annotations

import concurrent.futures

from playwright.sync_api import sync_playwright

# Bottom margin is taller than the others to leave room for the page-number footer below --
# without this, the footer text can collide with the last line of body content on a full page.
PDF_MARGIN = {"top": "16mm", "bottom": "20mm", "left": "14mm", "right": "14mm"}

# header_template/footer_template render in an isolated mini-document with NO access to a
# caller's own <style> block, so each needs its own inline styling. header_template must be a
# non-empty template (an empty string is treated as "no override" and shows Chromium's own
# default header instead) -- an empty <span> is the standard way to suppress it while keeping
# the header area blank. pageNumber/totalPages are literal class names Chromium recognizes.
PAGE_HEADER_TEMPLATE = "<span></span>"

PAGE_FOOTER_TEMPLATE = """
<div style="width:100%; font-size:9px; color:#6b7280; text-align:center;
            font-family:Helvetica, Arial, sans-serif; padding:0 14mm;">
  Page <span class="pageNumber"></span> of <span class="totalPages"></span>
</div>
"""


def render_html_to_pdf(html: str) -> bytes:
    """
    Render an HTML string to PDF bytes using a headless Chromium.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(_render_html_to_pdf_on_worker_thread, html).result()


def _render_html_to_pdf_on_worker_thread(html: str) -> bytes:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            return page.pdf(
                format="A4",
                print_background=True,
                margin=PDF_MARGIN,
                display_header_footer=True,
                header_template=PAGE_HEADER_TEMPLATE,
                footer_template=PAGE_FOOTER_TEMPLATE,
            )
        finally:
            browser.close()
