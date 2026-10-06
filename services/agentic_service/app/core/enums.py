"""
Shared enum values used across the backend.

Using enums helps us avoid spelling mistakes like:
- "approved"
- "approve"
- "Approval"

All statuses are controlled from one place.
"""

from enum import Enum


class FeatureStatus(str, Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentName(str, Enum):
    REQUIREMENT = "requirement_agent"
    DOMAIN = "domain_agent"
    ARCHITECTURE = "architecture_agent"
    UIUX = "uiux_agent"
    CODER = "coder_agent"
    SECURITY = "security_agent"
    QA = "qa_agent"


class ArtifactType(str, Enum):
    SRS = "srs"
    ENHANCED_SRS = "enhanced_srs"
    DOMAIN_IMPROVEMENTS = "domain_improvements"

    # Architecture Agent artifacts
    ARCHITECTURE_PLAN = "architecture_plan"
    SDS = "sds"
    USE_CASE_DIAGRAM = "use_case_diagram"
    SEQUENCE_DIAGRAM = "sequence_diagram"
    CLASS_DIAGRAM = "class_diagram"
    ARCHITECTURE_TRACEABILITY = "architecture_traceability"

    # UI/UX Agent artifacts
    UI_METADATA = "ui_metadata"
    UI_INTEGRATION_MANIFEST = "ui_integration_manifest"
    UI_COMPONENT_CODE = "ui_component_code"
    UI_PAGE_HTML = "ui_page_html"
    UI_PREVIEW_SCREENSHOT = "ui_preview_screenshot"
    DESIGN_SYSTEM = "design_system"

    # Coder Agent artifacts
    CODE_PLAN = "code_plan"
    CODE_DIFF = "code_diff"
    CODE_MANIFEST = "code_manifest"
    REQUIREMENT_CODE_MAP = "requirement_code_map"
    SETUP_INSTRUCTIONS = "setup_instructions"
    PROJECT_MANIFEST = "project_manifest"

    # Security / QA Agent artifacts (placeholders for now)
    SECURITY_REPORT = "security_report"
    QA_REPORT = "qa_report"

    UI_DESIGN = "ui_design"
    CODE = "code"


class ArtifactFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"
    TEXT = "text"
    HTML = "html"
    PNG = "png"
    CODE = "code"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"

class ArchitectureStyle(str, Enum):
    """
    Preferred architecture style selected by the user or BA.

    Important:
    In Requirement Agent, this is only captured as a requirement/design preference.
    The actual Software Design Specification will be generated later by Architecture Agent.
    """

    MODULAR = "modular"
    MONOLITHIC = "monolithic"
    MVC = "mvc"
    MICROSERVICES = "microservices"
    LAYERED = "layered"
    CLEAN_ARCHITECTURE = "clean_architecture"