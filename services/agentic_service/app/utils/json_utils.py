# """
# JSON utility helpers.

# This file helps extract valid JSON from LLM responses.

# LLMs may return:
# 1. Raw JSON
# 2. JSON inside markdown code blocks
# 3. JSON mixed with normal explanation text

# Architecture Agent uses this function to parse the LLM output.
# """

# import json
# import re
# from typing import Any


# def extract_json_from_text(text: str) -> dict[str, Any]:
#     """
#     Extract the first valid JSON object from text.

#     Args:
#         text: Raw text returned by the LLM.

#     Returns:
#         Parsed JSON as a Python dictionary.

#     Raises:
#         ValueError: If no valid JSON object is found.
#     """

#     # 1. Try direct JSON parsing first.
#     try:
#         return json.loads(text)
#     except json.JSONDecodeError:
#         pass

#     # 2. Try JSON inside markdown code block.
#     code_block_match = re.search(
#         r"```(?:json)?\s*(\{.*?\})\s*```",
#         text,
#         re.DOTALL
#     )

#     if code_block_match:
#         possible_json = code_block_match.group(1)

#         try:
#             return json.loads(possible_json)
#         except json.JSONDecodeError:
#             pass

#     # 3. Try to find any JSON-looking object in the text.
#     object_match = re.search(r"(\{.*\})", text, re.DOTALL)

#     if object_match:
#         possible_json = object_match.group(1)

#         try:
#             return json.loads(possible_json)
#         except json.JSONDecodeError:
#             pass

#     # 4. If nothing works, raise a clear error.
#     raise ValueError("No valid JSON object found in LLM response.")
"""
JSON utility functions.

LLMs do not always return perfect JSON.

Sometimes they return:
- pure JSON
- JSON inside markdown code fences
- explanation text before or after JSON

This file provides reusable helper functions for extracting JSON safely.

Important:
Some agents may import extract_json_object().
Other agents may import extract_json_from_text().
To avoid import errors, we support both names.
"""

import json
import re
from typing import Any


def remove_markdown_code_fences(text: str) -> str:
    """
    Remove markdown code fences from LLM output.

    Example:
        ```json
        {"hello": "world"}
        ```

    becomes:
        {"hello": "world"}

    This helps when an LLM wraps JSON inside markdown.
    """
    cleaned = text.strip()

    # Remove opening ```json or ```
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)

    # Remove ending ```
    cleaned = re.sub(r"\s*```$", "", cleaned)

    return cleaned.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """
    Extract the first valid JSON object from text.

    This function is useful when the LLM returns output like:

        Here is the JSON:
        {
          "key": "value"
        }

    Returns:
        Parsed JSON dictionary.

    Raises:
        ValueError if no valid JSON object can be found.
    """
    cleaned = remove_markdown_code_fences(text)

    # First try direct JSON parsing.
    try:
        parsed = json.loads(cleaned)

        if isinstance(parsed, dict):
            return parsed

        raise ValueError("Parsed JSON is not an object.")

    except json.JSONDecodeError:
        pass

    # If direct parsing fails, try to extract content between first { and last }.
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response.")

    possible_json = cleaned[start:end + 1]

    try:
        parsed = json.loads(possible_json)

        if not isinstance(parsed, dict):
            raise ValueError("Extracted JSON is not an object.")

        return parsed

    except json.JSONDecodeError as error:
        raise ValueError(
            f"Failed to parse JSON from LLM response: {error}"
        ) from error


def extract_json_from_text(text: str) -> dict[str, Any]:
    """
    Compatibility wrapper.

    Some existing files, such as architecture_agent/parser.py,
    may import this function name:

        extract_json_from_text

    Our Requirement Agent used:

        extract_json_object

    To support both agents, this function simply calls extract_json_object().
    """
    return extract_json_object(text)


def ensure_keys_exist(data: dict[str, Any], required_keys: list[str]) -> None:
    """
    Validate that required keys exist in a dictionary.

    Example:
        ensure_keys_exist(data, ["srs_markdown", "srs_json"])

    Raises:
        ValueError if any key is missing.
    """
    missing_keys = [key for key in required_keys if key not in data]

    if missing_keys:
        raise ValueError(f"Missing required keys in JSON output: {missing_keys}")


def to_pretty_json(data: dict[str, Any]) -> str:
    """
    Convert dictionary to readable JSON string.

    This is useful for debugging or saving clean JSON text.
    """
    return json.dumps(data, indent=2, ensure_ascii=False)