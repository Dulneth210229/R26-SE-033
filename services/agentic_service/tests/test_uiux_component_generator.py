"""
Unit tests for UIUXComponentGenerator's deterministic pieces -- no LLM involved: the
delimited-format parser (_parse) and the content-quality gate (detect_placeholder_content).

detect_placeholder_content is the concrete fix for a real, confirmed bug (Sample E-commerce /
Item Listing feature): a generated preview rendered nothing but "Unknown state."/"No data
available" because the LLM-authored JSX only handled some of the declared render states. This
gate is what UIUXAgent._generate_component_with_quality_gate checks before ever accepting a
fragment as done -- these tests lock in exactly what it does and does not flag.
"""

import pytest

from app.agents.uiux_agent.component_generator import (
    HTML_CODE_MARKER,
    UIUXComponentGenerator,
)


@pytest.fixture
def generator():
    return UIUXComponentGenerator()


def test_parse_extracts_fenced_html_block(generator):
    text = f"""{HTML_CODE_MARKER}
```html
<section class="p-4"><p>Real content</p></section>
```"""
    result = generator._parse(text)
    assert result == {"html_code": '<section class="p-4"><p>Real content</p></section>'}


def test_parse_extracts_unfenced_html(generator):
    text = f'{HTML_CODE_MARKER}\n<div class="p-2">No fence here</div>'
    result = generator._parse(text)
    assert result["html_code"] == '<div class="p-2">No fence here</div>'


def test_parse_missing_marker_raises(generator):
    with pytest.raises(ValueError, match=HTML_CODE_MARKER):
        generator._parse("<div>no marker at all</div>")


def test_parse_empty_html_section_raises(generator):
    with pytest.raises(ValueError, match="must not be empty"):
        generator._parse(f"{HTML_CODE_MARKER}\n```html\n```")


def test_detect_placeholder_content_flags_empty(generator):
    assert generator.detect_placeholder_content("") == "The fragment is empty."
    assert generator.detect_placeholder_content("   \n  ") == "The fragment is empty."


def test_detect_placeholder_content_flags_known_bad_phrases(generator):
    # These are the EXACT real phrases confirmed present in the real broken artifacts.
    violation_no_data = generator.detect_placeholder_content('<p class="text-lg">No data available</p>')
    violation_unknown_state = generator.detect_placeholder_content('<div class="p-10"><p>Unknown state.</p></div>')

    assert violation_no_data is not None
    assert "no data available" in violation_no_data.lower()
    assert violation_unknown_state is not None
    assert "unknown state" in violation_unknown_state.lower()


def test_detect_placeholder_content_flags_lorem_ipsum(generator):
    assert generator.detect_placeholder_content("<p>Lorem ipsum dolor sit amet</p>") is not None


def test_detect_placeholder_content_allows_real_content(generator):
    real_fragment = """
    <table class="w-full border-collapse">
      <thead><tr><th>Name</th><th>Price</th></tr></thead>
      <tbody>
        <tr><td>Wireless Mouse</td><td>$24.99</td></tr>
        <tr><td>Mechanical Keyboard</td><td>$89.00</td></tr>
      </tbody>
    </table>
    """
    assert generator.detect_placeholder_content(real_fragment) is None


def test_detect_placeholder_content_allows_legitimate_html_placeholder_attribute(generator):
    """
    Real, confirmed false-positive bug: a genuine <input placeholder="..."> attribute (exactly
    what a real search/filter component needs) previously matched the bare "placeholder" phrase
    because the check searched the whole raw HTML string, not just visible text -- crashing a
    real run for a component named "SearchFilterBar" after exhausting every repair attempt.
    """
    search_bar = """
    <section class="bg-white p-4 rounded-lg shadow-sm flex gap-3">
      <input type="text" placeholder="Search items by name..." class="border rounded px-3 py-2 flex-1">
      <select class="border rounded px-3 py-2">
        <option>All Categories</option>
        <option>Electronics</option>
      </select>
    </section>
    """
    assert generator.detect_placeholder_content(search_bar) is None


def test_detect_placeholder_content_still_flags_placeholder_as_visible_text(generator):
    """The gate must still catch a genuine "placeholder" phrase when it's real, rendered text
    content (not an HTML attribute) -- the fix narrows what's checked, not what's caught."""
    violation = generator.detect_placeholder_content("<p>This is a placeholder message.</p>")
    assert violation is not None
    assert "placeholder" in violation.lower()
