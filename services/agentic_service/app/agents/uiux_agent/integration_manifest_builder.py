"""
UI/UX Agent integration manifest builder.

Purpose:
Build a deterministic manifest describing how each generated page/component
should be wired into the persistent frontend app -- route path, nav entry,
component names, real content each one displays. This is consumed by the
Coder Agent as VISUAL REFERENCE context (alongside the HTML fragments/pages
themselves, via read_ui_component_design/read_ui_page_design), not by the
human reviewer.

Why deterministic (no LLM):
Everything needed is already present in ui_metadata_json. The UI/UX Agent
never touches App.jsx/router itself (see build plan section 4.4) -- it only
describes what the Coder Agent should wire up.
"""

from __future__ import annotations

from typing import Any


class UIUXIntegrationManifestBuilder:
    """
    Builds integration_manifest_json from ui_metadata_json.
    """

    def build(self, ui_metadata_json: dict[str, Any]) -> dict[str, Any]:
        pages = []

        for page in ui_metadata_json.get("pages", []):
            components = page.get("components", []) or []

            pages.append(
                {
                    "page_id": page.get("page_id"),
                    "route": page.get("route"),
                    "nav_entry": page.get("name"),
                    "components": [
                        {
                            "name": component.get("name"),
                            "reused_from_design_system": component.get(
                                "reused_from_design_system", False
                            ),
                            "content_elements": component.get("content_elements") or [],
                        }
                        for component in components
                    ],
                    "actors": page.get("actors", []),
                    "covers_requirements": page.get("covers_requirements", []),
                }
            )

        return {"pages": pages}


uiux_integration_manifest_builder = UIUXIntegrationManifestBuilder()
