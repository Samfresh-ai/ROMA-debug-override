"""Smart context extraction for ROMA Debug.

Uses AST parsing to extract full function/class definitions around errors,
with graceful fallback strategies for non-parseable or missing files.
"""

import ast
import os
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple


@dataclass
class FileContext:
    """Extracted context from a source file."""
    filepath: str
    line_number: int
    context_type: str  # 'ast', 'lines', 'missing'
    content: str
    function_name: Optional[str] = None
    class_name: Optional[str] = None


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
    """Extract context from a file using AST or fallback.

    Strategy:
    1. Resolve file path (check cwd-relative paths)
    2. Try AST parsing to get full function/class
    3. Fallback to +/- 50 lines if AST fails
    4. Return friendly message if file missing

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
            content=f"[System] Local file not found at {file_path}. Debugging based on logs only."
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
            content=f"[System] Cannot read file {file_path}: {e}. Debugging based on logs only."
        )

    # Try AST parsing
    ast_context = _try_ast_extraction(source, lines, error_line, resolved_path)
    if ast_context:
        return ast_context

    # Fallback: +/- 50 lines
    return _line_based_extraction(resolved_path, lines, error_line, context_lines=50)


def _try_ast_extraction(
    source: str,
    lines: List[str],
    error_line: int,
    file_path: str
) -> Optional[FileContext]:
    """Try to extract full function/class definition using AST.

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
    )


def _line_based_extraction(
    file_path: str,
    lines: List[str],
    error_line: int,
    context_lines: int = 50
) -> FileContext:
    """Fallback: extract +/- N lines around error.

    Args:
        file_path: Path to file
        lines: Source lines
        error_line: Target line number
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
