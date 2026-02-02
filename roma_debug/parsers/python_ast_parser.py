"""Python AST-based parser implementation.

Uses Python's built-in ast module for parsing Python source code.
This is the legacy fallback parser that provides reliable Python parsing.
"""

import ast
from typing import Optional, List

from roma_debug.core.models import Language, Symbol, Import
from roma_debug.parsers.base import BaseParser


class PythonAstParser(BaseParser):
    """Python parser using the built-in ast module.

    This parser provides reliable Python parsing using Python's own
    AST module. It's used as the primary Python parser and as a
    fallback when tree-sitter is unavailable.
    """

    def __init__(self):
        """Initialize the Python AST parser."""
        super().__init__()
        self._tree: Optional[ast.AST] = None
        self._symbols: List[Symbol] = []
        self._imports: List[Import] = []

    @property
    def language(self) -> Language:
        """Return Python as the language."""
        return Language.PYTHON

    def parse(self, source: str, filepath: str = "") -> bool:
        """Parse Python source code using ast.

        Args:
            source: Python source code
            filepath: Optional file path

        Returns:
            True if parsing succeeded
        """
        self.reset()
        self._source = source
        self._filepath = filepath
        self._lines = source.splitlines()

        try:
            self._tree = ast.parse(source)
            self._parsed = True
            self._extract_symbols()
            self._extract_imports_internal()
            return True
        except SyntaxError:
            return False

    def reset(self):
        """Reset parser state."""
        super().reset()
        self._tree = None
        self._symbols = []
        self._imports = []

    def _extract_symbols(self):
        """Extract all function and class symbols from the AST."""
        if self._tree is None:
            return

        def visit_node(node: ast.AST, parent: Optional[Symbol] = None):
            symbol = None

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                if parent and parent.kind == "class":
                    kind = "method"

                # Extract decorators
                decorators = []
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        decorators.append(dec.id)
                    elif isinstance(dec, ast.Attribute):
                        decorators.append(ast.unparse(dec) if hasattr(ast, 'unparse') else str(dec.attr))
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name):
                            decorators.append(dec.func.id)
                        elif isinstance(dec.func, ast.Attribute):
                            decorators.append(dec.func.attr)

                # Extract docstring
                docstring = ast.get_docstring(node)

                symbol = Symbol(
                    name=node.name,
                    kind=kind,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    start_col=node.col_offset,
                    end_col=node.end_col_offset or 0,
                    parent=parent,
                    decorators=decorators,
                    docstring=docstring,
                )
                self._symbols.append(symbol)

            elif isinstance(node, ast.ClassDef):
                # Extract decorators
                decorators = []
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        decorators.append(dec.id)
                    elif isinstance(dec, ast.Attribute):
                        decorators.append(ast.unparse(dec) if hasattr(ast, 'unparse') else str(dec.attr))

                # Extract docstring
                docstring = ast.get_docstring(node)

                symbol = Symbol(
                    name=node.name,
                    kind="class",
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    start_col=node.col_offset,
                    end_col=node.end_col_offset or 0,
                    parent=parent,
                    decorators=decorators,
                    docstring=docstring,
                )
                self._symbols.append(symbol)

            # Visit children
            new_parent = symbol if symbol else parent
            for child in ast.iter_child_nodes(node):
                visit_node(child, new_parent)

        visit_node(self._tree)

    def _extract_imports_internal(self):
        """Extract import statements from the AST."""
        if self._tree is None:
            return

        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._imports.append(Import(
                        module_name=alias.name,
                        alias=alias.asname,
                        imported_names=[],
                        is_relative=False,
                        relative_level=0,
                        line_number=node.lineno,
                        language=Language.PYTHON,
                    ))

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported_names = [alias.name for alias in node.names]
                aliases = {alias.name: alias.asname for alias in node.names if alias.asname}

                self._imports.append(Import(
                    module_name=module,
                    alias=None,
                    imported_names=imported_names,
                    is_relative=node.level > 0,
                    relative_level=node.level,
                    line_number=node.lineno,
                    language=Language.PYTHON,
                ))

    def find_enclosing_symbol(self, line_number: int) -> Optional[Symbol]:
        """Find the innermost symbol containing the given line.

        Args:
            line_number: 1-based line number

        Returns:
            The innermost Symbol containing the line, or None
        """
        best_match: Optional[Symbol] = None
        best_size = float('inf')

        for symbol in self._symbols:
            if symbol.contains_line(line_number):
                size = symbol.end_line - symbol.start_line
                if size < best_size:
                    best_match = symbol
                    best_size = size

        return best_match

    def extract_imports(self) -> List[Import]:
        """Return all extracted imports.

        Returns:
            List of Import objects
        """
        return self._imports.copy()

    def find_all_symbols(self) -> List[Symbol]:
        """Return all extracted symbols.

        Returns:
            List of all Symbol objects
        """
        return self._symbols.copy()

    def find_symbols_by_name(self, name: str) -> List[Symbol]:
        """Find all symbols with the given name.

        Args:
            name: Symbol name to search for

        Returns:
            List of matching Symbol objects
        """
        return [s for s in self._symbols if s.name == name]

    def find_symbols_by_kind(self, kind: str) -> List[Symbol]:
        """Find all symbols of a given kind.

        Args:
            kind: Symbol kind ('function', 'class', 'method', etc.)

        Returns:
            List of matching Symbol objects
        """
        return [s for s in self._symbols if s.kind == kind]

    def get_function_calls_in_symbol(self, symbol: Symbol) -> List[str]:
        """Extract function/method calls within a symbol.

        Args:
            symbol: The symbol to analyze

        Returns:
            List of called function/method names
        """
        if self._tree is None:
            return []

        calls = []

        def find_symbol_node(node: ast.AST) -> Optional[ast.AST]:
            """Find the AST node for the given symbol."""
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbol.name and node.lineno == symbol.start_line:
                    return node
            for child in ast.iter_child_nodes(node):
                result = find_symbol_node(child)
                if result:
                    return result
            return None

        symbol_node = find_symbol_node(self._tree)
        if symbol_node is None:
            return []

        for node in ast.walk(symbol_node):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    # For method calls like obj.method()
                    calls.append(node.func.attr)

        return calls
