"""Core data models for ROMA Debug V2.

This module provides enhanced data structures for multi-language support
and deep debugging capabilities.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Any


class Language(Enum):
    """Supported programming languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    C = "c"
    CPP = "cpp"
    CSHARP = "csharp"
    RUBY = "ruby"
    PHP = "php"
    UNKNOWN = "unknown"

    @classmethod
    def from_extension(cls, ext: str) -> "Language":
        """Get language from file extension.

        Args:
            ext: File extension (with or without leading dot)

        Returns:
            Language enum value
        """
        ext = ext.lower().lstrip(".")
        mapping = {
            "py": cls.PYTHON,
            "pyw": cls.PYTHON,
            "pyi": cls.PYTHON,
            "js": cls.JAVASCRIPT,
            "mjs": cls.JAVASCRIPT,
            "cjs": cls.JAVASCRIPT,
            "jsx": cls.JAVASCRIPT,
            "ts": cls.TYPESCRIPT,
            "tsx": cls.TYPESCRIPT,
            "mts": cls.TYPESCRIPT,
            "cts": cls.TYPESCRIPT,
            "go": cls.GO,
            "rs": cls.RUST,
            "java": cls.JAVA,
            "c": cls.C,
            "h": cls.C,
            "cpp": cls.CPP,
            "cc": cls.CPP,
            "cxx": cls.CPP,
            "hpp": cls.CPP,
            "hxx": cls.CPP,
            "cs": cls.CSHARP,
            "rb": cls.RUBY,
            "php": cls.PHP,
        }
        return mapping.get(ext, cls.UNKNOWN)


@dataclass
class Symbol:
    """A code symbol (function, method, class, etc.).

    Represents a named code construct that can contain the error line.
    """
    name: str
    kind: str  # 'function', 'method', 'class', 'module', etc.
    start_line: int
    end_line: int
    start_col: int = 0
    end_col: int = 0
    parent: Optional["Symbol"] = None
    children: List["Symbol"] = field(default_factory=list)
    docstring: Optional[str] = None
    decorators: List[str] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        """Get fully qualified name including parent chain."""
        if self.parent:
            return f"{self.parent.qualified_name}.{self.name}"
        return self.name

    def contains_line(self, line_number: int) -> bool:
        """Check if this symbol contains the given line number."""
        return self.start_line <= line_number <= self.end_line


@dataclass
class Import:
    """Represents an import statement.

    Tracks both the import syntax and resolved file path.
    """
    module_name: str  # e.g., 'os.path', 'lodash', './utils'
    alias: Optional[str] = None  # e.g., 'np' for 'import numpy as np'
    imported_names: List[str] = field(default_factory=list)  # e.g., ['join', 'dirname']
    is_relative: bool = False
    relative_level: int = 0  # Number of dots for relative imports
    line_number: int = 0
    resolved_path: Optional[str] = None  # Actual file path after resolution
    language: Language = Language.UNKNOWN

    @property
    def full_import_string(self) -> str:
        """Reconstruct the import statement."""
        if self.language == Language.PYTHON:
            if self.imported_names:
                prefix = "." * self.relative_level if self.is_relative else ""
                return f"from {prefix}{self.module_name} import {', '.join(self.imported_names)}"
            elif self.alias:
                return f"import {self.module_name} as {self.alias}"
            else:
                return f"import {self.module_name}"
        elif self.language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            if self.imported_names:
                return f"import {{ {', '.join(self.imported_names)} }} from '{self.module_name}'"
            elif self.alias:
                return f"import {self.alias} from '{self.module_name}'"
            else:
                return f"import '{self.module_name}'"
        elif self.language == Language.GO:
            if self.alias:
                return f'import {self.alias} "{self.module_name}"'
            return f'import "{self.module_name}"'
        return f"import {self.module_name}"


@dataclass
class FileContext:
    """Extracted context from a source file.

    This class is backward compatible with the original FileContext
    while adding V2 fields for multi-language support.
    """
    filepath: str
    line_number: int
    context_type: str  # 'ast', 'lines', 'missing', 'treesitter'
    content: str
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    # V2 additions
    language: Language = Language.UNKNOWN
    imports: List[Import] = field(default_factory=list)
    symbol: Optional[Symbol] = None
    raw_source: Optional[str] = None  # Full file source for later analysis

    def to_dict(self) -> dict:
        """Convert to dictionary (for JSON serialization)."""
        return {
            "filepath": self.filepath,
            "line_number": self.line_number,
            "context_type": self.context_type,
            "content": self.content,
            "function_name": self.function_name,
            "class_name": self.class_name,
            "language": self.language.value,
            "imports": [
                {
                    "module_name": imp.module_name,
                    "alias": imp.alias,
                    "imported_names": imp.imported_names,
                    "resolved_path": imp.resolved_path,
                }
                for imp in self.imports
            ],
        }


@dataclass
class TraceFrame:
    """A single frame from a stack trace.

    Represents one level in the call stack from an error traceback.
    """
    filepath: str
    line_number: int
    function_name: Optional[str] = None
    column_number: Optional[int] = None
    code_snippet: Optional[str] = None
    language: Language = Language.UNKNOWN

    def __str__(self) -> str:
        parts = [f"{self.filepath}:{self.line_number}"]
        if self.function_name:
            parts.append(f" in {self.function_name}")
        return "".join(parts)


@dataclass
class ParsedTraceback:
    """A fully parsed traceback/stack trace.

    Contains all frames from the error plus the error message.
    """
    frames: List[TraceFrame] = field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    language: Language = Language.UNKNOWN
    raw_traceback: str = ""

    @property
    def primary_frame(self) -> Optional[TraceFrame]:
        """Get the primary frame (usually the last one where error occurred)."""
        if self.frames:
            return self.frames[-1]
        return None

    @property
    def files(self) -> List[str]:
        """Get list of unique file paths from all frames."""
        seen = set()
        result = []
        for frame in self.frames:
            if frame.filepath not in seen:
                seen.add(frame.filepath)
                result.append(frame.filepath)
        return result


@dataclass
class UpstreamContext:
    """Context from upstream modules (imports and callers).

    Used for deep debugging to trace root causes beyond the traceback.
    """
    file_contexts: List[FileContext] = field(default_factory=list)
    call_chain: List[str] = field(default_factory=list)  # ["module_a.func1", "module_b.func2"]
    relevant_definitions: dict = field(default_factory=dict)  # {symbol: code}
    dependency_summary: str = ""

    def to_prompt_text(self) -> str:
        """Format upstream context for inclusion in AI prompt."""
        parts = []

        if self.call_chain:
            parts.append("## CALL CHAIN")
            parts.append(" -> ".join(self.call_chain))

        if self.relevant_definitions:
            parts.append("\n## RELEVANT DEFINITIONS")
            for symbol, code in self.relevant_definitions.items():
                parts.append(f"\n### {symbol}")
                parts.append(code)

        if self.file_contexts:
            parts.append("\n## UPSTREAM FILE CONTEXTS")
            for ctx in self.file_contexts:
                parts.append(f"\n### {ctx.filepath}")
                parts.append(ctx.content)

        if self.dependency_summary:
            parts.append("\n## DEPENDENCY SUMMARY")
            parts.append(self.dependency_summary)

        return "\n".join(parts)


@dataclass
class AnalysisContext:
    """Complete context for AI analysis.

    Combines primary error context with traceback and upstream information.
    """
    primary_context: FileContext
    traceback_contexts: List[FileContext] = field(default_factory=list)
    upstream_context: Optional[UpstreamContext] = None
    parsed_traceback: Optional[ParsedTraceback] = None
    project_root: Optional[str] = None
    error_analysis: Optional[object] = None  # ErrorAnalysis from error_analyzer

    def to_prompt_text(self) -> str:
        """Format complete context for AI prompt."""
        parts = []

        # Primary error context
        parts.append("## PRIMARY ERROR CONTEXT")
        parts.append(f"File: {self.primary_context.filepath}")
        parts.append(f"Line: {self.primary_context.line_number}")
        if self.primary_context.function_name:
            parts.append(f"Function: {self.primary_context.function_name}")
        if self.primary_context.class_name:
            parts.append(f"Class: {self.primary_context.class_name}")
        parts.append(f"Language: {self.primary_context.language.value}")
        parts.append("\n```")
        parts.append(self.primary_context.content)
        parts.append("```")

        # Traceback contexts
        if self.traceback_contexts:
            parts.append("\n## TRACEBACK CONTEXTS")
            for ctx in self.traceback_contexts:
                if ctx.filepath != self.primary_context.filepath:
                    parts.append(f"\n### {ctx.filepath}:{ctx.line_number}")
                    if ctx.function_name:
                        parts.append(f"Function: {ctx.function_name}")
                    parts.append("```")
                    parts.append(ctx.content)
                    parts.append("```")

        # Upstream context for deep debugging
        if self.upstream_context:
            parts.append("\n## UPSTREAM CONTEXT (Deep Debugging)")
            parts.append(self.upstream_context.to_prompt_text())

        return "\n".join(parts)
