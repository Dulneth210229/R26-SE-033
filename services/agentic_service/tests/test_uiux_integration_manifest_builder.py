"""
Golden-file style unit test for UIUXIntegrationManifestBuilder.

No LLM involved -- given a fixed ui_metadata_json, assert the exact manifest
produced. Fully reproducible, per the build plan's testing strategy for
deterministic builders.
"""

from app.agents.uiux_agent.integration_manifest_builder import UIUXIntegrationManifestBuilder

UI_METADATA_JSON = {
    "pages": [
        {
            "page_id": "login-page",
            "name": "Login Page",
            "route": "/login",
            "actors": ["Customer", "Admin"],
            "covers_requirements": ["FR-001", "US-001"],
            "components": [
                {
                    "name": "LoginForm",
                    "reused_from_design_system": False,
                    "covers_ui_expectations": ["Login Form"],
                    "content_elements": ["email field label", "password field label"],
                },
                {
                    "name": "Button",
                    "reused_from_design_system": True,
                    "covers_ui_expectations": [],
                    "content_elements": ["button label"],
                },
            ],
            "states": ["idle", "loading", "error", "success"],
        }
    ],
    "notes": "",
}

EXPECTED_MANIFEST = {
    "pages": [
        {
            "page_id": "login-page",
            "route": "/login",
            "nav_entry": "Login Page",
            "components": [
                {
                    "name": "LoginForm",
                    "reused_from_design_system": False,
                    "content_elements": ["email field label", "password field label"],
                },
                {
                    "name": "Button",
                    "reused_from_design_system": True,
                    "content_elements": ["button label"],
                },
            ],
            "actors": ["Customer", "Admin"],
            "covers_requirements": ["FR-001", "US-001"],
        }
    ]
}


def test_builds_exact_expected_manifest():
    builder = UIUXIntegrationManifestBuilder()
    result = builder.build(UI_METADATA_JSON)
    assert result == EXPECTED_MANIFEST


def test_handles_page_with_no_components():
    builder = UIUXIntegrationManifestBuilder()
    result = builder.build({"pages": [{"page_id": "empty-page", "name": "Empty", "route": "/empty"}]})
    assert result == {
        "pages": [
            {
                "page_id": "empty-page",
                "route": "/empty",
                "nav_entry": "Empty",
                "components": [],
                "actors": [],
                "covers_requirements": [],
            }
        ]
    }


def test_handles_no_pages():
    builder = UIUXIntegrationManifestBuilder()
    assert builder.build({"pages": []}) == {"pages": []}
