"""ROMA Debug Tracing - Import resolution, dependency analysis, and project awareness.

This package provides tools for:
- Tracing imports and building dependency graphs
- Scanning and understanding project structure
- Analyzing errors to find relevant files
- Deep debugging across files
"""

from roma_debug.tracing.import_resolver import ImportResolver, resolve_import
from roma_debug.tracing.dependency_graph import DependencyGraph
from roma_debug.tracing.call_chain import CallChainAnalyzer
from roma_debug.tracing.context_builder import ContextBuilder
from roma_debug.tracing.project_scanner import ProjectScanner, ProjectInfo, ProjectFile
from roma_debug.tracing.error_analyzer import ErrorAnalyzer, ErrorAnalysis

__all__ = [
    "ImportResolver",
    "resolve_import",
    "DependencyGraph",
    "CallChainAnalyzer",
    "ContextBuilder",
    "ProjectScanner",
    "ProjectInfo",
    "ProjectFile",
    "ErrorAnalyzer",
    "ErrorAnalysis",
]
