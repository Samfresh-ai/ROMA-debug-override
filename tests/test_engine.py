"""Tests for the engine module."""

import pytest
from unittest.mock import patch, MagicMock
import json

from roma_debug.core.engine import (
    analyze_error,
    analyze_error_v2,
    _build_prompt,
    _build_prompt_v2,
    _parse_json_response,
    _normalize_filepath,
    _determine_action_type,
    FixResult,
    FixResultV2,
    ActionType,
)


class TestBuildPrompt:
    """Tests for prompt building."""

    def test_builds_prompt_with_log_only(self):
        """Test prompt building with just error log."""
        log = "ValueError: test error"
        context = ""

        prompt = _build_prompt(log, context)

        assert "## USER INPUT" in prompt
        assert "ValueError: test error" in prompt
        assert "## SOURCE CONTEXT" not in prompt

    def test_builds_prompt_with_context(self):
        """Test prompt building with log and context."""
        log = "ValueError: test error"
        context = "def func():\n    pass"

        prompt = _build_prompt(log, context)

        assert "## USER INPUT" in prompt
        assert "ValueError: test error" in prompt
        assert "## SOURCE CONTEXT" in prompt
        assert "def func():" in prompt

    def test_v2_prompt(self):
        """Test V2 prompt building."""
        log = "ValueError: test"
        context = "## PRIMARY ERROR\nsome context"

        prompt = _build_prompt_v2(log, context)

        assert "## USER INPUT" in prompt
        assert "QUESTION" in prompt  # Should mention QUESTION/ANSWER logic
        assert "PATCH" in prompt  # Should mention PATCH mode


class TestParseJsonResponse:
    """Tests for JSON response parsing."""

    def test_parses_plain_json(self):
        """Test parsing plain JSON."""
        text = '{"filepath": "test.py", "full_code_block": "code", "explanation": "fixed"}'
        result = _parse_json_response(text)

        assert result["filepath"] == "test.py"
        assert result["full_code_block"] == "code"

    def test_parses_json_in_markdown(self):
        """Test parsing JSON wrapped in markdown code block."""
        text = '''```json
{"filepath": "test.py", "full_code_block": "code", "explanation": "fixed"}
```'''
        result = _parse_json_response(text)

        assert result["filepath"] == "test.py"

    def test_parses_json_in_markdown_no_lang(self):
        """Test parsing JSON in markdown without language specifier."""
        text = '''```
{"filepath": "test.py", "full_code_block": "code", "explanation": "fixed"}
```'''
        result = _parse_json_response(text)

        assert result["filepath"] == "test.py"

    def test_raises_on_invalid_json(self):
        """Test that invalid JSON raises ValueError."""
        text = "This is not JSON at all"

        with pytest.raises(ValueError):
            _parse_json_response(text)


class TestNormalizeFilepath:
    """Tests for filepath normalization."""

    def test_returns_valid_path(self):
        """Test that valid paths are returned as-is."""
        assert _normalize_filepath("src/main.py") == "src/main.py"
        assert _normalize_filepath("/app/test.py") == "/app/test.py"

    def test_returns_none_for_placeholders(self):
        """Test that placeholder paths return None."""
        assert _normalize_filepath("path/to/file.py") is None
        assert _normalize_filepath("your_file.py") is None
        assert _normalize_filepath("example.py") is None
        assert _normalize_filepath("<filename>") is None

    def test_returns_none_for_empty(self):
        """Test that empty/null paths return None."""
        assert _normalize_filepath(None) is None
        assert _normalize_filepath("") is None
        assert _normalize_filepath("   ") is None


class TestActionType:
    """Tests for ActionType enum and determination."""

    def test_from_string_patch(self):
        """Test parsing PATCH action type."""
        assert ActionType.from_string("PATCH") == ActionType.PATCH
        assert ActionType.from_string("patch") == ActionType.PATCH
        assert ActionType.from_string("Patch") == ActionType.PATCH

    def test_from_string_answer(self):
        """Test parsing ANSWER action type."""
        assert ActionType.from_string("ANSWER") == ActionType.ANSWER
        assert ActionType.from_string("answer") == ActionType.ANSWER
        assert ActionType.from_string("Answer") == ActionType.ANSWER

    def test_from_string_default(self):
        """Test default to PATCH for unknown values."""
        assert ActionType.from_string(None) == ActionType.PATCH
        assert ActionType.from_string("unknown") == ActionType.PATCH
        assert ActionType.from_string("") == ActionType.PATCH

    def test_determine_action_type_explicit(self):
        """Test determining action type from explicit field."""
        assert _determine_action_type({"action_type": "ANSWER"}) == ActionType.ANSWER
        assert _determine_action_type({"action_type": "PATCH"}) == ActionType.PATCH

    def test_determine_action_type_heuristic(self):
        """Test heuristic action type determination."""
        # No filepath and no code = ANSWER
        assert _determine_action_type({"filepath": None, "full_code_block": ""}) == ActionType.ANSWER
        assert _determine_action_type({"filepath": None, "full_code_block": "   "}) == ActionType.ANSWER

        # Has filepath or code = PATCH
        assert _determine_action_type({"filepath": "test.py", "full_code_block": ""}) == ActionType.PATCH
        assert _determine_action_type({"filepath": None, "full_code_block": "code"}) == ActionType.PATCH


class TestFixResult:
    """Tests for FixResult class."""

    def test_to_dict(self):
        """Test FixResult to_dict conversion."""
        result = FixResult(
            filepath="test.py",
            full_code_block="def fix(): pass",
            explanation="Fixed the bug",
            raw_response="{}",
            model_used="gemini-2.5-flash",
        )

        d = result.to_dict()

        assert d["filepath"] == "test.py"
        assert d["full_code_block"] == "def fix(): pass"
        assert d["explanation"] == "Fixed the bug"
        assert d["action_type"] == "PATCH"

    def test_is_answer_only(self):
        """Test is_answer_only property."""
        patch_result = FixResult(
            filepath="test.py",
            full_code_block="code",
            explanation="fix",
            raw_response="{}",
            model_used="gemini",
            action_type=ActionType.PATCH,
        )
        answer_result = FixResult(
            filepath=None,
            full_code_block="",
            explanation="The answer is...",
            raw_response="{}",
            model_used="gemini",
            action_type=ActionType.ANSWER,
        )

        assert patch_result.is_answer_only is False
        assert patch_result.is_patch is True
        assert answer_result.is_answer_only is True
        assert answer_result.is_patch is False


class TestFixResultV2:
    """Tests for FixResultV2 class."""

    def test_has_root_cause(self):
        """Test has_root_cause property."""
        result = FixResultV2(
            filepath="main.py",
            full_code_block="code",
            explanation="fix",
            raw_response="{}",
            model_used="gemini",
            root_cause_file="utils.py",
            root_cause_explanation="The bug is actually here",
        )

        assert result.has_root_cause is True

    def test_no_root_cause_when_same_file(self):
        """Test has_root_cause is False when root_cause_file matches filepath."""
        result = FixResultV2(
            filepath="main.py",
            full_code_block="code",
            explanation="fix",
            raw_response="{}",
            model_used="gemini",
            root_cause_file="main.py",
        )

        assert result.has_root_cause is False

    def test_all_files_to_fix(self):
        """Test all_files_to_fix property."""
        from roma_debug.core.engine import AdditionalFix

        result = FixResultV2(
            filepath="main.py",
            full_code_block="code",
            explanation="fix",
            raw_response="{}",
            model_used="gemini",
            root_cause_file="utils.py",
            additional_fixes=[
                AdditionalFix(filepath="helpers.py", full_code_block="", explanation=""),
            ],
        )

        files = result.all_files_to_fix
        assert "main.py" in files
        assert "utils.py" in files
        assert "helpers.py" in files

    def test_v2_to_dict(self):
        """Test FixResultV2 to_dict includes V2 fields."""
        from roma_debug.core.engine import AdditionalFix

        result = FixResultV2(
            filepath="main.py",
            full_code_block="code",
            explanation="fix",
            raw_response="{}",
            model_used="gemini",
            root_cause_file="utils.py",
            root_cause_explanation="Root cause here",
            additional_fixes=[
                AdditionalFix(filepath="other.py", full_code_block="more code", explanation="also fix"),
            ],
        )

        d = result.to_dict()

        assert d["root_cause_file"] == "utils.py"
        assert d["root_cause_explanation"] == "Root cause here"
        assert len(d["additional_fixes"]) == 1
        assert d["additional_fixes"][0]["filepath"] == "other.py"


class TestAnalyzeError:
    """Tests for analyze_error function with mocked API."""

    @patch('roma_debug.core.engine._get_client')
    def test_returns_fix_result(self, mock_get_client):
        """Test that analyze_error returns a FixResult."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "filepath": "test.py",
            "full_code_block": "def fixed(): pass",
            "explanation": "Fixed the function"
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_error("ValueError: test", "def broken(): pass")

        assert isinstance(result, FixResult)
        assert result.filepath == "test.py"
        assert result.full_code_block == "def fixed(): pass"

    @patch('roma_debug.core.engine._get_client')
    def test_handles_null_filepath(self, mock_get_client):
        """Test handling of null filepath in response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "filepath": None,
            "full_code_block": "general advice",
            "explanation": "This is a config error"
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_error("400 API key invalid", "")

        assert result.filepath is None


class TestAnalyzeErrorV2:
    """Tests for analyze_error_v2 function."""

    @patch('roma_debug.core.engine._get_client')
    def test_returns_v2_result(self, mock_get_client):
        """Test that analyze_error_v2 returns FixResultV2."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "filepath": "main.py",
            "full_code_block": "fixed code",
            "explanation": "Fixed",
            "root_cause_file": "utils.py",
            "root_cause_explanation": "The bug was here",
            "additional_fixes": []
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_error_v2("Error trace", "context")

        assert isinstance(result, FixResultV2)
        assert result.root_cause_file == "utils.py"

    @patch('roma_debug.core.engine._get_client')
    def test_parses_additional_fixes(self, mock_get_client):
        """Test parsing of additional_fixes in V2 response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "filepath": "main.py",
            "full_code_block": "code1",
            "explanation": "Fix 1",
            "additional_fixes": [
                {"filepath": "utils.py", "full_code_block": "code2", "explanation": "Fix 2"},
                {"filepath": "helpers.py", "full_code_block": "code3", "explanation": "Fix 3"},
            ]
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_error_v2("Error", "context")

        assert len(result.additional_fixes) == 2
        assert result.additional_fixes[0].filepath == "utils.py"
        assert result.additional_fixes[1].filepath == "helpers.py"

    @patch('roma_debug.core.engine._get_client')
    def test_answer_mode_v2(self, mock_get_client):
        """Test V2 ANSWER mode response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "action_type": "ANSWER",
            "filepath": None,
            "full_code_block": "",
            "explanation": "There are 5 files in the src folder."
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_error_v2("How many files in src?", "context")

        assert result.is_answer_only is True
        assert result.filepath is None
        assert result.full_code_block == ""
        assert "5 files" in result.explanation
        assert result.all_files_to_fix == []  # No files to fix in ANSWER mode
