"""Tests for the engine module."""

import pytest
from unittest.mock import patch, MagicMock
import json

from roma_debug.core.engine import (
    analyze_error,
    _parse_json_response,
    _normalize_filepath,
    _determine_action_type,
    FixResult,
    ActionType,
)


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


class TestAnalyzeError:
    """Tests for analyze_error function with mocked API."""

    @patch('roma_debug.core.engine._read_requested_files')
    @patch('roma_debug.core.engine._get_client')
    def test_returns_fix_result(self, mock_get_client, mock_read_files):
        """Test that analyze_error returns a FixResult."""
        mock_read_files.return_value = ([("test.py", "print('x')")], [])
        mock_client = MagicMock()
        mock_response_investigate = MagicMock()
        mock_response_investigate.text = json.dumps({
            "action_type": "INVESTIGATE",
            "files_to_read": ["test.py"],
        })
        mock_response_patch = MagicMock()
        mock_response_patch.text = json.dumps({
            "filepath": "test.py",
            "full_code_block": "def fixed(): pass",
            "explanation": "Fixed the function"
        })
        mock_client.models.generate_content.side_effect = [
            mock_response_investigate,
            mock_response_patch,
        ]
        mock_get_client.return_value = mock_client

        result = analyze_error("ValueError: test", "def broken(): pass")

        assert isinstance(result, FixResult)
        assert result.filepath == "test.py"
        assert result.full_code_block == "def fixed(): pass"

    @patch('roma_debug.core.engine._read_requested_files')
    @patch('roma_debug.core.engine._get_client')
    def test_handles_null_filepath(self, mock_get_client, mock_read_files):
        """Test handling of null filepath in response."""
        mock_read_files.return_value = ([("test.py", "print('x')")], [])
        mock_client = MagicMock()
        mock_response_investigate = MagicMock()
        mock_response_investigate.text = json.dumps({
            "action_type": "INVESTIGATE",
            "files_to_read": ["test.py"],
        })
        mock_response_patch = MagicMock()
        mock_response_patch.text = json.dumps({
            "filepath": None,
            "full_code_block": "general advice",
            "explanation": "This is a config error"
        })
        mock_client.models.generate_content.side_effect = [
            mock_response_investigate,
            mock_response_patch,
        ]
        mock_get_client.return_value = mock_client

        result = analyze_error("400 API key invalid", "")

        assert result.filepath is None
