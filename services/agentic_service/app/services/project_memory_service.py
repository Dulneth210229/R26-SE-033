"""
Project memory service.

This service is responsible for:
- Loading and saving the project-level design system (owned by UI/UX Agent).
- Loading and updating the project-level project manifest (owned by Coder Agent).

Why this exists:
Artifacts today are feature-scoped (outputs/{project}/feature-{name}/...). Both the
UI/UX Agent and the Coder Agent need something that persists across features within
the same project, or every feature reinvents colors, components, routes, and models
from zero. These two JSON documents are that cross-feature memory.

Both files are stored as plain JSON at:
    outputs/{project_slug}/_project/design_system.json
    outputs/{project_slug}/_project/project_manifest.json

They are read (never blindly overwritten) at the start of a feature run, and updated
only after human approval of that feature's output.
"""

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.in_memory_store import store
from app.utils.file_manager import ensure_directory, read_json_file, write_json_file
from app.utils.slugify import slugify

DEFAULT_DESIGN_SYSTEM: dict[str, Any] = {
    "colors": {},
    "typography": {},
    "spacing": {},
    "components": {},
}

DEFAULT_PROJECT_MANIFEST: dict[str, Any] = {
    "routes": [],
    "api_endpoints": [],
    "models": [],
    "shared_components": [],
    "features": {},
}


class ProjectMemoryService:
    """
    Handles project-level, cross-feature memory documents.
    """

    def _project_slug(self, project_id: str) -> str:
        project = store.projects.get(project_id)

        if not project:
            raise ValueError(f"Project not found: {project_id}")

        return slugify(project.get("project_name") or project_id)

    def _project_root(self, project_id: str) -> Path:
        return Path(settings.OUTPUT_DIR) / self._project_slug(project_id) / "_project"

    def _design_system_path(self, project_id: str) -> Path:
        return self._project_root(project_id) / "design_system.json"

    def _project_manifest_path(self, project_id: str) -> Path:
        return self._project_root(project_id) / "project_manifest.json"

    def load_design_system(self, project_id: str) -> dict[str, Any]:
        """
        Load the project's design system, or return a fresh default if this is the
        project's first feature.
        """
        path = self._design_system_path(project_id)

        if not path.exists():
            return dict(DEFAULT_DESIGN_SYSTEM)

        return read_json_file(path)

    def save_design_system(self, project_id: str, data: dict[str, Any]) -> str:
        """
        Persist the project's design system.
        """
        path = self._design_system_path(project_id)
        ensure_directory(path.parent)
        return write_json_file(path, data)

    def load_project_manifest(self, project_id: str) -> dict[str, Any]:
        """
        Load the project's manifest (routes/endpoints/models/components/features already
        built), or return a fresh default if this is the project's first feature.
        """
        path = self._project_manifest_path(project_id)

        if not path.exists():
            return dict(DEFAULT_PROJECT_MANIFEST)

        return read_json_file(path)

    def update_project_manifest(self, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """
        Merge `patch` into the existing project manifest and persist it.

        List-valued fields (routes, api_endpoints, models, shared_components) are
        concatenated; the `features` map is updated key by key; anything else is
        overwritten by the patch value.
        """
        manifest = self.load_project_manifest(project_id)

        for key, value in patch.items():
            if key == "features" and isinstance(value, dict):
                manifest.setdefault("features", {}).update(value)
            elif isinstance(value, list) and isinstance(manifest.get(key), list):
                manifest[key].extend(item for item in value if item not in manifest[key])
            else:
                manifest[key] = value

        path = self._project_manifest_path(project_id)
        ensure_directory(path.parent)
        write_json_file(path, manifest)

        return manifest


project_memory_service = ProjectMemoryService()
