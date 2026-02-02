"""Dependency graph builder for project analysis.

Builds a graph of module dependencies for understanding code relationships.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Set

from roma_debug.core.models import Language, Import, FileContext


@dataclass
class DependencyNode:
    """A node in the dependency graph representing a file/module."""
    filepath: str
    language: Language
    imports: List[Import] = field(default_factory=list)
    imported_by: List[str] = field(default_factory=list)  # Files that import this one
    symbols: List[str] = field(default_factory=list)  # Exported symbols

    @property
    def filename(self) -> str:
        return Path(self.filepath).name

    @property
    def module_name(self) -> str:
        """Derive module name from filepath."""
        path = Path(self.filepath)
        # Remove extension and convert to module format
        stem = path.stem
        if stem == '__init__':
            return path.parent.name
        return stem


class DependencyGraph:
    """Graph of module dependencies in a project.

    Tracks which files import which other files, allowing us to:
    - Find all files that depend on a given file
    - Find all dependencies of a file
    - Identify potential root cause locations
    """

    def __init__(self, project_root: Optional[str] = None):
        """Initialize the dependency graph.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._nodes: Dict[str, DependencyNode] = {}
        self._edges: Dict[str, Set[str]] = defaultdict(set)  # from -> to
        self._reverse_edges: Dict[str, Set[str]] = defaultdict(set)  # to -> from

    def add_file(self, filepath: str, language: Language, imports: List[Import]):
        """Add a file to the dependency graph.

        Args:
            filepath: Path to the file
            language: Language of the file
            imports: List of imports from the file
        """
        filepath = str(Path(filepath).resolve())

        if filepath not in self._nodes:
            self._nodes[filepath] = DependencyNode(
                filepath=filepath,
                language=language,
            )

        node = self._nodes[filepath]
        node.imports = imports

        # Add edges for resolved imports
        for imp in imports:
            if imp.resolved_path:
                resolved = str(Path(imp.resolved_path).resolve())
                self._edges[filepath].add(resolved)
                self._reverse_edges[resolved].add(filepath)

                # Ensure the target node exists
                if resolved not in self._nodes:
                    # Infer language from extension
                    target_lang = Language.from_extension(Path(resolved).suffix)
                    self._nodes[resolved] = DependencyNode(
                        filepath=resolved,
                        language=target_lang,
                    )

                # Update imported_by
                self._nodes[resolved].imported_by.append(filepath)

    def add_file_context(self, context: FileContext):
        """Add a FileContext to the graph.

        Args:
            context: FileContext object with imports
        """
        self.add_file(context.filepath, context.language, context.imports)

    def get_dependencies(self, filepath: str) -> List[str]:
        """Get all files that the given file imports.

        Args:
            filepath: Path to the file

        Returns:
            List of file paths that are imported
        """
        filepath = str(Path(filepath).resolve())
        return list(self._edges.get(filepath, set()))

    def get_dependents(self, filepath: str) -> List[str]:
        """Get all files that import the given file.

        Args:
            filepath: Path to the file

        Returns:
            List of file paths that import this file
        """
        filepath = str(Path(filepath).resolve())
        return list(self._reverse_edges.get(filepath, set()))

    def get_transitive_dependencies(self, filepath: str, max_depth: int = 10) -> List[str]:
        """Get all transitive dependencies of a file.

        Args:
            filepath: Path to the file
            max_depth: Maximum recursion depth

        Returns:
            List of all files that the given file depends on (directly or indirectly)
        """
        filepath = str(Path(filepath).resolve())
        visited = set()
        result = []

        def visit(path: str, depth: int):
            if depth > max_depth or path in visited:
                return
            visited.add(path)

            for dep in self._edges.get(path, set()):
                if dep not in visited:
                    result.append(dep)
                    visit(dep, depth + 1)

        visit(filepath, 0)
        return result

    def get_transitive_dependents(self, filepath: str, max_depth: int = 10) -> List[str]:
        """Get all files that transitively depend on the given file.

        Args:
            filepath: Path to the file
            max_depth: Maximum recursion depth

        Returns:
            List of all files that depend on this file (directly or indirectly)
        """
        filepath = str(Path(filepath).resolve())
        visited = set()
        result = []

        def visit(path: str, depth: int):
            if depth > max_depth or path in visited:
                return
            visited.add(path)

            for dep in self._reverse_edges.get(path, set()):
                if dep not in visited:
                    result.append(dep)
                    visit(dep, depth + 1)

        visit(filepath, 0)
        return result

    def get_path_between(self, source: str, target: str) -> Optional[List[str]]:
        """Find the import path between two files.

        Args:
            source: Starting file
            target: Target file

        Returns:
            List of files forming the path, or None if no path exists
        """
        source = str(Path(source).resolve())
        target = str(Path(target).resolve())

        if source == target:
            return [source]

        # BFS to find shortest path
        visited = {source}
        queue = [(source, [source])]

        while queue:
            current, path = queue.pop(0)

            for neighbor in self._edges.get(current, set()):
                if neighbor == target:
                    return path + [neighbor]

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def find_common_dependencies(self, files: List[str]) -> List[str]:
        """Find files that are imported by all given files.

        Args:
            files: List of file paths

        Returns:
            List of files that are common dependencies
        """
        if not files:
            return []

        # Get dependencies of first file
        common = set(self.get_transitive_dependencies(files[0]))

        # Intersect with dependencies of other files
        for filepath in files[1:]:
            deps = set(self.get_transitive_dependencies(filepath))
            common &= deps

        return list(common)

    def get_node(self, filepath: str) -> Optional[DependencyNode]:
        """Get the node for a file.

        Args:
            filepath: Path to the file

        Returns:
            DependencyNode or None
        """
        filepath = str(Path(filepath).resolve())
        return self._nodes.get(filepath)

    def get_all_files(self) -> List[str]:
        """Get all files in the graph.

        Returns:
            List of all file paths
        """
        return list(self._nodes.keys())

    def get_summary(self) -> str:
        """Get a text summary of the dependency graph.

        Returns:
            Human-readable summary string
        """
        lines = [
            f"Dependency Graph Summary:",
            f"  Files: {len(self._nodes)}",
            f"  Direct Dependencies: {sum(len(deps) for deps in self._edges.values())}",
        ]

        # Top imported files
        import_counts = [(f, len(deps)) for f, deps in self._reverse_edges.items()]
        import_counts.sort(key=lambda x: x[1], reverse=True)

        if import_counts:
            lines.append("\n  Most Imported Files:")
            for filepath, count in import_counts[:5]:
                lines.append(f"    {Path(filepath).name}: imported by {count} files")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize the graph to a dictionary.

        Returns:
            Dictionary representation of the graph
        """
        return {
            "project_root": str(self.project_root),
            "nodes": {
                path: {
                    "filepath": node.filepath,
                    "language": node.language.value,
                    "imports": [imp.module_name for imp in node.imports],
                    "imported_by": node.imported_by,
                }
                for path, node in self._nodes.items()
            },
            "edges": {k: list(v) for k, v in self._edges.items()},
        }
