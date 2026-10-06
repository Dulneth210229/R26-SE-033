"""
Security Agent internal schemas.

Real shapes, replacing the earlier placeholder that always returned
status="skipped". Mirrors the input convention every other agent already
uses (feature_id resolved to project via the shared store), and keeps a
report-shaped output so this agent still slots into the same
artifact-saving path (artifact_service.save_json_artifact /
save_text_artifact) as every implemented agent before it.
"""

from pydantic import BaseModel, Field


class SecurityAgentInput(BaseModel):
    feature_id: str


class SecurityFinding(BaseModel):
    id: str
    rule_id: str
    layer: str  # "pattern" | "secret" | "dependency" | "llm" | "ai_model_deep_scan"
    severity: str  # raw producer vocabulary -- see severity.py for the display-tier mapping
    cwe: str
    file: str
    line: int | None = None
    message: str
    # Populated by every layer as of this pass -- where in the code the issue occurs and how to
    # fix it, distinct from `message` (what the issue is). None only for a finding shaped before
    # this field existed (never produced going forward).
    root_cause: str | None = None
    recommendation: str | None = None


class SecurityLLMFinding(BaseModel):
    """One finding as returned by the LLM reviewer layer (see prompt.py's requested shape).
    Kept separate from SecurityFinding (the deterministic-scanner shape) since the LLM's own
    field names differ (title/description/recommendation/confidence have no deterministic-scanner
    equivalent) -- _run_llm_review_layer converts an accepted one into a SecurityFinding-shaped
    dict before merging it into the combined findings list."""

    title: str
    description: str = ""
    severity: str = "unknown"
    file: str = "unknown"
    line: int | None = None
    cwe: str | None = None
    root_cause: str = ""
    recommendation: str = ""
    confidence: str = "medium"


class SecurityLLMReviewResult(BaseModel):
    additional_findings: list[SecurityLLMFinding] = Field(default_factory=list)
    notes: str = ""


class SecurityDeepScanFinding(BaseModel):
    """One finding as returned by the AI-model deep-code-read scan layer (deep_scan.py) --
    unlike SecurityLLMFinding, the model producing this was shown REAL source code directly, not
    just a findings summary. Same shape as SecurityLLMFinding by design (both convert into a
    SecurityFinding dict the same way) but kept as its own class so a schema change to one layer's
    prompt contract never silently affects the other's."""

    title: str
    description: str = ""
    severity: str = "unknown"
    file: str = "unknown"
    line: int | None = None
    cwe: str | None = None
    root_cause: str = ""
    recommendation: str = ""
    confidence: str = "medium"


class SecurityDeepScanResult(BaseModel):
    findings: list[SecurityDeepScanFinding] = Field(default_factory=list)


class SecurityAgentOutput(BaseModel):
    security_report_json: dict = {}
    status: str = "completed"
    gate_decision: str = "pass"  # "pass" | "review" | "fail" -- see severity.gate_decision
    findings_count: int = 0
    critical_count: int = 0
    moderate_count: int = 0
    warning_count: int = 0
    artifact_ids: list[str] = []
    message: str = ""
    scan_type: str = "standard"  # "standard" | "ai_model_deep_scan"
