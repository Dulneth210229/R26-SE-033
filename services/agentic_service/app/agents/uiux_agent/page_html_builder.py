"""
UI/UX Agent page HTML builder.

Purpose:
Deterministically assemble a page's already-generated component HTML fragments into one full,
self-contained <!DOCTYPE html> document -- no LLM call, pure string concatenation, so this step
can never fail or hallucinate. This is what guarantees every page always renders something
complete (the fix for a real, confirmed "empty UI" bug -- see component_generator.py's module
docstring for the root cause this design eliminates: React/JSX needed per-component state-
branching logic to decide what to render, and an unhandled branch fell into generic placeholder
text; static HTML has no branches to fall into in the first place).

Self-contained: the vendored Tailwind Play-CDN script
(app/agents/uiux_agent/vendor/tailwindcss.js) is inlined directly into the document's <head> (not
referenced via <script src>), so the resulting artifact needs no network access or backend to
render correctly -- it can be opened standalone, downloaded, or dropped straight into an
<iframe srcDoc>. Confirmed by direct inspection: this is a self-scanning Play-CDN IIFE bundle (no
companion <script type="text/tailwindcss"> block needed) that behaves identically whether loaded
via `src=` or executed inline.

Real, confirmed bug this template also guards against: an `<iframe srcDoc>` resolves a document's
*relative* URLs (including a plain `href="#"` -- exactly the convention
HTML_COMPONENT_GENERATOR_SYSTEM_PROMPT already asks for on decorative links) against the
*embedding parent page's own URL*, not against the srcdoc content itself. Clicking such a link
inside the preview iframe therefore navigates the iframe to the host app's own URL, rendering the
entire host app nested inside the preview pane -- confirmed directly against a real generated
page (its Pagination "Next"/"Previous" links use exactly `href="#"`). The inline click-prevention
script below (`_CLICK_GUARD_SCRIPT`) makes every link in every assembled page permanently inert
regardless of its href value, present or future -- the deterministic fix for the whole bug class,
not just this one link.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

VENDOR_DIR = Path(__file__).parent / "vendor"
TAILWIND_VENDOR_FILE = "tailwindcss.js"

# Makes every link in the assembled page permanently inert -- see the module docstring for the
# real iframe[srcdoc] navigation bug this prevents. Capture-phase so it runs before any other
# handler; closest("a") so it also catches a click on an element nested inside a link (e.g. an
# icon or span). Deliberately unconditional: this is a static visual reference, never working
# navigation, regardless of what href value any given link happens to carry.
_CLICK_GUARD_SCRIPT = """<script>
document.addEventListener("click", function (event) {
  if (event.target && event.target.closest && event.target.closest("a")) {
    event.preventDefault();
  }
}, true);
</script>"""

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script>
{tailwind_js}
</script>
</head>
<body class="min-h-screen bg-gray-50 text-gray-900">
<main class="max-w-6xl mx-auto p-6 space-y-6">
{fragments}
</main>
{click_guard_script}
</body>
</html>
"""


class PageHtmlBuildError(RuntimeError):
    """Raised only if a required vendored asset is missing -- never for content reasons (this
    builder is pure string concatenation otherwise, and cannot fail on its input)."""


class UIUXPageHtmlBuilder:
    """
    Assembles a page's ordered component fragments into one full, self-contained HTML document.
    """

    def build(self, page_metadata: dict[str, Any], component_fragments: list[str]) -> str:
        """
        component_fragments: the HTML fragments for this page's components, already in the order
        they should appear -- the same order ui_metadata_json.pages[].components already lists
        them in (the same order the previous JSX-mounting pipeline used).
        """

        title = page_metadata.get("name") or page_metadata.get("page_id") or "Page"
        fragments_html = "\n".join(
            fragment.strip() for fragment in component_fragments if fragment and fragment.strip()
        )

        return _PAGE_TEMPLATE.format(
            title=title,
            tailwind_js=self._read_tailwind_js(),
            fragments=fragments_html,
            click_guard_script=_CLICK_GUARD_SCRIPT,
        )

    def _read_tailwind_js(self) -> str:
        path = VENDOR_DIR / TAILWIND_VENDOR_FILE

        if not path.exists():
            raise PageHtmlBuildError(f"Vendored Tailwind asset not found: {path}")

        content = path.read_text(encoding="utf-8")
        # Defensive escape in case a future vendor-file update ever introduces a literal
        # "</script" substring (e.g. inside a string constant) -- would otherwise prematurely
        # close this inline <script> tag. Confirmed the current vendored file has no such
        # substring, but this makes that safe regardless of future updates, at zero behavioral
        # cost (the browser's JS parser treats "<\/script" identically to "</script").
        return content.replace("</script", "<\\/script")


uiux_page_html_builder = UIUXPageHtmlBuilder()
