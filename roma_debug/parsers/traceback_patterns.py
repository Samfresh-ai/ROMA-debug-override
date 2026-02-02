"""Multi-language traceback/stack trace patterns.

Provides regex patterns and parsers for extracting file locations
from error tracebacks in multiple programming languages.
"""

import re
from typing import Optional, List, Tuple, Pattern

from roma_debug.core.models import Language, TraceFrame, ParsedTraceback


# Compiled regex patterns for each language's traceback format
TRACEBACK_PATTERNS: dict[Language, List[Pattern]] = {
    # Python: File "path/to/file.py", line 10, in function_name
    Language.PYTHON: [
        re.compile(r'File ["\'](.+?)["\'], line (\d+)(?:, in (\w+))?'),
        # Alternative format sometimes seen
        re.compile(r'^\s+(.+\.py):(\d+)'),
    ],

    # JavaScript/Node.js: at functionName (path/to/file.js:10:5) or path/to/file.js:10:5
    Language.JAVASCRIPT: [
        re.compile(r'at\s+(?:(\w+(?:\.\w+)*)\s+)?\(?(.+?):(\d+):(\d+)\)?'),
        re.compile(r'^\s+at\s+(.+?):(\d+):(\d+)'),
        # Chrome DevTools format
        re.compile(r'(\w+)?@(.+?):(\d+):(\d+)'),
    ],

    # TypeScript: same as JavaScript but with .ts extension
    Language.TYPESCRIPT: [
        re.compile(r'at\s+(?:(\w+(?:\.\w+)*)\s+)?\(?(.+?\.tsx?):(\d+):(\d+)\)?'),
        re.compile(r'^\s+at\s+(.+?\.tsx?):(\d+):(\d+)'),
    ],

    # Go: goroutine N [running]:
    #     path/to/file.go:123 +0x1a2
    #     main.functionName(...)
    Language.GO: [
        re.compile(r'^\s*(.+\.go):(\d+)(?:\s+\+0x[0-9a-f]+)?', re.MULTILINE),
        re.compile(r'[\t\s]+(/?\S+\.go):(\d+)', re.MULTILINE),
        # panic location
        re.compile(r'panic.*at\s+(.+\.go):(\d+)'),
    ],

    # Rust: panicked at 'message', src/main.rs:10:5
    #       thread 'main' panicked at src/main.rs:10:5
    Language.RUST: [
        re.compile(r"panicked at ['\"]?(.+?\.rs)['\"]?:(\d+):(\d+)"),
        re.compile(r"panicked at .+?, (.+?\.rs):(\d+):(\d+)"),
        # Backtrace format
        re.compile(r'^\s*\d+:\s+.+\s+at\s+(.+?\.rs):(\d+):(\d+)'),
        re.compile(r'^\s+(\S+\.rs):(\d+)'),
    ],

    # Java: at com.example.Class.method(File.java:10)
    Language.JAVA: [
        re.compile(r'at\s+([\w$.]+)\(([\w]+\.java):(\d+)\)'),
        re.compile(r'at\s+([\w$.]+)\((\w+\.java):(\d+)\)'),
        # Kotlin (often mixed with Java)
        re.compile(r'at\s+([\w$.]+)\(([\w]+\.kt):(\d+)\)'),
    ],

    # C#/.NET: at Namespace.Class.Method() in path/to/file.cs:line 10
    Language.CSHARP: [
        re.compile(r'at\s+([\w.]+)\(\)\s+in\s+(.+?\.cs):line\s+(\d+)'),
        re.compile(r'at\s+([\w.]+)\s+in\s+(.+?\.cs):(\d+)'),
    ],

    # Ruby: from path/to/file.rb:10:in `method_name'
    Language.RUBY: [
        re.compile(r"from (.+?\.rb):(\d+)(?::in [`'](\w+)')?"),
        re.compile(r"^\s*(.+?\.rb):(\d+):in [`'](\w+)'"),
    ],

    # PHP: in /path/to/file.php on line 10
    #      /path/to/file.php(10): function()
    Language.PHP: [
        re.compile(r'in\s+(.+?\.php)\s+on\s+line\s+(\d+)'),
        re.compile(r'(.+?\.php)\((\d+)\):\s*(\w+)?'),
    ],
}

# Error type patterns for each language
ERROR_TYPE_PATTERNS: dict[Language, List[Pattern]] = {
    Language.PYTHON: [
        re.compile(r'^(\w+Error):\s*(.+)$', re.MULTILINE),
        re.compile(r'^(\w+Exception):\s*(.+)$', re.MULTILINE),
        re.compile(r'^(\w+Warning):\s*(.+)$', re.MULTILINE),
    ],
    Language.JAVASCRIPT: [
        re.compile(r'^(\w*Error):\s*(.+)$', re.MULTILINE),
        re.compile(r'^Uncaught\s+(\w+):\s*(.+)$', re.MULTILINE),
    ],
    Language.TYPESCRIPT: [
        re.compile(r'^(\w*Error):\s*(.+)$', re.MULTILINE),
        re.compile(r'^TSError:\s*(.+)$', re.MULTILINE),
    ],
    Language.GO: [
        re.compile(r'^panic:\s*(.+)$', re.MULTILINE),
        re.compile(r'^fatal error:\s*(.+)$', re.MULTILINE),
    ],
    Language.RUST: [
        re.compile(r"thread '[\w-]+' panicked at ['\"](.+?)['\"]", re.MULTILINE),
        re.compile(r'^error\[E\d+\]:\s*(.+)$', re.MULTILINE),
    ],
    Language.JAVA: [
        re.compile(r'^([\w.]+Exception):\s*(.+)$', re.MULTILINE),
        re.compile(r'^([\w.]+Error):\s*(.+)$', re.MULTILINE),
        re.compile(r'^Caused by:\s*([\w.]+):\s*(.+)$', re.MULTILINE),
    ],
}


def detect_traceback_language(traceback: str) -> Language:
    """Detect the language of a traceback from its format.

    Args:
        traceback: The traceback/stack trace string

    Returns:
        Detected Language enum value
    """
    # Check for language-specific indicators
    indicators = [
        (Language.PYTHON, ['File "', "Traceback (most recent call last):", ".py\", line"]),
        (Language.JAVASCRIPT, ["at ", ".js:", "node_modules/", "Error:", "    at "]),
        (Language.TYPESCRIPT, [".ts:", ".tsx:", "TSError"]),
        (Language.GO, ["goroutine", ".go:", "panic:", "runtime error:"]),
        (Language.RUST, ["panicked at", ".rs:", "thread '", "RUST_BACKTRACE"]),
        (Language.JAVA, [".java:", "at ", "Exception", "Caused by:"]),
        (Language.CSHARP, [".cs:", "at ", " in ", ":line "]),
        (Language.RUBY, [".rb:", "from ", ":in `"]),
        (Language.PHP, [".php", "on line", "Stack trace:"]),
    ]

    scores = {lang: 0 for lang, _ in indicators}

    for lang, keywords in indicators:
        for keyword in keywords:
            if keyword in traceback:
                scores[lang] += 1

    # Return language with highest score
    best_lang = max(scores, key=scores.get)
    if scores[best_lang] > 0:
        return best_lang

    return Language.UNKNOWN


def parse_traceback(traceback: str, language: Optional[Language] = None) -> ParsedTraceback:
    """Parse a traceback string into structured data.

    Args:
        traceback: The traceback/stack trace string
        language: Optional language hint (auto-detected if not provided)

    Returns:
        ParsedTraceback with frames and error info
    """
    if language is None:
        language = detect_traceback_language(traceback)

    frames = extract_frames(traceback, language)
    error_type, error_message = extract_error_info(traceback, language)

    return ParsedTraceback(
        frames=frames,
        error_type=error_type,
        error_message=error_message,
        language=language,
        raw_traceback=traceback,
    )


def extract_frames(traceback: str, language: Language) -> List[TraceFrame]:
    """Extract stack frames from a traceback.

    Args:
        traceback: The traceback string
        language: The language of the traceback

    Returns:
        List of TraceFrame objects
    """
    frames = []
    patterns = TRACEBACK_PATTERNS.get(language, [])

    # Also try unknown patterns (generic file:line format)
    if language == Language.UNKNOWN:
        patterns = [
            re.compile(r'(?:at\s+)?(.+?):(\d+)(?::(\d+))?'),
        ]

    for pattern in patterns:
        for match in pattern.finditer(traceback):
            groups = match.groups()

            # Different languages have different group structures
            if language == Language.PYTHON:
                filepath = groups[0]
                line_number = int(groups[1])
                function_name = groups[2] if len(groups) > 2 else None
                column = None

            elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
                # JS format: function, file, line, column or file, line, column
                if len(groups) >= 4:
                    function_name = groups[0]
                    filepath = groups[1]
                    line_number = int(groups[2])
                    column = int(groups[3]) if groups[3] else None
                else:
                    function_name = None
                    filepath = groups[0]
                    line_number = int(groups[1])
                    column = int(groups[2]) if len(groups) > 2 and groups[2] else None

            elif language == Language.GO:
                filepath = groups[0]
                line_number = int(groups[1])
                function_name = None
                column = None

            elif language == Language.RUST:
                filepath = groups[0]
                line_number = int(groups[1])
                column = int(groups[2]) if len(groups) > 2 and groups[2] else None
                function_name = None

            elif language == Language.JAVA:
                # Java format: class.method, file, line
                function_name = groups[0] if groups[0] else None
                filepath = groups[1]
                line_number = int(groups[2])
                column = None

            else:
                # Generic fallback
                filepath = groups[0]
                line_number = int(groups[1]) if len(groups) > 1 and groups[1] else 0
                column = int(groups[2]) if len(groups) > 2 and groups[2] else None
                function_name = None

            # Skip if we couldn't get a valid file and line
            if not filepath or not line_number:
                continue

            frame = TraceFrame(
                filepath=filepath,
                line_number=line_number,
                function_name=function_name,
                column_number=column,
                language=language,
            )
            frames.append(frame)

    return frames


def extract_error_info(traceback: str, language: Language) -> Tuple[Optional[str], Optional[str]]:
    """Extract error type and message from a traceback.

    Args:
        traceback: The traceback string
        language: The language of the traceback

    Returns:
        Tuple of (error_type, error_message)
    """
    patterns = ERROR_TYPE_PATTERNS.get(language, [])

    for pattern in patterns:
        match = pattern.search(traceback)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                return groups[0], groups[1]
            elif len(groups) == 1:
                return None, groups[0]

    # Generic fallback: look for common error patterns
    generic_patterns = [
        re.compile(r'^Error:\s*(.+)$', re.MULTILINE),
        re.compile(r'^Exception:\s*(.+)$', re.MULTILINE),
        re.compile(r'^fatal:\s*(.+)$', re.MULTILINE),
    ]

    for pattern in generic_patterns:
        match = pattern.search(traceback)
        if match:
            return None, match.group(1)

    return None, None


def extract_file_line_pairs(traceback: str, language: Optional[Language] = None) -> List[Tuple[str, int]]:
    """Extract (filepath, line_number) pairs from a traceback.

    Simple helper function for basic extraction without full parsing.

    Args:
        traceback: The traceback string
        language: Optional language hint

    Returns:
        List of (filepath, line_number) tuples
    """
    if language is None:
        language = detect_traceback_language(traceback)

    frames = extract_frames(traceback, language)
    return [(f.filepath, f.line_number) for f in frames]
