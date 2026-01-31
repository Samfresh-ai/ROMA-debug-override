"""Gemini Fixer Logic for ROMA Debug.

Returns structured JSON responses for machine-readable fixes.
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import types

from roma_debug.config import GEMINI_API_KEY
from roma_debug.prompts import SYSTEM_PROMPT


# Model priority: try Lite first (higher quota), then Flash
PRIMARY_MODEL = "gemini-2.5-flash-lite"
FALLBACK_MODEL = "gemini-2.5-flash"

# Placeholder paths that indicate the AI couldn't determine the real path
INVALID_PATHS = {
    "unknown",
    "path/to/file.py",
    "path/to/your/code.py",
    "path/to/your/file.py",
    "example.py",
    "your_file.py",
    "file.py",
    "",
}


@dataclass
class FixResult:
    """Structured result from the AI engine."""
    filepath: Optional[str]  # None for general system errors
    full_code_block: str
    explanation: str
    raw_response: str
    model_used: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "filepath": self.filepath,
            "full_code_block": self.full_code_block,
            "explanation": self.explanation,
        }


def _get_client() -> genai.Client:
    """Get configured Gemini client."""
    return genai.Client(api_key=GEMINI_API_KEY)


def _normalize_filepath(filepath: Optional[str]) -> Optional[str]:
    """Normalize filepath, returning None for invalid/placeholder paths.

    Args:
        filepath: Raw filepath from AI response

    Returns:
        Validated filepath or None if invalid
    """
    if filepath is None:
        return None

    # Convert to string and strip whitespace
    filepath = str(filepath).strip()

    # Check against known invalid placeholders
    if filepath.lower() in INVALID_PATHS:
        return None

    # Check for placeholder patterns
    placeholder_patterns = [
        r"^path/to/",
        r"^your[_-]",
        r"^example[_-]?",
        r"<.*>",  # <filename> style placeholders
    ]
    for pattern in placeholder_patterns:
        if re.match(pattern, filepath, re.IGNORECASE):
            return None

    return filepath


def _parse_json_response(text: str) -> dict:
    """Parse JSON from response, handling markdown code blocks.

    Args:
        text: Raw response text

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If JSON parsing fails
    """
    # Try direct JSON parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in text
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from response: {text[:200]}...")


def analyze_error(log: str, context: str, max_retries: int = 3) -> FixResult:
    """Analyze an error log and return a structured code fix.

    Args:
        log: The error log or traceback
        context: Source code context around the error
        max_retries: Number of retries for rate limit errors

    Returns:
        FixResult with structured fix data (filepath may be None for general errors)

    Raises:
        Exception: If Gemini API call fails after retries
    """
    client = _get_client()

    user_prompt = _build_prompt(log, context)
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

    # Configure for JSON output
    generation_config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
    )

    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]
    last_error = None

    for model_name in models_to_try:
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=full_prompt,
                    config=generation_config,
                )

                raw_text = response.text

                # Parse JSON response
                try:
                    parsed = _parse_json_response(raw_text)
                except ValueError:
                    # If JSON parsing fails, create a basic structure
                    parsed = {
                        "filepath": None,
                        "full_code_block": raw_text,
                        "explanation": "AI returned non-JSON response. Raw output provided.",
                    }

                # Normalize and validate filepath
                raw_filepath = parsed.get("filepath")
                normalized_filepath = _normalize_filepath(raw_filepath)

                return FixResult(
                    filepath=normalized_filepath,
                    full_code_block=parsed.get("full_code_block", ""),
                    explanation=parsed.get("explanation", ""),
                    raw_response=raw_text,
                    model_used=model_name,
                )

            except Exception as e:
                error_str = str(e).lower()
                last_error = e

                is_quota_error = any(x in error_str for x in [
                    "429", "quota", "rate limit", "resource exhausted"
                ])

                if is_quota_error:
                    if model_name == PRIMARY_MODEL:
                        break  # Try fallback model

                    wait_time = (2 ** attempt) * 5
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                        continue

                raise

        if model_name == PRIMARY_MODEL and last_error:
            continue

    raise last_error


def analyze_error_simple(log: str, context: str, max_retries: int = 3) -> str:
    """Analyze error and return raw text (for backward compatibility).

    Args:
        log: The error log or traceback
        context: Source code context around the error
        max_retries: Number of retries for rate limit errors

    Returns:
        Raw text fix from Gemini
    """
    result = analyze_error(log, context, max_retries)
    return result.full_code_block or result.raw_response


def _build_prompt(log: str, context: str) -> str:
    """Build the user prompt from log and context."""
    parts = ["## ERROR LOG", log]

    if context:
        parts.extend(["", "## SOURCE CONTEXT", context])

    parts.extend([
        "",
        "## INSTRUCTIONS",
        "Analyze the error above. Return the corrected code as JSON.",
        "The full_code_block should contain the complete fixed code, ready to replace the original.",
        "If no specific file path is in the error traceback, set filepath to null.",
    ])

    return "\n".join(parts)
