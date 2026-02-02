"""Tree-sitter based parser for multi-language support.

Provides semantic parsing for JavaScript, TypeScript, Go, Rust, Java,
and other languages using tree-sitter grammars.
"""

import os
from typing import Optional, List, Dict, Any

from roma_debug.core.models import Language, Symbol, Import
from roma_debug.parsers.base import BaseParser

# Try to import tree-sitter
try:
    import tree_sitter
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    tree_sitter = None

# Language-specific tree-sitter modules
_LANGUAGE_MODULES: Dict[Language, str] = {
    Language.PYTHON: "tree_sitter_python",
    Language.JAVASCRIPT: "tree_sitter_javascript",
    Language.TYPESCRIPT: "tree_sitter_typescript",
    Language.GO: "tree_sitter_go",
    Language.RUST: "tree_sitter_rust",
    Language.JAVA: "tree_sitter_java",
}


def _get_tree_sitter_language(lang: Language) -> Optional[Any]:
    """Get the tree-sitter language object for a language.

    Args:
        lang: The Language enum value

    Returns:
        tree-sitter Language object or None if not available
    """
    if not TREE_SITTER_AVAILABLE:
        return None

    module_name = _LANGUAGE_MODULES.get(lang)
    if not module_name:
        return None

    try:
        module = __import__(module_name)
        # tree-sitter-python exposes language() function
        if hasattr(module, 'language'):
            return tree_sitter.Language(module.language())
        return None
    except ImportError:
        return None
    except Exception:
        return None


# Node types that represent functions/methods in each language
FUNCTION_TYPES: Dict[Language, List[str]] = {
    Language.PYTHON: ["function_definition", "async_function_definition"],
    Language.JAVASCRIPT: ["function_declaration", "function_expression", "arrow_function", "method_definition"],
    Language.TYPESCRIPT: ["function_declaration", "function_expression", "arrow_function", "method_definition", "method_signature"],
    Language.GO: ["function_declaration", "method_declaration"],
    Language.RUST: ["function_item", "impl_item"],
    Language.JAVA: ["method_declaration", "constructor_declaration"],
}

# Node types that represent classes/structs in each language
CLASS_TYPES: Dict[Language, List[str]] = {
    Language.PYTHON: ["class_definition"],
    Language.JAVASCRIPT: ["class_declaration", "class"],
    Language.TYPESCRIPT: ["class_declaration", "interface_declaration"],
    Language.GO: ["type_declaration"],  # for struct types
    Language.RUST: ["struct_item", "enum_item", "impl_item"],
    Language.JAVA: ["class_declaration", "interface_declaration", "enum_declaration"],
}

# Node types for imports
IMPORT_TYPES: Dict[Language, List[str]] = {
    Language.PYTHON: ["import_statement", "import_from_statement"],
    Language.JAVASCRIPT: ["import_statement", "import_declaration"],
    Language.TYPESCRIPT: ["import_statement", "import_declaration"],
    Language.GO: ["import_declaration", "import_spec"],
    Language.RUST: ["use_declaration"],
    Language.JAVA: ["import_declaration"],
}


class TreeSitterParser(BaseParser):
    """Multi-language parser using tree-sitter.

    Supports JavaScript, TypeScript, Go, Rust, Java, and more.
    Falls back gracefully when tree-sitter is not installed.
    """

    def __init__(self, language: Language = Language.UNKNOWN):
        """Initialize the tree-sitter parser.

        Args:
            language: The language to parse (can be set later)
        """
        super().__init__()
        self._lang = language
        self._tree: Optional[Any] = None
        self._ts_language: Optional[Any] = None
        self._parser: Optional[Any] = None
        self._symbols: List[Symbol] = []
        self._imports: List[Import] = []

    @property
    def language(self) -> Language:
        """Return the language this parser handles."""
        return self._lang

    @language.setter
    def language(self, lang: Language):
        """Set the language and initialize the parser."""
        if self._lang != lang:
            self._lang = lang
            self._init_parser()

    @classmethod
    def is_available(cls) -> bool:
        """Check if tree-sitter is available."""
        return TREE_SITTER_AVAILABLE

    @classmethod
    def supported_languages(cls) -> List[Language]:
        """Get list of languages with available tree-sitter support."""
        if not TREE_SITTER_AVAILABLE:
            return []

        available = []
        for lang in _LANGUAGE_MODULES:
            if _get_tree_sitter_language(lang) is not None:
                available.append(lang)
        return available

    def _init_parser(self):
        """Initialize the tree-sitter parser for the current language."""
        if not TREE_SITTER_AVAILABLE:
            return

        self._ts_language = _get_tree_sitter_language(self._lang)
        if self._ts_language is not None:
            self._parser = tree_sitter.Parser(self._ts_language)

    def parse(self, source: str, filepath: str = "") -> bool:
        """Parse source code using tree-sitter.

        Args:
            source: The source code to parse
            filepath: Optional file path for context

        Returns:
            True if parsing succeeded
        """
        self.reset()
        self._source = source
        self._filepath = filepath
        self._lines = source.splitlines()

        # Auto-detect language from filepath if not set
        if self._lang == Language.UNKNOWN and filepath:
            self._lang = Language.from_extension(os.path.splitext(filepath)[1])
            self._init_parser()

        if self._parser is None:
            self._init_parser()

        if self._parser is None:
            return False

        try:
            self._tree = self._parser.parse(source.encode('utf-8'))
            self._parsed = True
            self._extract_symbols()
            self._extract_imports_internal()
            return True
        except Exception:
            return False

    def reset(self):
        """Reset parser state."""
        super().reset()
        self._tree = None
        self._symbols = []
        self._imports = []

    def _get_node_text(self, node) -> str:
        """Get the text content of a tree-sitter node."""
        if self._source is None:
            return ""
        return self._source[node.start_byte:node.end_byte]

    def _get_name_from_node(self, node) -> Optional[str]:
        """Extract the name identifier from a definition node."""
        # Common patterns for finding names
        name_field_types = ["name", "identifier", "property_name"]

        for child in node.children:
            if child.type in ["identifier", "property_identifier", "type_identifier"]:
                return self._get_node_text(child)
            if hasattr(node, 'child_by_field_name'):
                for field in name_field_types:
                    name_node = node.child_by_field_name(field)
                    if name_node:
                        return self._get_node_text(name_node)

        # Fallback: first identifier child
        for child in node.children:
            if "identifier" in child.type:
                return self._get_node_text(child)

        return None

    def _extract_symbols(self):
        """Extract all function and class symbols from the parse tree."""
        if self._tree is None:
            return

        function_types = FUNCTION_TYPES.get(self._lang, [])
        class_types = CLASS_TYPES.get(self._lang, [])

        def visit_node(node, parent_symbol: Optional[Symbol] = None):
            symbol = None
            kind = None

            if node.type in function_types:
                kind = "function"
                if parent_symbol and parent_symbol.kind == "class":
                    kind = "method"
            elif node.type in class_types:
                kind = "class"

            if kind:
                name = self._get_name_from_node(node)
                if name:
                    # Get line numbers (tree-sitter uses 0-based)
                    start_line = node.start_point[0] + 1
                    end_line = node.end_point[0] + 1

                    symbol = Symbol(
                        name=name,
                        kind=kind,
                        start_line=start_line,
                        end_line=end_line,
                        start_col=node.start_point[1],
                        end_col=node.end_point[1],
                        parent=parent_symbol,
                    )
                    self._symbols.append(symbol)

            # Visit children
            new_parent = symbol if symbol else parent_symbol
            for child in node.children:
                visit_node(child, new_parent)

        visit_node(self._tree.root_node)

    def _extract_imports_internal(self):
        """Extract import statements from the parse tree."""
        if self._tree is None:
            return

        import_types = IMPORT_TYPES.get(self._lang, [])

        def visit_node(node):
            if node.type in import_types:
                imp = self._parse_import_node(node)
                if imp:
                    self._imports.append(imp)

            for child in node.children:
                visit_node(child)

        visit_node(self._tree.root_node)

    def _parse_import_node(self, node) -> Optional[Import]:
        """Parse an import node into an Import object."""
        import_text = self._get_node_text(node)
        line_number = node.start_point[0] + 1

        if self._lang == Language.PYTHON:
            return self._parse_python_import(node, import_text, line_number)
        elif self._lang in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            return self._parse_js_import(node, import_text, line_number)
        elif self._lang == Language.GO:
            return self._parse_go_import(node, import_text, line_number)
        elif self._lang == Language.RUST:
            return self._parse_rust_import(node, import_text, line_number)
        elif self._lang == Language.JAVA:
            return self._parse_java_import(node, import_text, line_number)

        # Generic fallback
        return Import(
            module_name=import_text,
            line_number=line_number,
            language=self._lang,
        )

    def _parse_python_import(self, node, text: str, line: int) -> Optional[Import]:
        """Parse Python import statement."""
        # Handle: import x, from x import y
        module_name = ""
        imported_names = []
        is_relative = False
        relative_level = 0

        if node.type == "import_statement":
            # import x, import x as y
            for child in node.children:
                if child.type == "dotted_name":
                    module_name = self._get_node_text(child)
                elif child.type == "aliased_import":
                    for subchild in child.children:
                        if subchild.type == "dotted_name":
                            module_name = self._get_node_text(subchild)
                            break

        elif node.type == "import_from_statement":
            # from x import y
            for child in node.children:
                if child.type == "dotted_name":
                    module_name = self._get_node_text(child)
                elif child.type == "relative_import":
                    is_relative = True
                    dots = self._get_node_text(child)
                    relative_level = dots.count('.')
                    # Get module name after dots
                    for subchild in child.children:
                        if subchild.type == "dotted_name":
                            module_name = self._get_node_text(subchild)
                elif child.type in ("identifier", "wildcard_import"):
                    imported_names.append(self._get_node_text(child))
                elif child.type == "aliased_import":
                    for subchild in child.children:
                        if subchild.type == "identifier":
                            imported_names.append(self._get_node_text(subchild))
                            break

        if not module_name and not imported_names:
            return None

        return Import(
            module_name=module_name,
            imported_names=imported_names,
            is_relative=is_relative,
            relative_level=relative_level,
            line_number=line,
            language=Language.PYTHON,
        )

    def _parse_js_import(self, node, text: str, line: int) -> Optional[Import]:
        """Parse JavaScript/TypeScript import statement."""
        module_name = ""
        imported_names = []
        alias = None

        for child in node.children:
            if child.type == "string":
                # The module path is in a string
                module_name = self._get_node_text(child).strip("'\"")
            elif child.type == "import_clause":
                for subchild in child.children:
                    if subchild.type == "identifier":
                        # Default import
                        alias = self._get_node_text(subchild)
                    elif subchild.type == "named_imports":
                        # Named imports: { a, b, c }
                        for imp_spec in subchild.children:
                            if imp_spec.type == "import_specifier":
                                for name_node in imp_spec.children:
                                    if name_node.type == "identifier":
                                        imported_names.append(self._get_node_text(name_node))
                                        break
                    elif subchild.type == "namespace_import":
                        # import * as X
                        for name_node in subchild.children:
                            if name_node.type == "identifier":
                                alias = self._get_node_text(name_node)

        if not module_name:
            return None

        is_relative = module_name.startswith('.') or module_name.startswith('/')

        return Import(
            module_name=module_name,
            alias=alias,
            imported_names=imported_names,
            is_relative=is_relative,
            line_number=line,
            language=self._lang,
        )

    def _parse_go_import(self, node, text: str, line: int) -> Optional[Import]:
        """Parse Go import statement."""
        module_name = ""
        alias = None

        # Handle both single imports and import blocks
        if node.type == "import_spec":
            for child in node.children:
                if child.type == "interpreted_string_literal":
                    module_name = self._get_node_text(child).strip('"')
                elif child.type == "package_identifier":
                    alias = self._get_node_text(child)
                elif child.type == "blank_identifier":
                    alias = "_"
                elif child.type == "dot":
                    alias = "."
        elif node.type == "import_declaration":
            # Find import_spec children
            for child in node.children:
                if child.type == "import_spec":
                    return self._parse_go_import(child, self._get_node_text(child), line)
                elif child.type == "import_spec_list":
                    # Multiple imports - just return first one for now
                    for spec in child.children:
                        if spec.type == "import_spec":
                            return self._parse_go_import(spec, self._get_node_text(spec), line)
                elif child.type == "interpreted_string_literal":
                    module_name = self._get_node_text(child).strip('"')

        if not module_name:
            return None

        return Import(
            module_name=module_name,
            alias=alias,
            line_number=line,
            language=Language.GO,
        )

    def _parse_rust_import(self, node, text: str, line: int) -> Optional[Import]:
        """Parse Rust use statement."""
        # use statements can be complex: use std::io::{Read, Write};
        module_name = ""
        imported_names = []

        def extract_path(n) -> str:
            if n.type == "identifier" or n.type == "crate":
                return self._get_node_text(n)
            elif n.type == "scoped_identifier":
                parts = []
                for child in n.children:
                    if child.type in ("identifier", "crate", "scoped_identifier"):
                        parts.append(extract_path(child))
                return "::".join(p for p in parts if p)
            return ""

        for child in node.children:
            if child.type == "use_list":
                # Multiple imports
                for item in child.children:
                    if "identifier" in item.type:
                        imported_names.append(self._get_node_text(item))
            elif child.type == "scoped_identifier":
                module_name = extract_path(child)
            elif child.type == "identifier":
                module_name = self._get_node_text(child)
            elif child.type == "scoped_use_list":
                # use std::io::{Read, Write}
                for subchild in child.children:
                    if subchild.type == "scoped_identifier":
                        module_name = extract_path(subchild)
                    elif subchild.type == "use_list":
                        for item in subchild.children:
                            if "identifier" in item.type:
                                imported_names.append(self._get_node_text(item))

        if not module_name and not imported_names:
            return None

        return Import(
            module_name=module_name,
            imported_names=imported_names,
            line_number=line,
            language=Language.RUST,
        )

    def _parse_java_import(self, node, text: str, line: int) -> Optional[Import]:
        """Parse Java import statement."""
        module_name = ""
        imported_names = []

        for child in node.children:
            if child.type == "scoped_identifier":
                # Build full path: com.example.MyClass
                parts = []

                def collect_parts(n):
                    for c in n.children:
                        if c.type == "identifier":
                            parts.append(self._get_node_text(c))
                        elif c.type == "scoped_identifier":
                            collect_parts(c)

                collect_parts(child)
                module_name = ".".join(parts)

            elif child.type == "asterisk":
                imported_names.append("*")

        if not module_name:
            return None

        return Import(
            module_name=module_name,
            imported_names=imported_names,
            line_number=line,
            language=Language.JAVA,
        )

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


def create_parser_for_language(language: Language) -> Optional[TreeSitterParser]:
    """Factory function to create a tree-sitter parser for a language.

    Args:
        language: The language to create a parser for

    Returns:
        TreeSitterParser instance or None if not supported
    """
    if not TREE_SITTER_AVAILABLE:
        return None

    if language not in _LANGUAGE_MODULES:
        return None

    parser = TreeSitterParser(language)
    parser._init_parser()

    if parser._parser is None:
        return None

    return parser


# Register tree-sitter parsers with the registry
def _register_treesitter_parsers():
    """Register tree-sitter parsers for all available languages."""
    if not TREE_SITTER_AVAILABLE:
        return

    from roma_debug.parsers.registry import register_parser

    for lang in TreeSitterParser.supported_languages():
        if lang != Language.PYTHON:  # Python uses AST parser by default
            register_parser(
                lang,
                TreeSitterParser,
                factory=lambda l=lang: TreeSitterParser(l),
            )


# Auto-register on import
_register_treesitter_parsers()
