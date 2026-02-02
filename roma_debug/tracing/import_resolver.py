"""Import resolution for multiple languages.

Resolves import statements to actual file paths on disk.
"""

import os
import sys
from pathlib import Path
from typing import Optional, List, Dict

from roma_debug.core.models import Language, Import


class ImportResolver:
    """Resolves import statements to file paths.

    Handles import resolution for Python, JavaScript/TypeScript, and Go.
    """

    def __init__(self, project_root: Optional[str] = None):
        """Initialize the resolver.

        Args:
            project_root: Root directory of the project for relative imports
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._cache: Dict[str, Optional[str]] = {}

    def resolve_imports(
        self,
        imports: List[Import],
        source_file: Path,
    ) -> List[Import]:
        """Resolve a list of imports to file paths.

        Args:
            imports: List of Import objects
            source_file: Path to the file containing the imports

        Returns:
            List of Import objects with resolved_path populated
        """
        resolved = []
        for imp in imports:
            resolved_imp = self.resolve_import(imp, source_file)
            resolved.append(resolved_imp)
        return resolved

    def resolve_import(self, imp: Import, source_file: Path) -> Import:
        """Resolve a single import to a file path.

        Args:
            imp: Import object to resolve
            source_file: Path to the file containing the import

        Returns:
            Import object with resolved_path populated (may be None if not found)
        """
        # Create a copy to avoid mutating the original
        resolved = Import(
            module_name=imp.module_name,
            alias=imp.alias,
            imported_names=imp.imported_names.copy(),
            is_relative=imp.is_relative,
            relative_level=imp.relative_level,
            line_number=imp.line_number,
            resolved_path=None,
            language=imp.language,
        )

        # Use cache if available
        cache_key = f"{imp.language.value}:{source_file}:{imp.module_name}:{imp.relative_level}"
        if cache_key in self._cache:
            resolved.resolved_path = self._cache[cache_key]
            return resolved

        # Resolve based on language
        if imp.language == Language.PYTHON:
            path = self._resolve_python_import(imp, source_file)
        elif imp.language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            path = self._resolve_js_import(imp, source_file)
        elif imp.language == Language.GO:
            path = self._resolve_go_import(imp, source_file)
        else:
            path = None

        resolved.resolved_path = path
        self._cache[cache_key] = path
        return resolved

    def _resolve_python_import(self, imp: Import, source_file: Path) -> Optional[str]:
        """Resolve a Python import to a file path.

        Handles:
        - Absolute imports: import foo, from foo import bar
        - Relative imports: from . import bar, from ..foo import bar
        - Package imports: import foo.bar.baz

        Args:
            imp: Import object
            source_file: Path to source file

        Returns:
            Resolved file path or None
        """
        if imp.is_relative:
            return self._resolve_python_relative_import(imp, source_file)
        return self._resolve_python_absolute_import(imp)

    def _resolve_python_relative_import(self, imp: Import, source_file: Path) -> Optional[str]:
        """Resolve a Python relative import."""
        source_dir = source_file.parent

        # Go up directories based on relative level
        # level 1 = current package (.), level 2 = parent package (..), etc.
        target_dir = source_dir
        for _ in range(imp.relative_level - 1):
            target_dir = target_dir.parent

        # Now resolve the module name from this directory
        if imp.module_name:
            parts = imp.module_name.split('.')
            target_path = target_dir / '/'.join(parts)
        else:
            target_path = target_dir

        # Check for module file or package
        candidates = [
            target_path.with_suffix('.py'),
            target_path / '__init__.py',
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return None

    def _resolve_python_absolute_import(self, imp: Import) -> Optional[str]:
        """Resolve a Python absolute import."""
        parts = imp.module_name.split('.')

        # Check in project root first
        project_path = self.project_root / '/'.join(parts)
        candidates = [
            project_path.with_suffix('.py'),
            project_path / '__init__.py',
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        # Check common source directories
        src_dirs = ['src', 'lib', 'app', '.']
        for src_dir in src_dirs:
            base = self.project_root / src_dir
            if not base.exists():
                continue

            target_path = base / '/'.join(parts)
            candidates = [
                target_path.with_suffix('.py'),
                target_path / '__init__.py',
            ]

            for candidate in candidates:
                if candidate.exists():
                    return str(candidate)

        # Check in sys.path (installed packages - skip for now as they're external)
        # We focus on local project files for debugging

        return None

    def _resolve_js_import(self, imp: Import, source_file: Path) -> Optional[str]:
        """Resolve a JavaScript/TypeScript import to a file path.

        Handles:
        - Relative imports: ./foo, ../bar
        - Absolute imports from project root
        - Index files

        Args:
            imp: Import object
            source_file: Path to source file

        Returns:
            Resolved file path or None
        """
        module = imp.module_name

        # Skip npm packages (don't start with . or /)
        if not module.startswith('.') and not module.startswith('/'):
            # Could be an npm package or alias, skip for now
            return None

        source_dir = source_file.parent

        if module.startswith('./') or module.startswith('../'):
            # Relative import
            target = (source_dir / module).resolve()
        elif module.startswith('/'):
            # Absolute from project root
            target = self.project_root / module.lstrip('/')
        else:
            return None

        # Try various extensions
        extensions = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '']
        for ext in extensions:
            candidate = Path(str(target) + ext)
            if candidate.exists() and candidate.is_file():
                return str(candidate)

        # Try index files
        index_names = ['index.ts', 'index.tsx', 'index.js', 'index.jsx']
        for index_name in index_names:
            candidate = target / index_name
            if candidate.exists():
                return str(candidate)

        return None

    def _resolve_go_import(self, imp: Import, source_file: Path) -> Optional[str]:
        """Resolve a Go import to a file path.

        Go imports are package paths. We look for local packages
        relative to the project root.

        Args:
            imp: Import object
            source_file: Path to source file

        Returns:
            Resolved file path or None (returns directory for Go packages)
        """
        module = imp.module_name

        # Skip standard library and external packages
        if not module.startswith('.') and '/' not in module:
            return None  # Standard library

        # Check if it's a local package
        # Look for go.mod to find module path
        go_mod = self._find_go_mod()
        if go_mod:
            module_path = self._get_go_module_path(go_mod)
            if module_path and module.startswith(module_path):
                # Local package
                relative_path = module[len(module_path):].lstrip('/')
                package_dir = self.project_root / relative_path
                if package_dir.exists() and package_dir.is_dir():
                    # Return directory path (Go packages are directories)
                    # Find the first .go file
                    go_files = list(package_dir.glob('*.go'))
                    if go_files:
                        return str(go_files[0])
                    return str(package_dir)

        # Try relative to project root
        parts = module.split('/')
        # Skip first part if it looks like a domain
        if '.' in parts[0]:
            parts = parts[1:]

        package_dir = self.project_root / '/'.join(parts)
        if package_dir.exists() and package_dir.is_dir():
            go_files = list(package_dir.glob('*.go'))
            if go_files:
                return str(go_files[0])

        return None

    def _find_go_mod(self) -> Optional[Path]:
        """Find go.mod file in project."""
        go_mod = self.project_root / 'go.mod'
        if go_mod.exists():
            return go_mod
        return None

    def _get_go_module_path(self, go_mod: Path) -> Optional[str]:
        """Extract module path from go.mod."""
        try:
            content = go_mod.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('module '):
                    return line[7:].strip()
        except Exception:
            pass
        return None

    def clear_cache(self):
        """Clear the resolution cache."""
        self._cache.clear()


def resolve_import(
    imp: Import,
    source_file: str,
    project_root: Optional[str] = None,
) -> Import:
    """Convenience function to resolve a single import.

    Args:
        imp: Import object to resolve
        source_file: Path to the file containing the import
        project_root: Optional project root directory

    Returns:
        Import with resolved_path populated
    """
    resolver = ImportResolver(project_root)
    return resolver.resolve_import(imp, Path(source_file))
