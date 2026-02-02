"""Tests for import resolution and dependency tracing."""

import os
import tempfile
import pytest
from pathlib import Path

from roma_debug.core.models import Language, Import, FileContext
from roma_debug.tracing.import_resolver import ImportResolver
from roma_debug.tracing.dependency_graph import DependencyGraph
from roma_debug.tracing.call_chain import CallChainAnalyzer, CallChain
from roma_debug.tracing.context_builder import ContextBuilder


class TestImportResolver:
    """Tests for import resolution."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create directory structure
            src = Path(tmpdir) / "src"
            src.mkdir()

            # Create main.py
            (src / "main.py").write_text("""
from utils import helper
from .local import something
import os
""")

            # Create utils.py
            (src / "utils.py").write_text("""
def helper():
    return 42
""")

            # Create local.py
            (src / "local.py").write_text("""
something = "value"
""")

            # Create __init__.py
            (src / "__init__.py").write_text("")

            yield tmpdir

    def test_resolve_absolute_import(self, temp_project):
        """Test resolving absolute imports."""
        resolver = ImportResolver(temp_project)

        imp = Import(
            module_name="src.utils",
            language=Language.PYTHON,
        )

        resolved = resolver.resolve_import(imp, Path(temp_project) / "src" / "main.py")
        assert resolved.resolved_path is not None
        assert "utils.py" in resolved.resolved_path

    def test_resolve_relative_import(self, temp_project):
        """Test resolving relative imports."""
        resolver = ImportResolver(temp_project)

        imp = Import(
            module_name="local",
            is_relative=True,
            relative_level=1,
            language=Language.PYTHON,
        )

        resolved = resolver.resolve_import(imp, Path(temp_project) / "src" / "main.py")
        assert resolved.resolved_path is not None
        assert "local.py" in resolved.resolved_path

    def test_unresolvable_import(self, temp_project):
        """Test that unresolvable imports return None."""
        resolver = ImportResolver(temp_project)

        imp = Import(
            module_name="nonexistent_module",
            language=Language.PYTHON,
        )

        resolved = resolver.resolve_import(imp, Path(temp_project) / "src" / "main.py")
        assert resolved.resolved_path is None

    def test_caching(self, temp_project):
        """Test that resolved paths are cached."""
        resolver = ImportResolver(temp_project)

        imp = Import(
            module_name="src.utils",
            language=Language.PYTHON,
        )

        source = Path(temp_project) / "src" / "main.py"
        resolved1 = resolver.resolve_import(imp, source)
        resolved2 = resolver.resolve_import(imp, source)

        # Should be cached
        assert resolved1.resolved_path == resolved2.resolved_path


class TestDependencyGraph:
    """Tests for dependency graph building."""

    def test_add_file(self):
        """Test adding a file to the graph."""
        graph = DependencyGraph()

        imports = [
            Import(module_name="utils", resolved_path="/app/utils.py", language=Language.PYTHON),
        ]

        graph.add_file("/app/main.py", Language.PYTHON, imports)

        assert "/app/main.py" in graph.get_all_files() or any(
            "main.py" in f for f in graph.get_all_files()
        )

    def test_get_dependencies(self):
        """Test getting dependencies of a file."""
        graph = DependencyGraph()

        imports = [
            Import(module_name="utils", resolved_path="/app/utils.py", language=Language.PYTHON),
            Import(module_name="helpers", resolved_path="/app/helpers.py", language=Language.PYTHON),
        ]

        graph.add_file("/app/main.py", Language.PYTHON, imports)

        deps = graph.get_dependencies("/app/main.py")
        assert len(deps) == 2

    def test_get_dependents(self):
        """Test getting files that depend on a given file."""
        graph = DependencyGraph()

        # main.py imports utils.py
        graph.add_file("/app/main.py", Language.PYTHON, [
            Import(module_name="utils", resolved_path="/app/utils.py", language=Language.PYTHON),
        ])

        # other.py also imports utils.py
        graph.add_file("/app/other.py", Language.PYTHON, [
            Import(module_name="utils", resolved_path="/app/utils.py", language=Language.PYTHON),
        ])

        dependents = graph.get_dependents("/app/utils.py")
        assert len(dependents) == 2

    def test_transitive_dependencies(self):
        """Test getting transitive dependencies."""
        graph = DependencyGraph()

        # main -> utils -> helpers
        graph.add_file("/app/main.py", Language.PYTHON, [
            Import(module_name="utils", resolved_path="/app/utils.py", language=Language.PYTHON),
        ])
        graph.add_file("/app/utils.py", Language.PYTHON, [
            Import(module_name="helpers", resolved_path="/app/helpers.py", language=Language.PYTHON),
        ])

        transitive = graph.get_transitive_dependencies("/app/main.py")
        # Should include both utils.py and helpers.py
        assert len(transitive) == 2


class TestCallChainAnalyzer:
    """Tests for call chain analysis."""

    @pytest.fixture
    def sample_contexts(self):
        """Create sample file contexts."""
        return [
            FileContext(
                filepath="/app/main.py",
                line_number=10,
                context_type="ast",
                content="def main():\n    result = process()",
                function_name="main",
                language=Language.PYTHON,
            ),
            FileContext(
                filepath="/app/utils.py",
                line_number=25,
                context_type="ast",
                content="def process():\n    return compute()",
                function_name="process",
                language=Language.PYTHON,
            ),
        ]

    def test_analyze_from_contexts(self, sample_contexts):
        """Test building call chain from contexts."""
        analyzer = CallChainAnalyzer()
        chain = analyzer.analyze_from_contexts(sample_contexts)

        assert len(chain.sites) == 2
        assert chain.sites[0].function_name == "main"
        assert chain.sites[1].function_name == "process"

    def test_call_chain_string(self, sample_contexts):
        """Test call chain string representation."""
        analyzer = CallChainAnalyzer()
        chain = analyzer.analyze_from_contexts(sample_contexts)

        chain_str = str(chain)
        assert "main" in chain_str
        assert "process" in chain_str


class TestContextBuilder:
    """Tests for the context builder."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project with sample files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Python file
            main_py = Path(tmpdir) / "main.py"
            main_py.write_text("""
import utils

def main():
    result = utils.process(None)
    return result

if __name__ == "__main__":
    main()
""")

            utils_py = Path(tmpdir) / "utils.py"
            utils_py.write_text("""
def process(data):
    return data.strip()  # This will fail with None
""")

            yield tmpdir

    def test_build_context_from_python_traceback(self, temp_project):
        """Test building context from a Python traceback."""
        error_log = f'''
Traceback (most recent call last):
  File "{temp_project}/main.py", line 5, in main
    result = utils.process(None)
  File "{temp_project}/utils.py", line 3, in process
    return data.strip()
AttributeError: 'NoneType' object has no attribute 'strip'
'''
        builder = ContextBuilder(project_root=temp_project)
        ctx = builder.build_analysis_context(error_log)

        assert ctx.primary_context is not None
        assert ctx.primary_context.filepath.endswith("utils.py")
        assert len(ctx.traceback_contexts) >= 1

    def test_get_context_for_prompt(self, temp_project):
        """Test formatting context for AI prompt."""
        error_log = f'''
Traceback (most recent call last):
  File "{temp_project}/main.py", line 5, in main
    result = utils.process(None)
AttributeError: 'NoneType' object has no attribute 'strip'
'''
        builder = ContextBuilder(project_root=temp_project)
        ctx = builder.build_analysis_context(error_log)

        prompt = builder.get_context_for_prompt(ctx)

        assert "PRIMARY ERROR" in prompt
        assert "main.py" in prompt
        assert "Language:" in prompt


class TestUpstreamContext:
    """Tests for upstream context building."""

    def test_upstream_context_to_prompt(self):
        """Test formatting upstream context."""
        from roma_debug.core.models import UpstreamContext

        ctx = UpstreamContext(
            call_chain=["main.main", "utils.process", "compute.calc"],
            relevant_definitions={"helper": "def helper(): pass"},
            dependency_summary="3 files analyzed",
        )

        text = ctx.to_prompt_text()

        assert "CALL CHAIN" in text
        assert "main.main" in text
        assert "RELEVANT DEFINITIONS" in text
        assert "helper" in text
