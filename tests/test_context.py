"""Tests for the context reader module."""

import os
import tempfile
import pytest

from roma_debug.utils.context import get_file_context


class TestGetFileContext:
    """Tests for get_file_context function."""

    def test_extracts_file_path_from_traceback(self):
        """Test that file paths are extracted from Python traceback."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # Write 50 lines so we can test context extraction
            for i in range(1, 51):
                f.write(f"# Line {i}\n")
            f.flush()
            temp_path = f.name

        try:
            traceback = f'''Traceback (most recent call last):
  File "{temp_path}", line 25, in test_func
    result = do_something()
ValueError: test error'''

            context = get_file_context(traceback)

            # Should contain context from the file
            assert "Context from" in context
            assert "Line 25" in context
        finally:
            os.unlink(temp_path)

    def test_context_includes_surrounding_lines(self):
        """Test that +/- 20 lines are included around error."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            for i in range(1, 51):
                f.write(f"line_{i} = {i}\n")
            f.flush()
            temp_path = f.name

        try:
            traceback = f'''File "{temp_path}", line 25'''

            context = get_file_context(traceback)

            # Should include lines 5-45 (25 +/- 20)
            assert "line_5" in context
            assert "line_25" in context
            assert "line_45" in context
        finally:
            os.unlink(temp_path)

    def test_marks_error_line(self):
        """Test that the error line is marked with >>."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("line1\nline2\nline3\n")
            f.flush()
            temp_path = f.name

        try:
            traceback = f'''File "{temp_path}", line 2'''

            context = get_file_context(traceback)

            # Error line should be marked
            assert " >> " in context
            # Line should contain "2 |"
            assert "2 |" in context
        finally:
            os.unlink(temp_path)

    def test_returns_empty_for_missing_file(self):
        """Test that missing files return empty context."""
        traceback = '''File "/nonexistent/path/file.py", line 10'''

        context = get_file_context(traceback)

        assert context == ""

    def test_returns_empty_for_no_file_refs(self):
        """Test that logs without file references return empty."""
        error_log = "Something went wrong, no file info"

        context = get_file_context(error_log)

        assert context == ""

    def test_handles_multiple_files(self):
        """Test extraction from tracebacks with multiple files."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f1:
            f1.write("# file1 content\n" * 10)
            f1.flush()
            path1 = f1.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f2:
            f2.write("# file2 content\n" * 10)
            f2.flush()
            path2 = f2.name

        try:
            traceback = f'''Traceback (most recent call last):
  File "{path1}", line 5, in func1
    result = func2()
  File "{path2}", line 3, in func2
    return bad()
ValueError: test'''

            context = get_file_context(traceback)

            # Should have context from both files
            assert "file1 content" in context
            assert "file2 content" in context
        finally:
            os.unlink(path1)
            os.unlink(path2)
