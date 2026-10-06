"""
Architecture Agent Use Case Diagram Renderer.

Purpose:
This file renders PlantUML source into PNG.

Why this file is inside architecture_agent:
- Use case rendering is currently only needed by Architecture Agent.
- We avoid changing shared/common files.
- Later, if multiple agents need diagram rendering, this can be moved to a common service.

Supported rendering methods:
1. plantuml command if installed globally
2. plantuml.jar if PLANTUML_JAR_PATH is configured
"""

import subprocess
from pathlib import Path

from app.core.config import settings


class UseCaseDiagramRenderer:
    """
    Renders PlantUML .puml file into .png.
    """

    def render_png(self, puml_path: Path) -> Path:
        """
        Render PlantUML file into PNG.

        Returns:
            Path to generated PNG file.

        Raises:
            RuntimeError if rendering fails.
        """

        if not puml_path.exists():
            raise RuntimeError(f"PlantUML file does not exist: {puml_path}")

        # First try system-level plantuml command.
        system_command = [
            "plantuml",
            "-tpng",
            str(puml_path)
        ]

        system_result = self._run_command(system_command)

        if system_result["success"]:
            return puml_path.with_suffix(".png")

        # If system command fails, try plantuml.jar.
        if settings.PLANTUML_JAR_PATH:
            jar_command = [
                "java",
                "-jar",
                settings.PLANTUML_JAR_PATH,
                "-tpng",
                str(puml_path)
            ]

            jar_result = self._run_command(jar_command)

            if jar_result["success"]:
                return puml_path.with_suffix(".png")

            raise RuntimeError(
                "PlantUML PNG rendering failed using plantuml.jar. "
                f"Error: {jar_result['error']}"
            )

        raise RuntimeError(
            "PlantUML PNG rendering failed. "
            "Install PlantUML globally or set PLANTUML_JAR_PATH in .env. "
            f"System error: {system_result['error']}"
        )

    def _run_command(self, command: list[str]) -> dict:
        """
        Run a command safely and capture output.

        We use subprocess because PlantUML is an external tool.
        """

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60
            )

            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr
            }

        except Exception as error:
            return {
                "success": False,
                "output": "",
                "error": str(error)
            }