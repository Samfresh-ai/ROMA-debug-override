"""Gemini Fixer Logic for ROMA Debug.

Returns structured JSON responses for machine-readable fixes.
Supports both V1 (simple) and V2 (deep debugging) modes.
Supports PATCH and ANSWER action types.
"""

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

from google import genai
from google.genai import types

from roma_debug.config import GEMINI_API_KEY
from roma_debug.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_V2


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


class ActionType(str, Enum):
    """Type of action the AI determined to take."""
    PATCH = "PATCH"   # Code fix required
    ANSWER = "ANSWER"  # Information/answer only, no code changes

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ActionType":
        """Parse action type from string, defaulting to PATCH for backward compatibility."""
        if value is None:
            return cls.PATCH
        value_upper = str(value).upper().strip()
        if value_upper == "ANSWER":
            return cls.ANSWER
        return cls.PATCH


@dataclass
class FixResult:
    """Structured result from the AI engine."""
    filepath: Optional[str]  # None for general system errors or ANSWER mode
    full_code_block: str
    explanation: str
    raw_response: str
    model_used: str
    action_type: ActionType = ActionType.PATCH

    @property
    def is_answer_only(self) -> bool:
        """Check if this is an answer-only response (no code patch)."""
        return self.action_type == ActionType.ANSWER

    @property
    def is_patch(self) -> bool:
        """Check if this is a patch response."""
        return self.action_type == ActionType.PATCH

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "action_type": self.action_type.value,
            "filepath": self.filepath,
            "full_code_block": self.full_code_block,
            "explanation": self.explanation,
        }


@dataclass
class AdditionalFix:
    """An additional fix for another file."""
    filepath: str
    full_code_block: str
    explanation: str


@dataclass
class FixResultV2(FixResult):
    """V2 result with root cause analysis and multiple fixes."""
    root_cause_file: Optional[str] = None
    root_cause_explanation: Optional[str] = None
    additional_fixes: List[AdditionalFix] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = super().to_dict()
        result["root_cause_file"] = self.root_cause_file
        result["root_cause_explanation"] = self.root_cause_explanation
        result["additional_fixes"] = [
            {
                "filepath": fix.filepath,
                "full_code_block": fix.full_code_block,
                "explanation": fix.explanation,
            }
            for fix in self.additional_fixes
        ]
        return result

    @property
    def has_root_cause(self) -> bool:
        """Check if a root cause in a different file was identified."""
        return bool(self.root_cause_file and self.root_cause_file != self.filepath)

    @property
    def all_files_to_fix(self) -> List[str]:
        """Get list of all files that need fixes."""
        if self.is_answer_only:
            return []
        files = []
        if self.filepath:
            files.append(self.filepath)
        if self.root_cause_file and self.root_cause_file not in files:
            files.append(self.root_cause_file)
        for fix in self.additional_fixes:
            if fix.filepath not in files:
                files.append(fix.filepath)
        return files


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


def _determine_action_type(parsed: dict) -> ActionType:
    """Determine the action type from parsed response.

    Args:
        parsed: Parsed JSON response

    Returns:
        ActionType enum value
    """
    # Check explicit action_type field
    if "action_type" in parsed:
        return ActionType.from_string(parsed["action_type"])

    # Heuristic: if no filepath and no code, it's likely an answer
    filepath = parsed.get("filepath")
    code = parsed.get("full_code_block", "")

    if filepath is None and (not code or code.strip() == ""):
        return ActionType.ANSWER

    return ActionType.PATCH


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

                # Determine action type
                action_type = _determine_action_type(parsed)

                # Normalize and validate filepath
                raw_filepath = parsed.get("filepath")
                normalized_filepath = _normalize_filepath(raw_filepath)

                return FixResult(
                    filepath=normalized_filepath,
                    full_code_block=parsed.get("full_code_block", ""),
                    explanation=parsed.get("explanation", ""),
                    raw_response=raw_text,
                    model_used=model_name,
                    action_type=action_type,
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


def analyze_error_v2(
    log: str,
    context: str,
    max_retries: int = 3,
    include_upstream: bool = True,
) -> FixResultV2:
    """Analyze an error with V2 deep debugging (root cause analysis).

    Supports both PATCH and ANSWER action types.

    Args:
        log: The error log or traceback
        context: Source code context (should include upstream context for V2)
        max_retries: Number of retries for rate limit errors
        include_upstream: Whether upstream context was included

    Returns:
        FixResultV2 with root cause analysis and potentially multiple fixes

    Raises:
        Exception: If Gemini API call fails after retries
    """
    client = _get_client()

    user_prompt = _build_prompt_v2(log, context)
    full_prompt = f"{SYSTEM_PROMPT_V2}\n\n{user_prompt}"

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
                        "action_type": "PATCH",
                        "filepath": None,
                        "full_code_block": raw_text,
                        "explanation": "AI returned non-JSON response. Raw output provided.",
                    }

                # Determine action type
                action_type = _determine_action_type(parsed)

                # For ANSWER type, don't try to normalize paths or parse fixes
                if action_type == ActionType.ANSWER:
                    return FixResultV2(
                        filepath=None,
                        full_code_block="",
                        explanation=parsed.get("explanation", ""),
                        raw_response=raw_text,
                        model_used=model_name,
                        action_type=action_type,
                        root_cause_file=None,
                        root_cause_explanation=None,
                        additional_fixes=[],
                    )

                # PATCH mode - normalize filepaths
                normalized_filepath = _normalize_filepath(parsed.get("filepath"))
                root_cause_file = _normalize_filepath(parsed.get("root_cause_file"))

                # Parse additional fixes
                additional_fixes = []
                for fix_data in parsed.get("additional_fixes", []):
                    fix_path = _normalize_filepath(fix_data.get("filepath"))
                    if fix_path:
                        additional_fixes.append(AdditionalFix(
                            filepath=fix_path,
                            full_code_block=fix_data.get("full_code_block", ""),
                            explanation=fix_data.get("explanation", ""),
                        ))

                return FixResultV2(
                    filepath=normalized_filepath,
                    full_code_block=parsed.get("full_code_block", ""),
                    explanation=parsed.get("explanation", ""),
                    raw_response=raw_text,
                    model_used=model_name,
                    action_type=action_type,
                    root_cause_file=root_cause_file,
                    root_cause_explanation=parsed.get("root_cause_explanation"),
                    additional_fixes=additional_fixes,
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
    parts = ["## USER INPUT", log]

    if context:
        parts.extend(["", "## SOURCE CONTEXT", context])

    parts.extend([
        "",
        "## INSTRUCTIONS",
        "Analyze the input above. Return JSON response.",
        "If it's a code error, provide the fix in full_code_block.",
        "If no specific file path is in the error traceback, set filepath to null.",
    ])

    return "\n".join(parts)


def _build_prompt_v2(log: str, context: str) -> str:
    """Build V2 prompt with upstream context support and PATCH/ANSWER handling."""
    parts = ["## USER INPUT", log]

    if context:
        parts.extend(["", context])  # Context already formatted by ContextBuilder

    parts.extend([
        "",
        "## INSTRUCTIONS",
        "First, determine if this is a CODE ERROR or a QUESTION.",
        "",
        "If QUESTION (how many, where is, explain, etc.):",
        "- Set action_type to 'ANSWER'",
        "- Use the <ProjectStructure> file tree to find the answer",
        "- Put your answer in the explanation field",
        "- Set filepath to null and full_code_block to empty string",
        "- DO NOT write code to answer questions about files/folders",
        "",
        "If CODE ERROR (traceback, exception, crash):",
        "- Set action_type to 'PATCH'",
        "- Provide the complete fixed code in full_code_block",
        "- Set root_cause_file if bug originates in a different file",
        "",
        "Return valid JSON matching the output format.",
    ])

    return "\n".join(parts)
