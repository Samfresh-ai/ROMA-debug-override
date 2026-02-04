"""Gemini Fixer Logic for ROMA Debug.

Returns structured JSON responses for machine-readable fixes.
Supports PATCH, ANSWER, and INVESTIGATE action types.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Tuple

from google import genai
from google.genai import types

from roma_debug.config import get_api_keys
from roma_debug.prompts import SYSTEM_PROMPT


# Model priority: try Gemini 3 first, then 2.5 fallback, then 2.5 flash lite
PRIMARY_MODEL = "gemini-3-flash-preview"
FALLBACK_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL_LITE = "gemini-2.5-flash-lite"


def _get_models_to_try() -> list[str]:
    """Get model list from env override or default priority list."""
    env_models = (
        os.environ.get("ROMA_MODELS")
        or os.environ.get("GEMINI_MODELS")
        or os.environ.get("GOOGLE_MODELS")
        or ""
    )
    models = [m.strip() for m in env_models.split(",") if m.strip()]
    if models:
        # De-dupe while preserving order
        seen = set()
        ordered = []
        for m in models:
            if m not in seen:
                seen.add(m)
                ordered.append(m)
        return ordered
    return [PRIMARY_MODEL, FALLBACK_MODEL, FALLBACK_MODEL_LITE]

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

def _extract_retry_delay_seconds(error_str: str) -> float:
    """Extract retry delay in seconds from error messages if present."""
    if not error_str:
        return 0.0
    # Examples: "Please retry in 12.64s" or "retryDelay': '12s'"
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", error_str, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"retrydelay['\"]?:\s*['\"]?([0-9]+)s", error_str, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return 0.0


class ActionType(str, Enum):
    """Type of action the AI determined to take."""
    PATCH = "PATCH"   # Code fix required
    ANSWER = "ANSWER"  # Information/answer only, no code changes
    INVESTIGATE = "INVESTIGATE"  # Request files to read before patching

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ActionType":
        """Parse action type from string, defaulting to PATCH for backward compatibility."""
        if value is None:
            return cls.PATCH
        value_upper = str(value).upper().strip()
        if value_upper == "ANSWER":
            return cls.ANSWER
        if value_upper == "INVESTIGATE":
            return cls.INVESTIGATE
        return cls.PATCH


@dataclass
@dataclass
class AdditionalFix:
    """An additional fix for another file."""
    filepath: str
    full_code_block: str
    explanation: str


@dataclass
class FixResult:
    """Result with root cause analysis and multiple fixes."""
    filepath: Optional[str]  # None for general system errors or ANSWER mode
    full_code_block: str
    explanation: str
    raw_response: str
    model_used: str
    action_type: ActionType = ActionType.PATCH
    root_cause_file: Optional[str] = None
    root_cause_explanation: Optional[str] = None
    additional_fixes: List[AdditionalFix] = field(default_factory=list)
    files_read: List[str] = field(default_factory=list)
    files_read_sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "action_type": self.action_type.value,
            "filepath": self.filepath,
            "full_code_block": self.full_code_block,
            "explanation": self.explanation,
            "root_cause_file": self.root_cause_file,
            "root_cause_explanation": self.root_cause_explanation,
            "additional_fixes": [
                {
                    "filepath": fix.filepath,
                    "full_code_block": fix.full_code_block,
                    "explanation": fix.explanation,
                }
                for fix in self.additional_fixes
            ],
            "files_read": self.files_read,
            "files_read_sources": self.files_read_sources,
        }

    @property
    def is_answer_only(self) -> bool:
        """Check if this is an answer-only response (no code patch)."""
        return self.action_type == ActionType.ANSWER

    @property
    def is_patch(self) -> bool:
        """Check if this is a patch response."""
        return self.action_type == ActionType.PATCH

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


_KEY_INDEX = 0


def _get_client_for_key(api_key: str) -> genai.Client:
    """Get configured Gemini client for a specific key."""
    return genai.Client(api_key=api_key)


def _get_key_pool() -> list[str]:
    keys = get_api_keys()
    if not keys:
        raise RuntimeError(
            "GEMINI_API_KEY not found! Please set GEMINI_API_KEY in your .env "
            "file or environment (or set GOOGLE_API_KEY)."
        )
    return keys


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

    # Heuristic: investigation if files_to_read present
    if "files_to_read" in parsed:
        return ActionType.INVESTIGATE

    # Heuristic: if no filepath and no code, it's likely an answer
    filepath = parsed.get("filepath")
    code = parsed.get("full_code_block", "")

    if filepath is None and (not code or code.strip() == ""):
        return ActionType.ANSWER

    return ActionType.PATCH


def _sanitize_files_to_read(files_to_read: object) -> List[str]:
    """Normalize files_to_read into a clean list of paths."""
    if isinstance(files_to_read, str):
        files = [files_to_read]
    elif isinstance(files_to_read, list):
        files = files_to_read
    else:
        return []

    cleaned: List[str] = []
    for item in files:
        if isinstance(item, str):
            path = item.strip()
            if path:
                cleaned.append(path)
    return cleaned


def _resolve_requested_path(requested_path: str, project_root: str) -> Optional[str]:
    """Resolve a requested file path within the project root."""
    if not requested_path:
        return None

    project_root = os.path.realpath(project_root)
    candidates = []

    if os.path.isabs(requested_path):
        candidates.append(requested_path)
    else:
        candidates.append(os.path.join(project_root, requested_path))
        if requested_path.startswith("./"):
            candidates.append(os.path.join(project_root, requested_path[2:]))

    for candidate in candidates:
        resolved = os.path.realpath(candidate)
        if os.path.isfile(resolved) and resolved.startswith(project_root + os.sep):
            return resolved

    basename = os.path.basename(requested_path)
    if not basename:
        return None

    for root, _, files in os.walk(project_root):
        if basename in files:
            resolved = os.path.realpath(os.path.join(root, basename))
            if resolved.startswith(project_root + os.sep):
                return resolved

    return None


def _read_requested_files(
    files_to_read: List[str],
    project_root: str,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Read requested files, returning (contents, missing)."""
    contents: List[Tuple[str, str]] = []
    missing: List[str] = []
    seen: set[str] = set()

    for requested_path in files_to_read:
        resolved = _resolve_requested_path(requested_path, project_root)
        if not resolved:
            if requested_path not in seen:
                missing.append(requested_path)
                seen.add(requested_path)
            continue

        rel_path = os.path.relpath(resolved, project_root)
        if rel_path in seen:
            continue

        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as handle:
                contents.append((rel_path, handle.read()))
                seen.add(rel_path)
        except Exception:
            missing.append(requested_path)

    return contents, missing


def _normalize_relpath(path: str) -> str:
    """Normalize a path for comparison (posix, no leading ./)."""
    path = path.replace("\\", "/").strip()
    if path.startswith("./"):
        path = path[2:]
    return path


def _resolve_traceback_files(
    traceback_files: List[str],
    project_root: str,
) -> List[str]:
    """Resolve traceback file paths to project-relative paths when possible."""
    resolved: List[str] = []
    project_root = os.path.realpath(project_root)

    for path in traceback_files:
        if not path:
            continue
        if os.path.isabs(path):
            real = os.path.realpath(path)
            if real.startswith(project_root + os.sep):
                rel = os.path.relpath(real, project_root)
                resolved.append(_normalize_relpath(rel))
            else:
                resolved.append(_normalize_relpath(path))
            continue

        # Try direct relative match first
        candidate = os.path.join(project_root, path)
        if os.path.isfile(candidate):
            resolved.append(_normalize_relpath(path))
            continue

        # Fallback: suffix match within project
        suffix = _normalize_relpath(path)
        matches: List[str] = []
        for root, _, files in os.walk(project_root):
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), project_root)
                rel_norm = _normalize_relpath(rel)
                if rel_norm.endswith(suffix):
                    matches.append(rel_norm)
            if len(matches) > 1:
                break

        if len(matches) == 1:
            resolved.append(matches[0])
        else:
            resolved.append(_normalize_relpath(path))

    return list(dict.fromkeys(p for p in resolved if p))


def _build_investigation_prompt(log: str, file_tree: str) -> str:
    """Build the investigation prompt with error log and file tree."""
    parts = [
        "<ErrorLog>",
        log,
        "</ErrorLog>",
        "",
        "<TracebackFiles>",
        "\n".join(_extract_traceback_files(log, os.getcwd())),
        "</TracebackFiles>",
        "",
        "<ProjectStructure>",
        "```",
        file_tree,
        "```",
        "</ProjectStructure>",
    ]
    return "\n".join(parts)


def _build_patch_prompt(
    log: str,
    file_tree: str,
    file_contents: List[Tuple[str, str]],
    missing_files: List[str],
    fallback_context: Optional[str] = None,
) -> str:
    """Build the patch/answer prompt with requested file contents."""
    parts = [
        "<ErrorLog>",
        log,
        "</ErrorLog>",
        "",
        "<ProjectStructure>",
        "```",
        file_tree,
        "```",
        "</ProjectStructure>",
        "",
    ]

    if missing_files:
        parts.extend([
            "<MissingFiles>",
            "\n".join(missing_files),
            "</MissingFiles>",
            "",
        ])

    if file_contents:
        parts.append("<FileContents>")
        for rel_path, content in file_contents:
            parts.append(f"## {rel_path}")
            parts.append("```")
            parts.append(content)
            parts.append("```")
        parts.append("</FileContents>")
    elif fallback_context:
        parts.extend([
            "<FileContents>",
            "(No files were requested or resolved. Provided context follows.)",
            "```",
            fallback_context,
            "```",
            "</FileContents>",
        ])
    else:
        parts.extend([
            "<FileContents>",
            "(No files were requested or resolved.)",
            "</FileContents>",
        ])

    return "\n".join(parts)


def _extract_traceback_files(log: str, project_root: str) -> List[str]:
    """Extract file paths from stack traces or error logs."""
    candidates: List[str] = []

    # Node/JS stack traces: at ... (/path/file.js:line:col)
    for match in re.findall(r'\(([^)]+?\.(?:js|ts|jsx|tsx)):\d+:\d+\)', log):
        candidates.append(match)

    # Python tracebacks: File "/path/file.py", line X
    for match in re.findall(r'File [\'"](.+?\.(?:py|js|ts|jsx|tsx|go|rs|java))[\'"], line \d+', log):
        candidates.append(match)

    resolved: List[str] = []
    for path in candidates:
        # Skip dependencies in node_modules; we want project files
        if "node_modules" in path:
            continue
        if os.path.isabs(path):
            try:
                rel = os.path.relpath(path, project_root)
                if not rel.startswith(".."):
                    resolved.append(rel)
                else:
                    resolved.append(path)
            except Exception:
                resolved.append(path)
        else:
            resolved.append(path)

    # Deduplicate
    return list(dict.fromkeys(p for p in resolved if p))


def _extract_project_traceback_files(log: str, project_root: str) -> List[str]:
    """Extract traceback files that belong to the project (exclude deps)."""
    files = _extract_traceback_files(log, project_root)
    if not files:
        return []

    project_root = os.path.realpath(project_root)
    filtered: List[str] = []
    for path in files:
        if os.path.isabs(path):
            real = os.path.realpath(path)
            if real.startswith(project_root + os.sep):
                filtered.append(path)
        else:
            # relative paths are treated as project-local
            if "node_modules" not in path:
                filtered.append(path)

    return list(dict.fromkeys(filtered))


def _fallback_files_to_read(log: str, project_root: str) -> List[str]:
    """Infer a minimal set of files to read when the model skips INVESTIGATE."""
    candidates: List[str] = []
    log_lower = log.lower()

    # Use stack trace file paths if present
    for path in _extract_traceback_files(log, project_root):
        if path not in candidates:
            candidates.append(path)

    # Extract explicit file mentions from the log
    file_mentions = re.findall(
        r'[\w\-/]+\.(?:html|css|js|ts|jsx|tsx|py|go|rs|java|json|env)',
        log,
        re.IGNORECASE,
    )
    for mention in file_mentions:
        if mention not in candidates:
            candidates.append(mention)

    # CSP and browser console errors should inspect HTML
    if "content security policy" in log_lower or "csp" in log_lower:
        if "index.html" not in candidates:
            candidates.append("index.html")

    # If nothing explicit, use entry points for server-side errors
    server_side_markers = [
        "node_modules",
        "express",
        "router",
        "patherror",
        "typeerror",
        "referenceerror",
        "stack trace",
        "at ",
    ]
    if not candidates and any(m in log_lower for m in server_side_markers):
        try:
            from roma_debug.tracing.project_scanner import ProjectScanner

            scanner = ProjectScanner(project_root)
            info = scanner.scan()
            for ep in info.entry_points[:3]:
                candidates.append(ep.path)
        except Exception:
            pass

    # Common frontend entry if HTTP/404 without explicit file
    if not candidates and ("404" in log_lower or "not found" in log_lower):
        candidates.append("index.html")

    return candidates[:5]


def _merge_files_to_read(
    model_files: List[str],
    traceback_files: List[str],
    heuristic_files: List[str],
) -> Tuple[List[str], dict[str, str]]:
    """Merge file lists and annotate sources."""
    merged: List[str] = []
    sources: dict[str, str] = {}

    def add_files(files: List[str], source: str) -> None:
        for path in files:
            if path not in merged:
                merged.append(path)
            if path not in sources:
                sources[path] = source

    add_files(model_files, "model")
    add_files(traceback_files, "traceback")
    add_files(heuristic_files, "heuristic")

    return merged, sources


def analyze_error(
    log: str,
    context: str,
    max_retries: int = 3,
    include_upstream: bool = True,
    project_root: Optional[str] = None,
    file_tree: Optional[str] = None,
    system_prompt_suffix: Optional[str] = None,
) -> FixResult:
    """Analyze an error with investigation-first debugging (root cause analysis).

    Args:
        log: The error log or traceback
        context: Source code context (optional, used as fallback)
        max_retries: Number of retries for rate limit errors
        include_upstream: Whether upstream context was included
        project_root: Project root for resolving requested files and file tree

    Returns:
        FixResult with root cause analysis and potentially multiple fixes

    Raises:
        Exception: If Gemini API call fails after retries
    """
    keys = _get_key_pool()
    global _KEY_INDEX
    debug_keys = os.environ.get("ROMA_DEBUG_KEYS", "").lower() in {"1", "true", "yes"}

    project_root = project_root or os.getcwd()
    if file_tree is None:
        from roma_debug.utils.context import generate_file_tree
        file_tree = generate_file_tree(project_root)
    traceback_files = _extract_project_traceback_files(log, project_root)
    resolved_traceback_files = _resolve_traceback_files(traceback_files, project_root)

    investigation_prompt = _build_investigation_prompt(log, file_tree)
    system_prompt = SYSTEM_PROMPT
    if system_prompt_suffix:
        system_prompt = f"{SYSTEM_PROMPT}\n\n{system_prompt_suffix}"
    full_prompt = f"{system_prompt}\n\n{investigation_prompt}"

    # Configure for JSON output
    generation_config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
    )

    models_to_try = _get_models_to_try()
    last_error = None

    for model_name in models_to_try:
        for attempt in range(max_retries):
            try:
                api_key = keys[_KEY_INDEX % len(keys)]
                if debug_keys:
                    print(f"[ROMA] Using API key index {_KEY_INDEX % len(keys)}")
                _KEY_INDEX += 1
                client = _get_client_for_key(api_key)
                response = client.models.generate_content(
                    model=model_name,
                    contents=full_prompt,
                    config=generation_config,
                )

                raw_text = response.text

                # Parse JSON response (investigation step)
                try:
                    parsed = _parse_json_response(raw_text)
                except ValueError:
                    parsed = {
                        "action_type": "INVESTIGATE",
                        "files_to_read": [],
                        "thought": "AI returned non-JSON response. Raw output provided.",
                    }

                action_type = _determine_action_type(parsed)

                model_files: List[str] = []
                if action_type == ActionType.INVESTIGATE:
                    model_files = _sanitize_files_to_read(parsed.get("files_to_read"))
                else:
                    # Enforce investigate-first if the model skipped it
                    model_files = _sanitize_files_to_read(parsed.get("files_to_read"))
                    action_type = ActionType.INVESTIGATE

                heuristic_files: List[str] = []
                if action_type == ActionType.INVESTIGATE and not model_files:
                    heuristic_files = _fallback_files_to_read(log, project_root)

                files_to_read, files_read_sources = _merge_files_to_read(
                    model_files=model_files,
                    traceback_files=traceback_files,
                    heuristic_files=heuristic_files,
                )

                if action_type == ActionType.INVESTIGATE:
                    if not files_to_read:
                        files_to_read = _fallback_files_to_read(log, project_root)
                        files_to_read, files_read_sources = _merge_files_to_read(
                            model_files=[],
                            traceback_files=traceback_files,
                            heuristic_files=files_to_read,
                        )

                    file_contents, missing_files = _read_requested_files(
                        files_to_read,
                        project_root,
                    )
                    files_read = [path for path, _ in file_contents]

                    if not file_contents:
                        return FixResult(
                            filepath=None,
                            full_code_block="",
                            explanation=(
                                "Investigation required before patching. "
                                "No files were successfully read."
                            ),
                            raw_response=raw_text,
                            model_used=model_name,
                            action_type=ActionType.ANSWER,
                            root_cause_file=None,
                            root_cause_explanation=None,
                            additional_fixes=[],
                            files_read=files_read,
                            files_read_sources=files_read_sources,
                        )

                    if resolved_traceback_files:
                        read_paths = { _normalize_relpath(path) for path, _ in file_contents }
                        unresolved = [f for f in resolved_traceback_files if _normalize_relpath(f) not in read_paths]
                        if unresolved:
                            return FixResult(
                                filepath=None,
                                full_code_block="",
                                explanation=(
                                    "Investigation required before patching. "
                                    "Traceback files were not read: "
                                    + ", ".join(unresolved)
                                ),
                                raw_response=raw_text,
                                model_used=model_name,
                                action_type=ActionType.ANSWER,
                                root_cause_file=None,
                                root_cause_explanation=None,
                                additional_fixes=[],
                                files_read=files_read,
                                files_read_sources=files_read_sources,
                            )

                    patch_prompt = _build_patch_prompt(
                        log=log,
                        file_tree=file_tree,
                        file_contents=file_contents,
                        missing_files=missing_files,
                        fallback_context=context,
                    )
                    final_prompt = f"{system_prompt}\n\n{patch_prompt}"

                    final_response = client.models.generate_content(
                        model=model_name,
                        contents=final_prompt,
                        config=generation_config,
                    )

                    raw_text = final_response.text

                    try:
                        parsed = _parse_json_response(raw_text)
                    except ValueError:
                        parsed = {
                            "action_type": "PATCH",
                            "filepath": None,
                            "full_code_block": raw_text,
                            "explanation": "AI returned non-JSON response. Raw output provided.",
                        }

                    action_type = _determine_action_type(parsed)

                    if action_type == ActionType.INVESTIGATE:
                        requested = _sanitize_files_to_read(parsed.get("files_to_read"))
                        return FixResult(
                            filepath=None,
                            full_code_block="",
                            explanation=(
                                "Model requested additional files after investigation. "
                                "Please rerun with the suggested files available."
                                + (f" Requested: {', '.join(requested)}" if requested else "")
                            ),
                            raw_response=raw_text,
                            model_used=model_name,
                            action_type=ActionType.ANSWER,
                            root_cause_file=None,
                            root_cause_explanation=None,
                            additional_fixes=[],
                            files_read=files_read,
                            files_read_sources=files_read_sources,
                        )

                # For ANSWER type, don't try to normalize paths or parse fixes
                if action_type == ActionType.ANSWER:
                    return FixResult(
                        filepath=None,
                        full_code_block="",
                        explanation=parsed.get("explanation", ""),
                        raw_response=raw_text,
                        model_used=model_name,
                        action_type=action_type,
                        root_cause_file=None,
                        root_cause_explanation=None,
                        additional_fixes=[],
                        files_read=files_read,
                        files_read_sources=files_read_sources,
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

                return FixResult(
                    filepath=normalized_filepath,
                    full_code_block=parsed.get("full_code_block", ""),
                    explanation=parsed.get("explanation", ""),
                    raw_response=raw_text,
                    model_used=model_name,
                    action_type=action_type,
                    root_cause_file=root_cause_file,
                    root_cause_explanation=parsed.get("root_cause_explanation"),
                    additional_fixes=additional_fixes,
                    files_read=files_read,
                    files_read_sources=files_read_sources,
                )

            except Exception as e:
                error_str = str(e).lower()
                last_error = e

                is_quota_error = any(x in error_str for x in [
                    "429", "quota", "rate limit", "resource exhausted", "resource_exhausted"
                ])
                is_overloaded_error = any(x in error_str for x in [
                    "503", "unavailable", "overloaded"
                ])

                if is_quota_error or is_overloaded_error:
                    retry_delay = _extract_retry_delay_seconds(error_str)
                    if len(keys) > 1:
                        if retry_delay > 0:
                            time.sleep(retry_delay)
                        continue
                    wait_time = retry_delay or ((2 ** attempt) * 5)
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                        continue
                    if model_name == PRIMARY_MODEL:
                        break  # Try fallback model

                raise

        if model_name == PRIMARY_MODEL and last_error:
            continue

    raise last_error

 
