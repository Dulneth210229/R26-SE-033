"""
PlantUML rendering service.

This service converts PlantUML source files into PNG diagrams.

Architecture Agent creates:
- usecase_v1.puml

PlantUML service renders:
- usecase_v1.png

Required:
- Java installed
- plantuml.jar available
- Graphviz installed and available in PATH

Example manual command:
    java -jar tools/plantuml.jar outputs/.../usecase_v1.puml
"""

import subprocess
from pathlib import Path

from app.core.config import settings


class PlantUMLService:
    """
    Service responsible for rendering PlantUML diagrams.
    """

    def render_puml_to_png(self, puml_file_path: str) -> str:
        """
        Render a .puml file into a .png file.

        Args:
            puml_file_path:
                Path to the PlantUML source file.

        Returns:
            Path to the generated PNG file.

        Raises:
            RuntimeError:
                If PlantUML rendering fails.
        """
        puml_path = Path(puml_file_path)

        if not puml_path.exists():
            raise RuntimeError(f"PlantUML file not found: {puml_file_path}")

        plantuml_jar = Path(settings.PLANTUML_JAR_PATH)

        if not plantuml_jar.exists():
            raise RuntimeError(
                f"PlantUML jar not found at: {settings.PLANTUML_JAR_PATH}. "
                "Download plantuml.jar and place it inside tools/plantuml.jar."
            )

        command = [
            "java",
            "-jar",
            str(plantuml_jar),
            "-tpng",
            str(puml_path)
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(
                "PlantUML rendering failed.\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )

        png_path = puml_path.with_suffix(".png")

        if not png_path.exists():
            raise RuntimeError(
                f"PlantUML command completed, but PNG was not created: {png_path}"
            )

        return str(png_path)


plantuml_service = PlantUMLService()