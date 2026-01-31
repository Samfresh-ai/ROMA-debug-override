"""Context reader for extracting file context from error logs."""

import os
import re
from typing import Optional


def get_file_context(error_log: str) -> str:
    """Extract file context from a Python traceback.

    Uses regex to extract file paths (e.g., "File '/app/src/main.py', line 10")
    from the Python traceback. If the file exists locally, reads +/- 20 lines
    around the error line.

    Args:
        error_log: The error log or traceback string

    Returns:
        Formatted string: "Context from [filename]:\n[code snippet]"
        Returns empty string if no files found or readable.
    """
    # Pattern to match Python traceback file references
    # Matches: File "/path/to/file.py", line 10
    pattern = re.compile(r'File ["\'](.+?)["\'], line (\d+)')

    matches = pattern.findall(error_log)

    if not matches:
        return ""

    context_parts = []

    for file_path, line_num_str in matches:
        line_num = int(line_num_str)
        snippet = _read_file_snippet(file_path, line_num)

        if snippet:
            filename = os.path.basename(file_path)
            context_parts.append(f"Context from {filename}:\n{snippet}")

    return "\n\n".join(context_parts)


def _read_file_snippet(file_path: str, error_line: int, context_lines: int = 20) -> Optional[str]:
    """Read a snippet of a file around a specific line.

    Args:
        file_path: Path to the file
        error_line: The line number where the error occurred
        context_lines: Number of lines to include before and after (default: 20)

    Returns:
        Formatted code snippet with line numbers, or None if file not readable
    """
    if not os.path.isfile(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except (IOError, OSError):
        return None

    total_lines = len(lines)

    # Calculate start and end lines (+/- 20 lines around error)
    start_line = max(1, error_line - context_lines)
    end_line = min(total_lines, error_line + context_lines)

    # Build snippet with line numbers
    snippet_lines = []
    for i in range(start_line - 1, end_line):
        line_num = i + 1
        line_content = lines[i].rstrip('\n\r')

        # Mark the error line
        marker = " >> " if line_num == error_line else "    "
        snippet_lines.append(f"{marker}{line_num:4d} | {line_content}")

    return "\n".join(snippet_lines)
