"""
QA Agent internal schemas.

Replaces the earlier aggregate-only shapes (a report that only ever said "3 passed, 1 failed")
with real per-test-case structure: a QaTestCase (what was PLANNED -- name, category, which real
file/function it targets, what inputs/behavior it covers) and a QaTestCaseResult (what actually
happened when it ran -- status, duration, failure message), matched together by name so the
report can show both halves for every test. See agent.py's own module docstring for how
generation and execution produce these.
"""

from pydantic import BaseModel, Field

TEST_CATEGORIES = ("unit", "integration", "regression")


class QAAgentInput(BaseModel):
    feature_id: str


class QaTestCase(BaseModel):
    """One planned test case -- the generation-time half. `test_file` and `method` are filled in
    by the caller (generator.py) after generation, not by the LLM itself."""

    name: str
    category: str = "unit"  # one of TEST_CATEGORIES
    target_file: str = ""
    target_function: str = ""
    inputs: str = ""
    expected_behavior: str = ""
    test_file: str = ""
    method: str = "llm"  # "llm" | "deterministic-fallback"


class QaLLMGenerationResult(BaseModel):
    """The exact JSON shape the LLM is asked to return for one generation call (see prompt.py) --
    parsed via extract_json_object with a graceful fallback on malformed output, the same
    resilience pattern already proven for Security Agent's LLM review layer."""

    test_cases: list[QaTestCase] = Field(default_factory=list)
    test_code: str = ""


class QaTestCaseResult(BaseModel):
    """One test case's real execution outcome, parsed from Jest's --json output. Matched back to
    its QaTestCase by `name` (see agent.py's own matching step) -- Jest's own result has no
    concept of "category"/"inputs"/"expected_behavior", only what actually ran."""

    name: str
    test_file: str = ""
    status: str = "failed"  # "passed" | "failed" -- every test case resolves to one of these two
    # only, never "skipped" (direct user requirement) -- see qa_agent/agent.py's own
    # _finalize_report for how a genuine "couldn't run at all" case is surfaced honestly as a
    # distinct environment_failure signal instead of a third per-test-case status.
    duration_ms: int | None = None
    failure_message: str | None = None
    # LLM-synthesized explanation of a failure (see agent.py's _analyze_failures) -- distinct from
    # failure_message (Jest's own raw assertion/stack-trace text): root_cause explains WHY it
    # actually failed, recommendation says what to change. Both stay None (never block the report)
    # if the analysis call is unreachable/fails, or for a passed test.
    root_cause: str | None = None
    recommendation: str | None = None


class QaRootCauseEntry(BaseModel):
    """One entry in the batched root-cause analysis call's response (see agent.py's
    _analyze_failures / prompt.py's QA_ROOT_CAUSE_PROMPT) -- matched back to its QaTestCaseResult
    by (test_file, name), the same pairing convention already used to match execution results to
    planned test cases."""

    test_file: str = ""
    name: str = ""
    root_cause: str = ""
    recommendation: str = ""


class QaRootCauseAnalysisResult(BaseModel):
    root_causes: list[QaRootCauseEntry] = Field(default_factory=list)


class QAAgentOutput(BaseModel):
    qa_report_json: dict = {}
    status: str = "completed"
    framework_used: str = "jest"
    tests_generated: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    artifact_ids: list[str] = []
    message: str = ""
