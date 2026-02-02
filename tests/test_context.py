"""Tests for the context reader module."""

import os
import tempfile
import pytest

from roma_debug.utils.context import (
    get_file_context,
    get_primary_file,
    extract_context_v2,
    generate_file_tree,
    get_file_context_with_tree,
)
from roma_debug.core.models import Language


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

            context_str, contexts = get_file_context(traceback)

            # Should contain context from the file
            assert "Context from" in context_str
            assert "Line 25" in context_str
        finally:
            os.unlink(temp_path)

    def test_context_includes_surrounding_lines(self):
        """Test that +/- 50 lines are included around error."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            for i in range(1, 51):
                f.write(f"line_{i} = {i}\n")
            f.flush()
            temp_path = f.name

        try:
            traceback = f'''File "{temp_path}", line 25'''

            context_str, contexts = get_file_context(traceback)

            # Should include lines around line 25
            assert "line_5" in context_str
            assert "line_25" in context_str
            assert "line_45" in context_str
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

            context_str, contexts = get_file_context(traceback)

            # Error line should be marked
            assert " >> " in context_str
            # Line should contain "2 |"
            assert "2 |" in context_str
        finally:
            os.unlink(temp_path)

    def test_returns_empty_for_missing_file(self):
        """Test that missing files return empty context string (but still return context list)."""
        traceback = '''File "/nonexistent/path/file.py", line 10'''

        context_str, contexts = get_file_context(traceback)

        # Context string should mention the file is not found
        assert "not found" in context_str or context_str == ""
        # Should still have a context entry with type='missing'
        assert len(contexts) == 1
        assert contexts[0].context_type == "missing"

    def test_returns_empty_for_no_file_refs(self):
        """Test that logs without file references return empty."""
        error_log = "Something went wrong, no file info"

        context_str, contexts = get_file_context(error_log)

        assert context_str == ""
        assert contexts == []

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

            context_str, contexts = get_file_context(traceback)

            # Should have context from both files
            assert "file1 content" in context_str
            assert "file2 content" in context_str
            assert len(contexts) == 2
        finally:
            os.unlink(path1)
            os.unlink(path2)


class TestFileContextV2:
    """Tests for V2 context extraction with language support."""

    def test_context_has_language(self):
        """Test that FileContext includes language."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            f.flush()
            temp_path = f.name

        try:
            traceback = f'''File "{temp_path}", line 2'''
            _, contexts = get_file_context(traceback)

            assert len(contexts) == 1
            assert contexts[0].language == Language.PYTHON
        finally:
            os.unlink(temp_path)

    def test_get_primary_file(self):
        """Test get_primary_file returns the last non-missing context."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f1:
            f1.write("# file1\n" * 5)
            f1.flush()
            path1 = f1.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f2:
            f2.write("# file2\n" * 5)
            f2.flush()
            path2 = f2.name

        try:
            traceback = f'''File "{path1}", line 2
File "{path2}", line 3'''
            _, contexts = get_file_context(traceback)

            primary = get_primary_file(contexts)
            assert primary is not None
            assert path2 in primary.filepath
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_v2_context_extraction(self):
        """Test extract_context_v2 returns V2 FileContext objects."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("import os\n\ndef main():\n    pass\n")
            f.flush()
            temp_path = f.name

        try:
            traceback = f'''File "{temp_path}", line 3'''
            _, contexts = extract_context_v2(traceback)

            assert len(contexts) == 1
            # V2 context should have to_dict method
            assert hasattr(contexts[0], 'to_dict')
        finally:
            os.unlink(temp_path)

    def test_ast_extraction_with_function(self):
        """Test AST extraction identifies function names."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
def my_function():
    x = 1
    y = 2
    return x + y
""")
            f.flush()
            temp_path = f.name

        try:
            traceback = f'''File "{temp_path}", line 4, in my_function'''
            _, contexts = get_file_context(traceback)

            assert len(contexts) == 1
            assert contexts[0].function_name == "my_function"
            assert contexts[0].context_type == "ast"
        finally:
            os.unlink(temp_path)


class TestFileTreeGeneration:
    """Tests for file tree generation utilities."""

    def test_generate_file_tree_from_context(self):
        """Test generate_file_tree function from utils.context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(f"{tmpdir}/src")
            with open(f"{tmpdir}/src/app.py", "w") as f:
                f.write("# app")
            with open(f"{tmpdir}/main.py", "w") as f:
                f.write("# main")

            # Change to the temp dir and generate tree
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                tree = generate_file_tree()

                assert "src/" in tree
                assert "app.py" in tree
                assert "main.py" in tree
            finally:
                os.chdir(original_cwd)

    def test_generate_file_tree_with_explicit_root(self):
        """Test generate_file_tree with explicit project root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(f"{tmpdir}/test.py", "w") as f:
                f.write("# test")

            tree = generate_file_tree(project_root=tmpdir)

            assert "test.py" in tree

    def test_get_file_context_with_tree(self):
        """Test get_file_context_with_tree includes both context and tree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(f"{tmpdir}/src")
            with open(f"{tmpdir}/src/app.py", "w") as f:
                f.write("def hello():\n    return 'world'\n")

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                traceback = f'''File "src/app.py", line 2'''
                context_str, contexts = get_file_context_with_tree(traceback)

                # Should include ProjectStructure section
                assert "<ProjectStructure>" in context_str
                assert "</ProjectStructure>" in context_str

                # Should include file tree
                assert "PROJECT FILE TREE" in context_str
                assert "src/" in context_str

                # Should include source context
                assert "SOURCE CONTEXT" in context_str

                # Should still have FileContext objects
                assert len(contexts) == 1
            finally:
                os.chdir(original_cwd)

    def test_file_tree_in_context_helps_path_verification(self):
        """Test that file tree includes instructional text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(f"{tmpdir}/server.py", "w") as f:
                f.write("# server code")

            tree = generate_file_tree(project_root=tmpdir)

            # Tree should be parseable (has proper structure)
            lines = tree.split('\n')
            assert len(lines) > 0
            # Should have the project root name
            assert lines[0].endswith('/')

    def test_context_with_tree_handles_no_traceback(self):
        """Test get_file_context_with_tree handles errors without file refs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(f"{tmpdir}/app.py", "w") as f:
                f.write("# app")

            error_log = "Cannot GET /index.html"  # No file reference

            context_str, contexts = get_file_context_with_tree(
                error_log,
                project_root=tmpdir
            )

            # Should still include the file tree for context
            assert "<ProjectStructure>" in context_str
            assert "app.py" in context_str

            # But no file contexts
            assert contexts == []
