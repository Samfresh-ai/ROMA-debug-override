"""Abstract base class for language parsers.

All language-specific parsers must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Optional, List

from roma_debug.core.models import Language, Symbol, Import


class BaseParser(ABC):
    """Abstract base class for language parsers.

    Each language parser must implement methods for:
    - Parsing source code
    - Finding symbols (functions, classes) at specific lines
    - Extracting import statements
    """

    def __init__(self):
        """Initialize the parser."""
        self._source: Optional[str] = None
        self._filepath: Optional[str] = None
        self._lines: List[str] = []
        self._parsed: bool = False

    @property
    @abstractmethod
    def language(self) -> Language:
        """Return the language this parser handles."""
        ...

    @property
    def source(self) -> Optional[str]:
        """Return the parsed source code."""
        return self._source

    @property
    def filepath(self) -> Optional[str]:
        """Return the file path being parsed."""
        return self._filepath

    @property
    def lines(self) -> List[str]:
        """Return source split into lines."""
        return self._lines

    @property
    def is_parsed(self) -> bool:
        """Check if a file has been successfully parsed."""
        return self._parsed

    @abstractmethod
    def parse(self, source: str, filepath: str = "") -> bool:
        """Parse source code.

        Args:
            source: The source code to parse
            filepath: Optional file path for context

        Returns:
            True if parsing succeeded, False otherwise
        """
        ...

    @abstractmethod
    def find_enclosing_symbol(self, line_number: int) -> Optional[Symbol]:
        """Find the innermost symbol containing the given line.

        Args:
            line_number: 1-based line number

        Returns:
            Symbol if found, None otherwise
        """
        ...

    @abstractmethod
    def extract_imports(self) -> List[Import]:
        """Extract all import statements from the parsed source.

        Returns:
            List of Import objects
        """
        ...

    def get_symbol_at_line(self, line_number: int) -> Optional[Symbol]:
        """Alias for find_enclosing_symbol for backward compatibility."""
        return self.find_enclosing_symbol(line_number)

    def get_line_content(self, line_number: int) -> Optional[str]:
        """Get the content of a specific line.

        Args:
            line_number: 1-based line number

        Returns:
            Line content or None if out of range
        """
        if not self._lines:
            return None
        idx = line_number - 1
        if 0 <= idx < len(self._lines):
            return self._lines[idx]
        return None

    def get_line_range(self, start: int, end: int) -> List[str]:
        """Get a range of lines.

        Args:
            start: 1-based start line (inclusive)
            end: 1-based end line (inclusive)

        Returns:
            List of line contents
        """
        if not self._lines:
            return []
        start_idx = max(0, start - 1)
        end_idx = min(len(self._lines), end)
        return self._lines[start_idx:end_idx]

    def format_snippet(
        self,
        start_line: int,
        end_line: int,
        highlight_line: Optional[int] = None,
        with_line_numbers: bool = True,
    ) -> str:
        """Format a code snippet with optional line numbers and highlighting.

        Args:
            start_line: 1-based start line
            end_line: 1-based end line
            highlight_line: Optional line to highlight with >>
            with_line_numbers: Whether to include line numbers

        Returns:
            Formatted snippet string
        """
        lines = self.get_line_range(start_line, end_line)
        result = []

        for i, line in enumerate(lines):
            line_num = start_line + i
            if with_line_numbers:
                marker = " >> " if line_num == highlight_line else "    "
                result.append(f"{marker}{line_num:4d} | {line}")
            else:
                marker = ">> " if line_num == highlight_line else "   "
                result.append(f"{marker}{line}")

        return "\n".join(result)

    def extract_symbol_code(
        self,
        symbol: Symbol,
        include_decorators: bool = True,
        context_before: int = 0,
        context_after: int = 0,
    ) -> str:
        """Extract the full code for a symbol.

        Args:
            symbol: The symbol to extract
            include_decorators: Whether to include decorator lines
            context_before: Extra lines before the symbol
            context_after: Extra lines after the symbol

        Returns:
            The symbol's source code
        """
        start = symbol.start_line
        if include_decorators and symbol.decorators:
            # Decorators are typically on lines before the definition
            start = max(1, start - len(symbol.decorators))

        start = max(1, start - context_before)
        end = min(len(self._lines), symbol.end_line + context_after)

        return "\n".join(self.get_line_range(start, end))

    def reset(self):
        """Reset parser state."""
        self._source = None
        self._filepath = None
        self._lines = []
        self._parsed = False
