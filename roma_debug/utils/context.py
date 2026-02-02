"""Smart context extraction for ROMA Debug.

Uses AST parsing to extract full function/class definitions around errors,
with graceful fallback strategies for non-parseable or missing files.

V2: Now supports multi-language parsing via parser registry.
"""

import ast
import os
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

from roma_debug.core.models import Language, FileContext as FileContextV2, Import, Symbol
from roma_debug.parsers.registry import get_parser, detect_language


@dataclass
class FileContext:
    """Extracted context from a source file.

    This is the V1 interface maintained for backward compatibility.
    Internally delegates to FileContextV2 when possible.
    """
    filepath: str
    line_number: int
    context_type: str  # 'ast', 'lines', 'missing', 'treesitter'
    content: str
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    # V2 additions (optional for backward compat)
    language: Language = Language.UNKNOWN
    imports: List[Import] = None
    symbol: Optional[Symbol] = None

    def __post_init__(self):
        if self.imports is None:
            self.imports = []

    def to_v2(self) -> FileContextV2:
        """Convert to V2 FileContext."""
        return FileContextV2(
            filepath=self.filepath,
            line_number=self.line_number,
            context_type=self.context_type,
            content=self.content,
            function_name=self.function_name,
            class_name=self.class_name,
            language=self.language,
            imports=self.imports or [],
            symbol=self.symbol,
        )


def _resolve_file_path(file_path: str) -> Optional[str]:
    """Resolve file path, checking both absolute and cwd-relative locations.

    Args:
        file_path: Path from traceback (may be absolute or relative)

    Returns:
        Resolved path if file exists, None otherwise
    """
    # 1. Try the path as-is (absolute or relative to cwd)
    if os.path.isfile(file_path):
        return file_path

    # 2. Try relative to current working directory
    cwd = os.getcwd()
    cwd_relative = os.path.join(cwd, file_path)
    if os.path.isfile(cwd_relative):
        return cwd_relative

    # 3. Try just the filename in cwd (for logs from different machines)
    filename = os.path.basename(file_path)
    cwd_filename = os.path.join(cwd, filename)
    if os.path.isfile(cwd_filename):
        return cwd_filename

    # 4. Try extracting relative path after common prefixes
    # e.g., "/app/src/main.py" -> "src/main.py"
    common_prefixes = ["/app/", "/home/", "/usr/", "/var/"]
    for prefix in common_prefixes:
        if file_path.startswith(prefix):
            relative = file_path[len(prefix):]
            cwd_relative = os.path.join(cwd, relative)
            if os.path.isfile(cwd_relative):
                return cwd_relative

    # 5. Search for the file in common project subdirectories
    search_dirs = [".", "src", "lib", "app", "tests", "test"]
    for search_dir in search_dirs:
        search_path = os.path.join(cwd, search_dir, filename)
        if os.path.isfile(search_path):
            return search_path

    return None


def get_file_context(error_log: str) -> Tuple[str, List[FileContext]]:
    """Extract file context from a Python traceback.

    Uses AST parsing to extract full function/class definitions.
    Falls back to line-based extraction if AST fails.
    Searches for files relative to os.getcwd() for project awareness.

    Args:
        error_log: The error log or traceback string

    Returns:
        Tuple of (formatted context string, list of FileContext objects)
    """
    # Pattern to match Python traceback file references
    pattern = re.compile(r'File ["\'](.+?)["\'], line (\d+)')
    matches = pattern.findall(error_log)

    if not matches:
        return "", []

    contexts: List[FileContext] = []
    context_parts: List[str] = []

    for file_path, line_num_str in matches:
        line_num = int(line_num_str)
        file_context = _extract_context(file_path, line_num)
        contexts.append(file_context)

        # Build formatted output
        filename = os.path.basename(file_path)
        if file_context.context_type == "missing":
            context_parts.append(file_context.content)
        else:
            header = f"Context from {filename}"
            if file_context.function_name:
                header += f" (function: {file_context.function_name})"
            if file_context.class_name:
                header += f" (class: {file_context.class_name})"
            context_parts.append(f"{header}:\n{file_context.content}")

    return "\n\n".join(context_parts), contexts


def _extract_context(file_path: str, error_line: int) -> FileContext:
    """Extract context from a file using parser or fallback.

    Strategy:
    1. Resolve file path (check cwd-relative paths)
    2. Detect language from file extension
    3. Try language-specific parser to get full function/class
    4. Fallback to +/- 50 lines if parser fails
    5. Return friendly message if file missing

    Args:
        file_path: Path to the source file (from traceback)
        error_line: Line number where error occurred

    Returns:
        FileContext with extracted content
    """
    # Resolve the file path (try cwd-relative if absolute doesn't exist)
    resolved_path = _resolve_file_path(file_path)

    if resolved_path is None:
        return FileContext(
            filepath=file_path,
            line_number=error_line,
            context_type="missing",
            content=f"[System] Local file not found at {file_path}. Debugging based on logs only.",
            language=detect_language(file_path),
        )

    # Read file content
    try:
        with open(resolved_path, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
            lines = source.splitlines()
    except (IOError, OSError) as e:
        return FileContext(
            filepath=file_path,
            line_number=error_line,
            context_type="missing",
            content=f"[System] Cannot read file {file_path}: {e}. Debugging based on logs only.",
            language=detect_language(file_path),
        )

    # Detect language
    language = detect_language(resolved_path)

    # Try parser-based extraction
    parser_context = _try_parser_extraction(source, lines, error_line, resolved_path, language)
    if parser_context:
        return parser_context

    # Fallback: +/- 50 lines
    return _line_based_extraction(resolved_path, lines, error_line, language, context_lines=50)


def _try_parser_extraction(
    source: str,
    lines: List[str],
    error_line: int,
    file_path: str,
    language: Language,
) -> Optional[FileContext]:
    """Try to extract full function/class definition using a parser.

    Args:
        source: Full source code
        lines: Source split into lines
        error_line: Target line number
        file_path: Path to file
        language: Detected language

    Returns:
        FileContext if successful, None if parsing fails
    """
    # Get appropriate parser
    parser = get_parser(language, create_new=True)

    if parser is None:
        # No parser available for this language, try Python AST as fallback
        if language == Language.PYTHON or file_path.endswith('.py'):
            return _try_ast_extraction(source, lines, error_line, file_path)
        return None

    # Try parsing
    if not parser.parse(source, file_path):
        # Parser failed, try Python AST as last resort for .py files
        if language == Language.PYTHON:
            return _try_ast_extraction(source, lines, error_line, file_path)
        return None

    # Find enclosing symbol
    symbol = parser.find_enclosing_symbol(error_line)

    if symbol is None:
        return None

    # Extract the full function/class with some buffer
    start_line = max(1, symbol.start_line - 2)  # 2 lines before for decorators
    end_line = min(len(lines), symbol.end_line + 2)

    # Build snippet with line numbers
    snippet = parser.format_snippet(start_line, end_line, highlight_line=error_line)

    # Determine names
    function_name = None
    class_name = None
    if symbol.kind in ("function", "method", "async_function"):
        function_name = symbol.name
        if symbol.parent and symbol.parent.kind == "class":
            class_name = symbol.parent.name
    elif symbol.kind == "class":
        class_name = symbol.name

    # Extract imports
    imports = parser.extract_imports()

    context_type = "treesitter" if "treesitter" in type(parser).__module__ else "ast"

    return FileContext(
        filepath=file_path,
        line_number=error_line,
        context_type=context_type,
        content=snippet,
        function_name=function_name,
        class_name=class_name,
        language=language,
        imports=imports,
        symbol=symbol,
    )


def _try_ast_extraction(
    source: str,
    lines: List[str],
    error_line: int,
    file_path: str
) -> Optional[FileContext]:
    """Try to extract full function/class definition using AST.

    Legacy method for backward compatibility. Kept as fallback.

    Args:
        source: Full source code
        lines: Source split into lines
        error_line: Target line number
        file_path: Path to file

    Returns:
        FileContext if successful, None if AST parsing fails
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # Find the innermost function or class containing the error line
    best_match = None
    best_match_size = float('inf')

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Check if error line is within this node
            if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                if node.lineno <= error_line <= (node.end_lineno or node.lineno):
                    # Prefer smaller (more specific) matches
                    size = (node.end_lineno or node.lineno) - node.lineno
                    if size < best_match_size:
                        best_match = node
                        best_match_size = size

    if not best_match:
        return None

    # Extract the full function/class with some buffer
    start_line = max(1, best_match.lineno - 2)  # 2 lines before for decorators
    end_line = min(len(lines), (best_match.end_lineno or best_match.lineno) + 2)

    # Build snippet with line numbers
    snippet_lines = []
    for i in range(start_line - 1, end_line):
        line_num = i + 1
        line_content = lines[i]
        marker = " >> " if line_num == error_line else "    "
        snippet_lines.append(f"{marker}{line_num:4d} | {line_content}")

    # Determine names
    function_name = None
    class_name = None
    if isinstance(best_match, (ast.FunctionDef, ast.AsyncFunctionDef)):
        function_name = best_match.name
    elif isinstance(best_match, ast.ClassDef):
        class_name = best_match.name

    return FileContext(
        filepath=file_path,
        line_number=error_line,
        context_type="ast",
        content="\n".join(snippet_lines),
        function_name=function_name,
        class_name=class_name,
        language=Language.PYTHON,
    )


def _line_based_extraction(
    file_path: str,
    lines: List[str],
    error_line: int,
    language: Language = Language.UNKNOWN,
    context_lines: int = 50
) -> FileContext:
    """Fallback: extract +/- N lines around error.

    Args:
        file_path: Path to file
        lines: Source lines
        error_line: Target line number
        language: Detected language
        context_lines: Lines before/after to include

    Returns:
        FileContext with line-based extraction
    """
    total_lines = len(lines)
    start_line = max(1, error_line - context_lines)
    end_line = min(total_lines, error_line + context_lines)

    snippet_lines = []
    for i in range(start_line - 1, end_line):
        line_num = i + 1
        line_content = lines[i]
        marker = " >> " if line_num == error_line else "    "
        snippet_lines.append(f"{marker}{line_num:4d} | {line_content}")

    return FileContext(
        filepath=file_path,
        line_number=error_line,
        context_type="lines",
        content="\n".join(snippet_lines),
        language=language,
    )


def get_primary_file(contexts: List[FileContext]) -> Optional[FileContext]:
    """Get the primary file from contexts (last non-missing entry).

    Usually the last file in the traceback is the most relevant.

    Args:
        contexts: List of FileContext objects

    Returns:
        The primary FileContext or None
    """
    for ctx in reversed(contexts):
        if ctx.context_type != "missing":
            return ctx
    return None


def extract_context_v2(
    error_log: str,
    project_root: Optional[str] = None,
) -> Tuple[str, List[FileContextV2]]:
    """V2 context extraction with full language support.

    Args:
        error_log: The error log or traceback string
        project_root: Optional project root for import resolution

    Returns:
        Tuple of (formatted context string, list of FileContextV2 objects)
    """
    # Use the same extraction logic but return V2 objects
    context_str, contexts = get_file_context(error_log)

    v2_contexts = [ctx.to_v2() for ctx in contexts]

    return context_str, v2_contexts


def generate_file_tree(
    project_root: Optional[str] = None,
    max_depth: int = 4,
    max_files_per_dir: int = 20,
) -> str:
    """Generate a visual file tree of the project for environmental awareness.

    This function creates a tree-style representation of the project structure,
    which can be included in prompts to help the AI understand what files exist.

    Args:
        project_root: Root directory to scan (defaults to cwd)
        max_depth: Maximum directory depth to traverse
        max_files_per_dir: Maximum files to show per directory

    Returns:
        String representation of the project file tree

    Example:
        >>> tree = generate_file_tree()
        >>> print(tree)
        my-project/
        ├── src/
        │   ├── app.py
        │   └── utils.py
        ├── tests/
        │   └── test_app.py
        └── requirements.txt
    """
    from roma_debug.tracing.project_scanner import ProjectScanner

    root = project_root or os.getcwd()
    scanner = ProjectScanner(root)

    return scanner.generate_file_tree(
        max_depth=max_depth,
        max_files_per_dir=max_files_per_dir,
    )


def get_file_context_with_tree(
    error_log: str,
    project_root: Optional[str] = None,
) -> Tuple[str, List[FileContext]]:
    """Extract file context from error log AND include file tree for awareness.

    Enhanced version of get_file_context() that also includes the project
    file tree to give the AI environmental awareness of what files exist.

    Args:
        error_log: The error log or traceback string
        project_root: Optional project root for file tree generation

    Returns:
        Tuple of (formatted context string with file tree, list of FileContext objects)
    """
    # Get standard file context
    context_str, contexts = get_file_context(error_log)

    # Generate file tree
    file_tree = generate_file_tree(project_root)

    # Build enhanced context with file tree
    parts = []

    # Add file tree section first
    parts.append("<ProjectStructure>")
    parts.append("## PROJECT FILE TREE")
    parts.append("Use this tree to verify file paths. Do NOT assume a file exists unless you see it here.")
    parts.append("If a file is missing from an expected location, look for it in this tree.")
    parts.append("")
    parts.append("```")
    parts.append(file_tree)
    parts.append("```")
    parts.append("</ProjectStructure>")
    parts.append("")

    # Add original context
    if context_str:
        parts.append("## SOURCE CONTEXT")
        parts.append(context_str)

    return "\n".join(parts), contexts
