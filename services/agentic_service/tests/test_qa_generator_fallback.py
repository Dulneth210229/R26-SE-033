"""
Unit tests for generator.py -- the "ask nicely -> decide deterministically" LLM generation ladder
(_invoke_llm's malformed/well-formed/unreachable-provider handling), the marker-based two-part
response parser (_parse_generation_response -- JSON test_cases metadata, then the literal
TEST_CODE_MARKER, then the real test code; see prompt.py's own docstring for why this replaced
embedding test_code as an escaped JSON string), and the deterministic unit fallback template
(_deterministic_unit_fallback), which must still produce real, correct Jest test code when no LLM
is reachable at all. No real LLM/network calls -- llm_provider_service is mocked at its import
site inside generator._invoke_llm.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.qa_agent import generator
from app.agents.qa_agent.prompt import TEST_CODE_MARKER
from app.agents.qa_agent.schemas import QaLLMGenerationResult


def _mock_provider(raw_output: str):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=raw_output)
    return provider


def _two_part_response(test_cases_json: str, code: str, *, fence: bool = False) -> str:
    code_block = f"```typescript\n{code}\n```" if fence else code
    return f"{test_cases_json}\n{TEST_CODE_MARKER}\n{code_block}"


@pytest.mark.asyncio
async def test_invoke_llm_returns_none_on_malformed_json():
    provider = _mock_provider("this is not json at all")
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert result is None


@pytest.mark.asyncio
async def test_invoke_llm_returns_none_when_marker_is_missing():
    raw = '{"test_cases": [{"name": "a test"}]}'
    provider = _mock_provider(raw)
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert result is None


@pytest.mark.asyncio
async def test_invoke_llm_returns_none_when_test_code_is_empty():
    raw = _two_part_response('{"test_cases": [{"name": "a test"}]}', "")
    provider = _mock_provider(raw)
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert result is None


@pytest.mark.asyncio
async def test_invoke_llm_returns_none_when_test_cases_is_empty():
    raw = _two_part_response('{"test_cases": []}', 'test("x", () => {});')
    provider = _mock_provider(raw)
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert result is None


@pytest.mark.asyncio
async def test_invoke_llm_returns_none_when_provider_unreachable():
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=ConnectionError("no route to host"))
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert result is None


@pytest.mark.asyncio
async def test_invoke_llm_returns_parsed_result_on_well_formed_response():
    raw = _two_part_response(
        '{"test_cases": [{"name": "getItem returns an item", "category": "unit", '
        '"target_file": "lib/api/item.ts", "target_function": "getItem"}]}',
        'test("getItem returns an item", () => {});',
    )
    provider = _mock_provider(raw)
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert isinstance(result, QaLLMGenerationResult)
    assert result.test_cases[0].name == "getItem returns an item"
    assert "getItem returns an item" in result.test_code


@pytest.mark.asyncio
async def test_invoke_llm_extracts_json_from_markdown_fenced_metadata():
    raw = _two_part_response(
        '```json\n{"test_cases": [{"name": "a test"}]}\n```',
        'test("a test", () => {});',
    )
    provider = _mock_provider(raw)
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert result is not None
    assert result.test_cases[0].name == "a test"


@pytest.mark.asyncio
async def test_invoke_llm_strips_a_fenced_code_block_around_the_test_code():
    raw = _two_part_response(
        '{"test_cases": [{"name": "a test"}]}', 'test("a test", () => {});', fence=True,
    )
    provider = _mock_provider(raw)
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert result is not None
    assert result.test_code == 'test("a test", () => {});'
    assert "```" not in result.test_code


@pytest.mark.asyncio
async def test_invoke_llm_handles_real_multiline_code_with_quotes_and_backslashes_with_no_escaping():
    # The exact class of input that broke the old embed-test_code-as-a-JSON-string approach --
    # real, unescaped newlines/quotes/backslashes in the code, which the marker-split approach
    # never needs to escape at all.
    real_code = (
        'import Item from "@/models/Item";\n\n'
        'test("regex matches digits", () => {\n'
        '  const pattern = /\\d+/;\n'
        '  expect(pattern.test("abc123")).toBe(true);\n'
        '});\n'
    )
    raw = _two_part_response('{"test_cases": [{"name": "regex matches digits"}]}', real_code)
    provider = _mock_provider(raw)
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._invoke_llm("system", "user")

    assert result is not None
    assert result.test_code == real_code.strip()


def test_deterministic_unit_fallback_handles_array_literal_export():
    target = {
        "rel": "lib/seedData.ts",
        "source": "export const SEED_ITEMS = [\n  { id: 1, name: 'a' },\n];\n",
    }

    result = generator._deterministic_unit_fallback(target)

    assert result is not None
    assert len(result.test_cases) == 1
    tc = result.test_cases[0]
    assert tc.target_function == "SEED_ITEMS"
    assert tc.method == "deterministic-fallback"
    assert tc.category == "unit"
    assert "SEED_ITEMS" in result.test_code
    assert 'from "../lib/seedData"' in result.test_code


def test_deterministic_unit_fallback_handles_guarded_async_null_export():
    target = {
        "rel": "lib/mongodb.ts",
        "source": (
            "export async function connectToDatabase() {\n"
            "  if (!process.env.MONGODB_URI) {\n"
            "    return null;\n"
            "  }\n"
            "}\n"
        ),
    }

    result = generator._deterministic_unit_fallback(target)

    assert result is not None
    tc = result.test_cases[0]
    assert tc.target_function == "connectToDatabase"
    assert tc.method == "deterministic-fallback"
    assert "await connectToDatabase()" in result.test_code


def test_deterministic_unit_fallback_returns_none_for_unrecognized_shape():
    target = {
        "rel": "lib/utils.ts",
        "source": "export function add(a: number, b: number): number { return a + b; }\n",
    }

    result = generator._deterministic_unit_fallback(target)

    assert result is None


def test_deterministic_unit_fallback_handles_both_shapes_in_one_file():
    target = {
        "rel": "lib/data.ts",
        "source": (
            "export const ITEMS = [{ id: 1 }];\n\n"
            "export async function getConfig() {\n  if (!process.env.X) {\n    return null;\n  }\n}\n"
        ),
    }

    result = generator._deterministic_unit_fallback(target)

    assert result is not None
    assert len(result.test_cases) == 2
    names = {tc.target_function for tc in result.test_cases}
    assert names == {"ITEMS", "getConfig"}


@pytest.mark.asyncio
async def test_generate_unit_tests_falls_back_to_deterministic_when_llm_unreachable():
    target = {
        "rel": "lib/seedData.ts",
        "exports": ["SEED_ITEMS"],
        "source": "export const SEED_ITEMS = [\n  { id: 1 },\n];\n",
    }
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=TimeoutError())
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator.generate_unit_tests(target)

    assert result is not None
    assert result.test_cases[0].method == "deterministic-fallback"


@pytest.mark.asyncio
async def test_generate_unit_tests_returns_none_when_llm_fails_and_no_fallback_shape():
    target = {
        "rel": "lib/utils.ts",
        "exports": ["add"],
        "source": "export function add(a: number, b: number): number { return a + b; }\n",
    }
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=TimeoutError())
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator.generate_unit_tests(target)

    assert result is None


@pytest.mark.asyncio
async def test_generate_regression_tests_returns_none_when_no_acceptance_criteria():
    result = await generator.generate_regression_tests([], None)

    assert result is None


def test_scan_for_forbidden_jest_constructs_detects_each_construct():
    assert generator.scan_for_forbidden_jest_constructs('test.skip("x", () => {});') == ["test.skip(...)"]
    assert generator.scan_for_forbidden_jest_constructs('it.todo("x");') == ["it.todo(...)"]
    assert generator.scan_for_forbidden_jest_constructs('test.each([1, 2])("x", () => {});') == ["test.each(...)"]


def test_scan_for_forbidden_jest_constructs_returns_empty_for_clean_code():
    assert generator.scan_for_forbidden_jest_constructs('test("x", () => { expect(1).toBe(1); });') == []


@pytest.mark.asyncio
async def test_generate_with_retries_succeeds_on_a_later_attempt_after_an_empty_response():
    provider = MagicMock()
    ok_raw = _two_part_response('{"test_cases": [{"name": "a test"}]}', 'test("a test", () => {});')
    provider.invoke_agent = AsyncMock(side_effect=["not json at all", ok_raw])
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._generate_with_retries("system", "user", max_attempts=3)

    assert result is not None
    assert result.test_cases[0].name == "a test"
    assert provider.invoke_agent.await_count == 2


@pytest.mark.asyncio
async def test_generate_with_retries_retries_when_forbidden_construct_is_used():
    provider = MagicMock()
    forbidden_raw = _two_part_response('{"test_cases": [{"name": "a"}]}', 'test.skip("a", () => {});')
    ok_raw = _two_part_response('{"test_cases": [{"name": "a"}]}', 'test("a", () => {});')
    provider.invoke_agent = AsyncMock(side_effect=[forbidden_raw, ok_raw])
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._generate_with_retries("system", "user", max_attempts=3)

    assert result is not None
    assert "test.skip" not in result.test_code
    assert provider.invoke_agent.await_count == 2


@pytest.mark.asyncio
async def test_generate_with_retries_returns_none_after_exhausting_every_attempt():
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=TimeoutError())
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator._generate_with_retries("system", "user", max_attempts=2)

    assert result is None
    assert provider.invoke_agent.await_count == 2


def test_deterministic_integration_fallback_asserts_response_instanceof_response_never_status_code():
    target = {
        "route_rel": "app/api/items/route.ts",
        "route_source": "export async function GET() { return Response.json([]); }\n"
                         "export async function POST(request) { return Response.json({}); }",
    }

    result = generator._deterministic_integration_fallback(target)

    assert result is not None
    assert {tc.target_function for tc in result.test_cases} == {"GET", "POST"}
    assert "expect(response).toBeInstanceOf(Response)" in result.test_code
    assert 'body: "{}"' in result.test_code  # POST gets a body


def test_deterministic_integration_fallback_returns_none_when_no_http_methods_exported():
    target = {"route_rel": "lib/helpers.ts", "route_source": "export function notAMethod() {}"}

    assert generator._deterministic_integration_fallback(target) is None


def test_deterministic_regression_fallback_names_the_acceptance_criteria_it_stands_in_for():
    route_target = {
        "route_rel": "app/api/items/route.ts",
        "route_source": "export async function GET() { return Response.json([]); }",
    }
    acceptance_criteria = [{"id": "AC-001", "description": "Items list loads."}]

    result = generator._deterministic_regression_fallback(acceptance_criteria, route_target)

    assert result is not None
    tc = result.test_cases[0]
    assert tc.category == "regression"
    assert "AC-001" in tc.expected_behavior


def test_deterministic_regression_fallback_returns_none_without_a_route_target():
    assert generator._deterministic_regression_fallback([{"id": "AC-001"}], None) is None


@pytest.mark.asyncio
async def test_generate_integration_tests_falls_back_to_deterministic_smoke_test_on_llm_failure():
    target = {
        "route_rel": "app/api/items/route.ts",
        "route_source": "export async function GET() { return Response.json([]); }",
        "related_files": [],
    }
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=TimeoutError())
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator.generate_integration_tests(target)

    assert result is not None
    assert result.test_cases[0].method == "deterministic-fallback"
    assert result.test_cases[0].category == "integration"


@pytest.mark.asyncio
async def test_generate_integration_tests_returns_none_when_llm_fails_and_no_http_methods_exported():
    target = {
        "route_rel": "lib/helpers.ts",
        "route_source": "export function notAnHttpMethod() { return true; }",
        "related_files": [],
    }
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=TimeoutError())
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator.generate_integration_tests(target)

    assert result is None
