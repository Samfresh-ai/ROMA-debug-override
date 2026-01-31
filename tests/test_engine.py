"""Tests for the engine module."""

import pytest
from unittest.mock import patch, MagicMock

from roma_debug.core.engine import analyze_error, _build_prompt


class TestBuildPrompt:
    """Tests for prompt building."""

    def test_builds_prompt_with_log_only(self):
        """Test prompt building with just error log."""
        log = "ValueError: test error"
        context = ""

        prompt = _build_prompt(log, context)

        assert "## ERROR LOG" in prompt
        assert "ValueError: test error" in prompt
        assert "## SOURCE CONTEXT" not in prompt

    def test_builds_prompt_with_context(self):
        """Test prompt building with log and context."""
        log = "ValueError: test error"
        context = "def func():\n    pass"

        prompt = _build_prompt(log, context)

        assert "## ERROR LOG" in prompt
        assert "ValueError: test error" in prompt
        assert "## SOURCE CONTEXT" in prompt
        assert "def func():" in prompt


class TestAnalyzeError:
    """Tests for analyze_error function."""

    def test_raises_without_api_key(self):
        """Test that missing API key raises ValueError."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="No API key found"):
                analyze_error("test log", "test context")

    @patch('roma_debug.core.engine.genai')
    def test_calls_gemini_with_temperature_zero(self, mock_genai):
        """Test that Gemini is called with temperature=0."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "fixed code"
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key'}):
            result = analyze_error("test log", "test context")

        # Check GenerativeModel was called with temperature=0
        call_kwargs = mock_genai.GenerativeModel.call_args
        assert call_kwargs[1]['generation_config']['temperature'] == 0

        assert result == "fixed code"

    @patch('roma_debug.core.engine.genai')
    def test_uses_gemini_flash_model(self, mock_genai):
        """Test that Gemini 2.0 Flash model is used."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "fixed code"
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key'}):
            analyze_error("test log", "")

        # Check model name
        call_kwargs = mock_genai.GenerativeModel.call_args
        assert call_kwargs[1]['model_name'] == "gemini-2.0-flash"
