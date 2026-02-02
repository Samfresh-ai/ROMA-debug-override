"""Call chain analysis for tracing error origins.

Analyzes function call chains from tracebacks to understand
the flow of execution leading to an error.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict

from roma_debug.core.models import (
    Language, Symbol, TraceFrame, ParsedTraceback, FileContext
)
from roma_debug.parsers.registry import get_parser


@dataclass
class CallSite:
    """A single call site in the call chain."""
    filepath: str
    line_number: int
    function_name: Optional[str]
    called_function: Optional[str]
    arguments: Optional[str] = None
    language: Language = Language.UNKNOWN

    def __str__(self) -> str:
        func = self.function_name or "<module>"
        called = f" -> {self.called_function}" if self.called_function else ""
        return f"{Path(self.filepath).name}:{self.line_number} {func}{called}"


@dataclass
class CallChain:
    """A chain of function calls from entry point to error."""
    sites: List[CallSite] = field(default_factory=list)
    error_frame: Optional[TraceFrame] = None

    @property
    def entry_point(self) -> Optional[CallSite]:
        """Get the first call in the chain."""
        return self.sites[0] if self.sites else None

    @property
    def error_site(self) -> Optional[CallSite]:
        """Get the call site where the error occurred."""
        return self.sites[-1] if self.sites else None

    def to_string_list(self) -> List[str]:
        """Get chain as list of strings for AI prompt."""
        return [str(site) for site in self.sites]

    def __str__(self) -> str:
        return " -> ".join(self.to_string_list())


class CallChainAnalyzer:
    """Analyzes call chains from tracebacks and source code.

    Combines traceback information with source analysis to build
    a detailed picture of the call flow.
    """

    def __init__(self, project_root: Optional[str] = None):
        """Initialize the analyzer.

        Args:
            project_root: Root directory for file resolution
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._source_cache: Dict[str, str] = {}

    def analyze_traceback(self, traceback: ParsedTraceback) -> CallChain:
        """Build a call chain from a parsed traceback.

        Args:
            traceback: Parsed traceback with frames

        Returns:
            CallChain representing the execution flow
        """
        chain = CallChain()
        chain.error_frame = traceback.primary_frame

        for i, frame in enumerate(traceback.frames):
            # Determine what function was called (from next frame)
            called_function = None
            if i + 1 < len(traceback.frames):
                next_frame = traceback.frames[i + 1]
                called_function = next_frame.function_name

            site = CallSite(
                filepath=frame.filepath,
                line_number=frame.line_number,
                function_name=frame.function_name,
                called_function=called_function,
                language=frame.language,
            )
            chain.sites.append(site)

        return chain

    def analyze_from_contexts(
        self,
        contexts: List[FileContext],
        traceback: Optional[ParsedTraceback] = None,
    ) -> CallChain:
        """Build a call chain from file contexts.

        Uses source analysis to extract additional call information.

        Args:
            contexts: List of FileContext objects from traceback files
            traceback: Optional parsed traceback for additional info

        Returns:
            CallChain with enhanced information
        """
        chain = CallChain()

        for ctx in contexts:
            # Get function/class names from context
            function_name = ctx.function_name
            if not function_name and ctx.class_name:
                function_name = f"{ctx.class_name}.__init__"

            # Try to find what function is called at the error line
            called_function = self._find_called_function(ctx)

            site = CallSite(
                filepath=ctx.filepath,
                line_number=ctx.line_number,
                function_name=function_name,
                called_function=called_function,
                language=ctx.language,
            )
            chain.sites.append(site)

        return chain

    def _find_called_function(self, context: FileContext) -> Optional[str]:
        """Find the function called at the error line.

        Args:
            context: FileContext with source content

        Returns:
            Name of the called function or None
        """
        if not context.symbol:
            return None

        # Get the parser for this language
        parser = get_parser(context.language, create_new=True)
        if not parser:
            return None

        # Parse the source if available
        source = self._get_source(context.filepath)
        if not source:
            return None

        if not parser.parse(source, context.filepath):
            return None

        # For Python, we can use the AST parser's call extraction
        if hasattr(parser, 'get_function_calls_in_symbol'):
            calls = parser.get_function_calls_in_symbol(context.symbol)
            if calls:
                # Return the most likely called function
                # (this is a simplification - ideally we'd analyze the specific line)
                return calls[0]

        return None

    def _get_source(self, filepath: str) -> Optional[str]:
        """Get source code for a file with caching.

        Args:
            filepath: Path to the file

        Returns:
            Source code string or None
        """
        if filepath in self._source_cache:
            return self._source_cache[filepath]

        try:
            path = Path(filepath)
            if not path.exists():
                # Try relative to project root
                path = self.project_root / filepath
                if not path.exists():
                    return None

            source = path.read_text(encoding='utf-8', errors='replace')
            self._source_cache[filepath] = source
            return source
        except Exception:
            return None

    def find_data_flow(
        self,
        chain: CallChain,
        variable_name: str,
    ) -> List[CallSite]:
        """Trace where a variable's value comes from in the call chain.

        Args:
            chain: The call chain to analyze
            variable_name: Name of the variable to trace

        Returns:
            List of call sites where the variable is assigned/modified
        """
        # This is a simplified implementation
        # Full data flow analysis would require proper static analysis

        relevant_sites = []

        for site in chain.sites:
            source = self._get_source(site.filepath)
            if not source:
                continue

            lines = source.splitlines()
            if 0 <= site.line_number - 1 < len(lines):
                line = lines[site.line_number - 1]

                # Simple check: does this line assign to the variable?
                if f"{variable_name} =" in line or f"{variable_name}=" in line:
                    relevant_sites.append(site)
                # Check for function parameter
                elif f"{variable_name}" in line and ("def " in line or "func " in line):
                    relevant_sites.append(site)

        return relevant_sites

    def get_upstream_callers(
        self,
        filepath: str,
        function_name: str,
        contexts: List[FileContext],
    ) -> List[CallSite]:
        """Find callers of a function from the provided contexts.

        Args:
            filepath: File containing the function
            function_name: Name of the function
            contexts: File contexts to search

        Returns:
            List of call sites that call this function
        """
        callers = []

        for ctx in contexts:
            if ctx.filepath == filepath:
                continue

            source = self._get_source(ctx.filepath)
            if not source:
                continue

            # Simple search for function calls
            lines = source.splitlines()
            for i, line in enumerate(lines, 1):
                # Look for function call patterns
                if f"{function_name}(" in line:
                    callers.append(CallSite(
                        filepath=ctx.filepath,
                        line_number=i,
                        function_name=ctx.function_name,
                        called_function=function_name,
                        language=ctx.language,
                    ))

        return callers
