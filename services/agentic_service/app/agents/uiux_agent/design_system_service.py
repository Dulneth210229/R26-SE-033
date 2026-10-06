"""
UI/UX Agent design system access.

Thin, UI/UX-Agent-specific wrapper around ProjectMemoryService. Kept separate
from ProjectMemoryService itself because ProjectMemoryService is a generic
cross-agent store (also used by the Coder Agent's project_manifest.json),
while this module encodes UI/UX-specific defaults and will grow merge logic
(new tokens/components discovered this run) once component_generator.py and
the post-approval persistence step are added in the next milestone.
"""

from app.services.project_memory_service import project_memory_service


class UIUXDesignSystemService:
    """
    Loads the project's design system for use as prompt context.
    """

    def load(self, project_id: str) -> dict:
        """
        Load the project's design system, or a fresh default if this is the
        project's first feature.
        """
        return project_memory_service.load_design_system(project_id)


uiux_design_system_service = UIUXDesignSystemService()
