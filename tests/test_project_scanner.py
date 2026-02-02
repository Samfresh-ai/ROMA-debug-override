"""Tests for the project scanner and error analyzer."""

import os
import tempfile
import pytest

from roma_debug.core.models import Language
from roma_debug.tracing.project_scanner import ProjectScanner, ProjectInfo, ProjectFile
from roma_debug.tracing.error_analyzer import ErrorAnalyzer, ErrorAnalysis


class TestProjectScanner:
    """Tests for ProjectScanner."""

    def test_scan_python_project(self):
        """Test scanning a Python project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple Python project
            os.makedirs(f"{tmpdir}/src")

            with open(f"{tmpdir}/app.py", "w") as f:
                f.write("""
from flask import Flask
app = Flask(__name__)

@app.route('/')
def index():
    return 'Hello'
""")

            with open(f"{tmpdir}/src/utils.py", "w") as f:
                f.write("""
def helper():
    return 42
""")

            with open(f"{tmpdir}/requirements.txt", "w") as f:
                f.write("flask\n")

            scanner = ProjectScanner(tmpdir)
            info = scanner.scan()

            assert info.project_type == "flask"
            assert info.primary_language == Language.PYTHON
            assert "flask" in info.frameworks_detected
            assert len(info.entry_points) >= 1
            assert any("app.py" in ep.path for ep in info.entry_points)
            assert len(info.config_files) >= 1

    def test_scan_javascript_project(self):
        """Test scanning a JavaScript project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(f"{tmpdir}/index.js", "w") as f:
                f.write("""
const express = require('express');
const app = express();

app.get('/', (req, res) => {
    res.send('Hello');
});
""")

            with open(f"{tmpdir}/package.json", "w") as f:
                f.write('{"name": "test", "dependencies": {"express": "^4.0.0"}}')

            scanner = ProjectScanner(tmpdir)
            info = scanner.scan()

            assert info.project_type == "express"
            assert info.primary_language == Language.JAVASCRIPT
            assert "express" in info.frameworks_detected
            assert len(info.entry_points) >= 1

    def test_find_relevant_files_http_error(self):
        """Test finding relevant files from HTTP error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(f"{tmpdir}/app.py", "w") as f:
                f.write("""
from flask import Flask
app = Flask(__name__)
""")

            with open(f"{tmpdir}/routes.py", "w") as f:
                f.write("""
from app import app

@app.route('/api/users')
def users():
    return []
""")

            scanner = ProjectScanner(tmpdir)
            scanner.scan()

            relevant = scanner.find_relevant_files("Cannot GET /index.html")

            # Should find app.py and routes.py as relevant
            paths = [f.path for f in relevant]
            assert any("app" in p for p in paths) or any("route" in p for p in paths)

    def test_project_summary(self):
        """Test project summary generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(f"{tmpdir}/main.py", "w") as f:
                f.write("print('hello')")

            scanner = ProjectScanner(tmpdir)
            info = scanner.scan()

            summary = info.to_summary()
            assert "Project Type:" in summary
            assert "Primary Language:" in summary

    def test_skip_directories(self):
        """Test that node_modules and similar are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(f"{tmpdir}/node_modules/lodash")
            os.makedirs(f"{tmpdir}/src")

            with open(f"{tmpdir}/src/app.js", "w") as f:
                f.write("console.log('app');")

            with open(f"{tmpdir}/node_modules/lodash/index.js", "w") as f:
                f.write("module.exports = {};")

            scanner = ProjectScanner(tmpdir)
            info = scanner.scan()

            # Should not include node_modules files
            paths = [f.path for f in info.source_files]
            assert not any("node_modules" in p for p in paths)
            assert any("app.js" in p for p in paths)


class TestErrorAnalyzer:
    """Tests for ErrorAnalyzer."""

    def test_analyze_http_404_error(self):
        """Test analyzing HTTP 404 error."""
        analyzer = ErrorAnalyzer()
        analysis = analyzer.analyze("Cannot GET /index.html")

        assert analysis.error_type == "http"
        assert analysis.error_category == "http_404"
        assert "/index.html" in analysis.affected_routes

    def test_analyze_python_import_error(self):
        """Test analyzing Python import error."""
        analyzer = ErrorAnalyzer()
        analysis = analyzer.analyze("ModuleNotFoundError: No module named 'flask'")

        assert analysis.error_type == "import"
        assert analysis.error_category == "python_import"
        assert analysis.suggested_language == Language.PYTHON

    def test_analyze_javascript_error(self):
        """Test analyzing JavaScript error."""
        analyzer = ErrorAnalyzer()
        # Use a more distinctly JavaScript error message
        analysis = analyzer.analyze("ReferenceError: myVariable is not defined\n    at Object.<anonymous> (/app/index.js:10:5)")

        assert analysis.error_type == "runtime"
        assert analysis.error_category == "js_reference"
        assert analysis.suggested_language == Language.JAVASCRIPT

    def test_analyze_config_error(self):
        """Test analyzing configuration error."""
        analyzer = ErrorAnalyzer()
        analysis = analyzer.analyze("API key not valid. Please check your API key.")

        assert analysis.error_type == "config"
        assert analysis.error_category == "config"

    def test_extract_routes(self):
        """Test route extraction from error."""
        analyzer = ErrorAnalyzer()
        analysis = analyzer.analyze("Cannot GET /api/users/123")

        assert "/api/users/123" in analysis.affected_routes

    def test_with_project_scanner(self):
        """Test error analyzer with project scanner."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(f"{tmpdir}/server.py", "w") as f:
                f.write("""
from flask import Flask, send_from_directory
app = Flask(__name__, static_folder='static')
""")

            scanner = ProjectScanner(tmpdir)
            analyzer = ErrorAnalyzer(scanner)

            analysis = analyzer.analyze("Cannot GET /index.html")

            # Should find server.py as relevant
            assert len(analysis.relevant_files) > 0

    def test_get_fix_context(self):
        """Test getting comprehensive fix context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(f"{tmpdir}/app.py", "w") as f:
                f.write("""
from flask import Flask
app = Flask(__name__)
""")

            scanner = ProjectScanner(tmpdir)
            analyzer = ErrorAnalyzer(scanner)

            context = analyzer.get_fix_context(
                "Cannot GET /index.html",
                include_project_structure=True,
                include_file_contents=True,
            )

            assert "ERROR ANALYSIS" in context
            assert "PROJECT STRUCTURE" in context

    def test_error_confidence(self):
        """Test error detection confidence."""
        analyzer = ErrorAnalyzer()

        # High confidence for specific error
        analysis = analyzer.analyze("ModuleNotFoundError: No module named 'flask'")
        assert analysis.confidence >= 0.9

        # Lower confidence for vague error
        analysis = analyzer.analyze("Something went wrong")
        assert analysis.confidence < 0.5


class TestFileTreeGenerator:
    """Tests for the file tree generator."""

    def test_generate_basic_tree(self):
        """Test basic file tree generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple project structure
            os.makedirs(f"{tmpdir}/src")
            os.makedirs(f"{tmpdir}/tests")

            with open(f"{tmpdir}/app.py", "w") as f:
                f.write("# main app")
            with open(f"{tmpdir}/src/utils.py", "w") as f:
                f.write("# utils")
            with open(f"{tmpdir}/tests/test_app.py", "w") as f:
                f.write("# tests")

            scanner = ProjectScanner(tmpdir)
            tree = scanner.generate_file_tree()

            # Should contain root and files
            assert "app.py" in tree
            assert "src/" in tree
            assert "utils.py" in tree
            assert "tests/" in tree
            assert "test_app.py" in tree

    def test_tree_respects_skip_dirs(self):
        """Test that tree skips node_modules, __pycache__, etc."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(f"{tmpdir}/node_modules/lodash")
            os.makedirs(f"{tmpdir}/__pycache__")
            os.makedirs(f"{tmpdir}/src")

            with open(f"{tmpdir}/src/app.py", "w") as f:
                f.write("# app")
            with open(f"{tmpdir}/node_modules/lodash/index.js", "w") as f:
                f.write("// lodash")
            with open(f"{tmpdir}/__pycache__/app.cpython-39.pyc", "w") as f:
                f.write("# bytecode")

            scanner = ProjectScanner(tmpdir)
            tree = scanner.generate_file_tree()

            # Should NOT contain skipped directories
            assert "node_modules" not in tree
            assert "__pycache__" not in tree
            # Should contain source files
            assert "src/" in tree
            assert "app.py" in tree

    def test_tree_respects_gitignore(self):
        """Test that tree respects .gitignore patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(f"{tmpdir}/build")
            os.makedirs(f"{tmpdir}/src")

            # Create .gitignore
            with open(f"{tmpdir}/.gitignore", "w") as f:
                f.write("build/\n*.log\n")

            with open(f"{tmpdir}/src/app.py", "w") as f:
                f.write("# app")
            with open(f"{tmpdir}/build/output.js", "w") as f:
                f.write("// build output")
            with open(f"{tmpdir}/debug.log", "w") as f:
                f.write("log content")

            scanner = ProjectScanner(tmpdir)
            tree = scanner.generate_file_tree()

            # Should NOT contain gitignored items
            assert "build" not in tree
            assert "debug.log" not in tree
            # Should contain non-ignored files
            assert "src/" in tree
            assert "app.py" in tree

    def test_tree_max_depth(self):
        """Test that tree respects max depth."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create deep directory structure
            deep_path = f"{tmpdir}/a/b/c/d/e"
            os.makedirs(deep_path)

            with open(f"{tmpdir}/a/b/c/d/e/deep.py", "w") as f:
                f.write("# deep file")
            with open(f"{tmpdir}/a/shallow.py", "w") as f:
                f.write("# shallow file")

            scanner = ProjectScanner(tmpdir)

            # With depth 2, should not see deep files
            tree = scanner.generate_file_tree(max_depth=2)
            assert "shallow.py" in tree
            assert "deep.py" not in tree

            # With depth 6, should see everything
            tree = scanner.generate_file_tree(max_depth=6)
            assert "deep.py" in tree

    def test_tree_truncation(self):
        """Test that tree truncates when too many files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create many files
            for i in range(30):
                with open(f"{tmpdir}/file_{i:02d}.py", "w") as f:
                    f.write(f"# file {i}")

            scanner = ProjectScanner(tmpdir)
            tree = scanner.generate_file_tree(max_files_per_dir=10)

            # Should show truncation indicator
            assert "more items" in tree

    def test_tree_structure_formatting(self):
        """Test that tree uses proper connectors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(f"{tmpdir}/src")

            with open(f"{tmpdir}/src/a.py", "w") as f:
                f.write("# a")
            with open(f"{tmpdir}/src/b.py", "w") as f:
                f.write("# b")
            with open(f"{tmpdir}/readme.md", "w") as f:
                f.write("# readme")

            scanner = ProjectScanner(tmpdir)
            tree = scanner.generate_file_tree()

            # Should have tree connectors
            assert "├──" in tree or "└──" in tree


class TestIntegration:
    """Integration tests for project scanner + error analyzer."""

    def test_flask_static_file_error(self):
        """Test analyzing Flask static file error with project context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Flask project structure
            os.makedirs(f"{tmpdir}/static")
            os.makedirs(f"{tmpdir}/templates")

            with open(f"{tmpdir}/app.py", "w") as f:
                f.write("""
from flask import Flask, render_template, send_from_directory
import os

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
""")

            with open(f"{tmpdir}/templates/index.html", "w") as f:
                f.write("<html><body>Hello</body></html>")

            scanner = ProjectScanner(tmpdir)
            analyzer = ErrorAnalyzer(scanner)

            # Analyze a static file error
            analysis = analyzer.analyze("Cannot GET /index.html")

            # Should identify as HTTP error
            assert analysis.error_type == "http"

            # Should find app.py as relevant
            relevant_paths = [f.path for f in analysis.relevant_files]
            assert any("app" in p for p in relevant_paths)

            # Context should include file contents
            context = analyzer.get_fix_context("Cannot GET /index.html")
            assert "flask" in context.lower() or "Flask" in context
