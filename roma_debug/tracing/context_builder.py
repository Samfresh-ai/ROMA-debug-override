"""Context builder for deep debugging.

Assembles comprehensive context for AI analysis by combining
traceback information, import resolution, and dependency analysis.
Includes project scanning for deep project awareness.
"""

import os
from pathlib import Path
from typing import Optional, List, Tuple

from roma_debug.core.models import (
    Language, Import, FileContext, UpstreamContext, AnalysisContext,
    ParsedTraceback, Symbol
)
from roma_debug.parsers.registry import get_parser, detect_language
from roma_debug.parsers.traceback_patterns import parse_traceback
from roma_debug.tracing.import_resolver import ImportResolver
from roma_debug.tracing.dependency_graph import DependencyGraph
from roma_debug.tracing.call_chain import CallChainAnalyzer, CallChain
from roma_debug.tracing.project_scanner import ProjectScanner, ProjectInfo
from roma_debug.tracing.error_analyzer import ErrorAnalyzer, ErrorAnalysis


class ContextBuilder:
    """Builds comprehensive context for AI-powered debugging.

    Coordinates all the analysis components to produce rich context
    for the AI to understand errors and suggest fixes.
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        max_upstream_files: int = 5,
        max_context_lines: int = 100,
        scan_project: bool = True,
    ):
        """Initialize the context builder.

        Args:
            project_root: Root directory of the project
            max_upstream_files: Maximum upstream files to include
            max_context_lines: Maximum lines per context snippet
            scan_project: Whether to scan project structure on init
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.max_upstream_files = max_upstream_files
        self.max_context_lines = max_context_lines

        self.import_resolver = ImportResolver(str(self.project_root))
        self.dependency_graph = DependencyGraph(str(self.project_root))
        self.call_chain_analyzer = CallChainAnalyzer(str(self.project_root))

        # Project scanner for deep awareness
        self.project_scanner = ProjectScanner(str(self.project_root))
        self.error_analyzer = ErrorAnalyzer(self.project_scanner)
        self._project_info: Optional[ProjectInfo] = None
        self._file_tree_cache: Optional[str] = None

        if scan_project:
            self._project_info = self.project_scanner.scan()

    @property
    def project_info(self) -> ProjectInfo:
        """Get project info, scanning if needed."""
        if self._project_info is None:
            self._project_info = self.project_scanner.scan()
        return self._project_info

    def get_file_tree(self, max_depth: int = 4, max_files_per_dir: int = 15) -> str:
        """Get cached file tree representation."""
        if self._file_tree_cache is None:
            self._file_tree_cache = self.project_scanner.generate_file_tree(
                max_depth=max_depth,
                max_files_per_dir=max_files_per_dir,
            )
        return self._file_tree_cache

    def build_analysis_context(
        self,
        error_log: str,
        file_contexts: Optional[List[FileContext]] = None,
        language_hint: Optional[Language] = None,
    ) -> AnalysisContext:
        """Build complete analysis context from an error log.

        Args:
            error_log: The error log/traceback string
            file_contexts: Optional pre-extracted file contexts
            language_hint: Optional language hint

        Returns:
            AnalysisContext ready for AI prompt
        """
        # Parse the traceback
        traceback = parse_traceback(error_log, language_hint)

        # Get file contexts if not provided
        if file_contexts is None:
            file_contexts = self._extract_file_contexts(traceback)

        if not file_contexts:
            # No file contexts - return minimal context
            return self._create_minimal_context(error_log, traceback)

        # Determine primary context (usually the error location)
        primary_context = self._get_primary_context(file_contexts, traceback)

        # Resolve imports and build dependency graph
        for ctx in file_contexts:
            resolved_imports = self.import_resolver.resolve_imports(
                ctx.imports,
                Path(ctx.filepath),
            )
            ctx.imports = resolved_imports
            self.dependency_graph.add_file_context(ctx)

        # Build upstream context for deep debugging
        upstream_context = self._build_upstream_context(
            primary_context,
            file_contexts,
            traceback,
        )

        return AnalysisContext(
            primary_context=primary_context,
            traceback_contexts=file_contexts,
            upstream_context=upstream_context,
            parsed_traceback=traceback,
            project_root=str(self.project_root),
        )

    def _extract_file_contexts(self, traceback: ParsedTraceback) -> List[FileContext]:
        """Extract file contexts from traceback frames.

        Args:
            traceback: Parsed traceback

        Returns:
            List of FileContext objects
        """
        contexts = []

        for frame in traceback.frames:
            context = self._extract_single_context(
                frame.filepath,
                frame.line_number,
                traceback.language,
            )
            if context and context.context_type != "missing":
                contexts.append(context)

        return contexts

    def _extract_single_context(
        self,
        filepath: str,
        line_number: int,
        language: Language,
    ) -> Optional[FileContext]:
        """Extract context from a single file.

        Args:
            filepath: Path to the file
            line_number: Error line number
            language: Language of the file

        Returns:
            FileContext or None if file not found
        """
        # Try to resolve the file path
        resolved_path = self._resolve_file_path(filepath)
        if not resolved_path:
            return FileContext(
                filepath=filepath,
                line_number=line_number,
                context_type="missing",
                content=f"[File not found: {filepath}]",
                language=language,
            )

        try:
            source = Path(resolved_path).read_text(encoding='utf-8', errors='replace')
            lines = source.splitlines()
        except Exception as e:
            return FileContext(
                filepath=filepath,
                line_number=line_number,
                context_type="missing",
                content=f"[Error reading file: {e}]",
                language=language,
            )

        # Detect language if unknown
        if language == Language.UNKNOWN:
            language = detect_language(resolved_path)

        # Try parser-based extraction
        parser = get_parser(language, create_new=True)
        if parser and parser.parse(source, resolved_path):
            symbol = parser.find_enclosing_symbol(line_number)
            imports = parser.extract_imports()

            if symbol:
                start = max(1, symbol.start_line - 2)
                end = min(len(lines), symbol.end_line + 2)
                snippet = parser.format_snippet(start, end, highlight_line=line_number)

                return FileContext(
                    filepath=resolved_path,
                    line_number=line_number,
                    context_type="ast" if language == Language.PYTHON else "treesitter",
                    content=snippet,
                    function_name=symbol.name if symbol.kind in ("function", "method") else None,
                    class_name=symbol.parent.name if symbol.parent and symbol.parent.kind == "class" else None,
                    language=language,
                    imports=imports,
                    symbol=symbol,
                    raw_source=source,
                )

            # Fallback to line-based extraction
            return self._line_based_context(resolved_path, lines, line_number, language, imports)

        # Fallback if parser fails
        return self._line_based_context(resolved_path, lines, line_number, language)

    def _line_based_context(
        self,
        filepath: str,
        lines: List[str],
        line_number: int,
        language: Language,
        imports: Optional[List[Import]] = None,
    ) -> FileContext:
        """Create context using line-based extraction.

        Args:
            filepath: Path to the file
            lines: Source lines
            line_number: Error line number
            language: Language of the file
            imports: Optional pre-extracted imports

        Returns:
            FileContext with line-based content
        """
        context_lines = min(50, self.max_context_lines // 2)
        start = max(1, line_number - context_lines)
        end = min(len(lines), line_number + context_lines)

        snippet_lines = []
        for i in range(start - 1, end):
            num = i + 1
            marker = " >> " if num == line_number else "    "
            snippet_lines.append(f"{marker}{num:4d} | {lines[i]}")

        return FileContext(
            filepath=filepath,
            line_number=line_number,
            context_type="lines",
            content="\n".join(snippet_lines),
            language=language,
            imports=imports or [],
        )

    def _get_primary_context(
        self,
        contexts: List[FileContext],
        traceback: ParsedTraceback,
    ) -> FileContext:
        """Determine the primary error context.

        Usually the last non-missing context in the traceback.

        Args:
            contexts: All file contexts
            traceback: Parsed traceback

        Returns:
            The primary FileContext
        """
        # Try to find context for the primary frame
        if traceback.primary_frame:
            for ctx in reversed(contexts):
                if ctx.filepath.endswith(traceback.primary_frame.filepath) or \
                   traceback.primary_frame.filepath.endswith(ctx.filepath):
                    if ctx.context_type != "missing":
                        return ctx

        # Fallback: last non-missing context
        for ctx in reversed(contexts):
            if ctx.context_type != "missing":
                return ctx

        # If all missing, return the last one
        return contexts[-1]

    def _build_upstream_context(
        self,
        primary_context: FileContext,
        traceback_contexts: List[FileContext],
        traceback: ParsedTraceback,
    ) -> Optional[UpstreamContext]:
        """Build upstream context for deep debugging.

        Analyzes imports and dependencies to find potentially
        relevant upstream code.

        Args:
            primary_context: The primary error context
            traceback_contexts: All traceback contexts
            traceback: Parsed traceback

        Returns:
            UpstreamContext or None if no upstream context found
        """
        upstream_files = []
        relevant_definitions = {}

        # Get call chain
        call_chain = self.call_chain_analyzer.analyze_from_contexts(
            traceback_contexts, traceback
        )

        # Find upstream files from imports
        for ctx in traceback_contexts:
            for imp in ctx.imports:
                if imp.resolved_path and imp.resolved_path not in upstream_files:
                    # Check if this import is already in traceback
                    is_in_traceback = any(
                        tc.filepath == imp.resolved_path
                        for tc in traceback_contexts
                    )
                    if not is_in_traceback:
                        upstream_files.append(imp.resolved_path)

        # Get files that depend on the primary context
        dependents = self.dependency_graph.get_dependents(primary_context.filepath)
        for dep in dependents:
            if dep not in upstream_files:
                upstream_files.append(dep)

        # Limit to max_upstream_files
        upstream_files = upstream_files[:self.max_upstream_files]

        # Extract contexts for upstream files
        upstream_contexts = []
        for filepath in upstream_files:
            ctx = self._extract_single_context(
                filepath,
                1,  # Just get the file overview
                detect_language(filepath),
            )
            if ctx and ctx.context_type != "missing":
                upstream_contexts.append(ctx)

        if not upstream_contexts and not call_chain.sites:
            return None

        # Build dependency summary
        summary = self.dependency_graph.get_summary()

        return UpstreamContext(
            file_contexts=upstream_contexts,
            call_chain=call_chain.to_string_list(),
            relevant_definitions=relevant_definitions,
            dependency_summary=summary,
        )

    def _create_minimal_context(
        self,
        error_log: str,
        traceback: ParsedTraceback,
    ) -> AnalysisContext:
        """Create context when no explicit traceback files are found.

        Uses project scanning and error analysis to find relevant files.

        Args:
            error_log: Original error log
            traceback: Parsed traceback

        Returns:
            AnalysisContext with project-aware context
        """
        # Analyze the error to find relevant files
        error_analysis = self.error_analyzer.analyze(error_log)

        # Get relevant files from error analysis
        relevant_files = error_analysis.relevant_files

        # If we found relevant files, extract their contexts
        file_contexts = []
        primary_context = None

        if relevant_files:
            # Try to create contexts for relevant files
            for pf in relevant_files[:3]:  # Top 3 most relevant
                full_path = str(self.project_root / pf.path)
                ctx = self._extract_single_context(
                    full_path,
                    1,  # Start of file
                    pf.language,
                )
                if ctx and ctx.context_type != "missing":
                    file_contexts.append(ctx)
                    if primary_context is None:
                        primary_context = ctx

        # If still no context, use entry points
        if not primary_context and self.project_info.entry_points:
            for ep in self.project_info.entry_points[:2]:
                full_path = str(self.project_root / ep.path)
                ctx = self._extract_single_context(
                    full_path,
                    1,
                    ep.language,
                )
                if ctx and ctx.context_type != "missing":
                    file_contexts.append(ctx)
                    if primary_context is None:
                        primary_context = ctx

        # Create synthetic primary context if still none found
        if primary_context is None:
            primary_context = FileContext(
                filepath="<error_log>",
                line_number=0,
                context_type="error_analysis",
                content=error_log,
                language=error_analysis.suggested_language or traceback.language,
            )

        # Build upstream context with project info
        upstream_context = None
        if file_contexts:
            upstream_context = UpstreamContext(
                file_contexts=file_contexts[1:] if len(file_contexts) > 1 else [],
                call_chain=[],
                relevant_definitions={},
                dependency_summary=self.project_info.to_summary(),
            )

        return AnalysisContext(
            primary_context=primary_context,
            traceback_contexts=file_contexts,
            upstream_context=upstream_context,
            parsed_traceback=traceback,
            project_root=str(self.project_root),
            error_analysis=error_analysis,
        )

    def _resolve_file_path(self, filepath: str) -> Optional[str]:
        """Resolve a file path to an actual file.

        Args:
            filepath: Path from traceback

        Returns:
            Resolved path or None
        """
        # Try as-is
        if os.path.isfile(filepath):
            return filepath

        # Try relative to project root
        relative = self.project_root / filepath
        if relative.is_file():
            return str(relative)

        # Try just the filename in project
        filename = Path(filepath).name
        for root, dirs, files in os.walk(self.project_root):
            if filename in files:
                return os.path.join(root, filename)

        # Try common source directories
        for src_dir in ['src', 'lib', 'app', 'pkg', '.']:
            candidate = self.project_root / src_dir / filename
            if candidate.is_file():
                return str(candidate)

        return None

    def get_context_for_prompt(
        self,
        analysis_context: AnalysisContext,
        include_upstream: bool = True,
        include_project_info: bool = True,
        include_file_tree: bool = True,
    ) -> str:
        """Format analysis context for AI prompt.

        Args:
            analysis_context: The AnalysisContext to format
            include_upstream: Whether to include upstream context
            include_project_info: Whether to include project structure info
            include_file_tree: Whether to include file tree structure

        Returns:
            Formatted context string
        """
        parts = []

        # Include project structure info for context
        if include_project_info and self._project_info:
            parts.append("## PROJECT INFORMATION")
            parts.append(f"Type: {self._project_info.project_type}")
            parts.append(f"Language: {self._project_info.primary_language.value}")
            if self._project_info.frameworks_detected:
                parts.append(f"Frameworks: {', '.join(self._project_info.frameworks_detected)}")
            if self._project_info.entry_points:
                parts.append(f"Entry Points: {', '.join(ep.path for ep in self._project_info.entry_points[:3])}")
            parts.append("")

        # Include file tree for environmental awareness
        if include_file_tree:
            file_tree = self.get_file_tree(max_depth=4, max_files_per_dir=15)
            parts.append("<ProjectStructure>")
            parts.append("## FILE TREE")
            parts.append("Use this tree to verify file paths exist before suggesting changes.")
            parts.append("Do NOT assume a file exists unless you see it here.")
            parts.append("")
            parts.append("```")
            parts.append(file_tree)
            parts.append("```")
            parts.append("</ProjectStructure>")
            parts.append("")

        # Include error analysis if present
        if analysis_context.error_analysis:
            ea = analysis_context.error_analysis
            parts.append("## ERROR ANALYSIS")
            parts.append(f"Error Type: {ea.error_type}")
            parts.append(f"Category: {ea.error_category}")
            if ea.affected_routes:
                parts.append(f"Affected Routes: {', '.join(ea.affected_routes)}")
            if ea.relevant_files:
                parts.append(f"Relevant Files: {', '.join(f.path for f in ea.relevant_files[:5])}")
            parts.append("")

        # Primary context
        parts.append("## PRIMARY ERROR LOCATION")
        if analysis_context.primary_context.filepath != "<error_log>":
            parts.append(f"File: {analysis_context.primary_context.filepath}")
            parts.append(f"Line: {analysis_context.primary_context.line_number}")
            if analysis_context.primary_context.function_name:
                parts.append(f"Function: {analysis_context.primary_context.function_name}")
            parts.append(f"Language: {analysis_context.primary_context.language.value}")
            parts.append("\n```")
            parts.append(analysis_context.primary_context.content)
            parts.append("```\n")
        else:
            # No specific file found - show error message
            parts.append("(No specific file path in error)")
            parts.append(f"Language: {analysis_context.primary_context.language.value}")
            parts.append("\nError Message:")
            parts.append(analysis_context.primary_context.content[:1000])
            parts.append("")

        # Other traceback locations
        other_contexts = [
            ctx for ctx in analysis_context.traceback_contexts
            if ctx.filepath != analysis_context.primary_context.filepath
        ]
        if other_contexts:
            parts.append("## CALL STACK CONTEXT")
            for ctx in other_contexts:
                parts.append(f"\n### {ctx.filepath}:{ctx.line_number}")
                if ctx.function_name:
                    parts.append(f"Function: {ctx.function_name}")
                parts.append("```")
                parts.append(ctx.content)
                parts.append("```")

        # Upstream context
        if include_upstream and analysis_context.upstream_context:
            parts.append("\n## UPSTREAM CONTEXT (for root cause analysis)")
            parts.append(analysis_context.upstream_context.to_prompt_text())

        return "\n".join(parts)

    def get_deep_context(self, error_log: str, language_hint: Optional[Language] = None) -> str:
        """Get comprehensive context for an error with full project awareness.

        This method provides THOROUGH context for the AI, including:
        - Project structure and frameworks
        - FILE TREE for environmental awareness
        - Error analysis
        - FULL contents of relevant files (not truncated)
        - Entry point contents
        - Related file existence checks

        Args:
            error_log: The error message/log
            language_hint: Optional language hint

        Returns:
            Comprehensive context string for AI
        """
        # Build analysis context
        analysis_ctx = self.build_analysis_context(error_log, language_hint=language_hint)

        parts = []

        # Project info
        if self._project_info:
            parts.append("## PROJECT INFORMATION")
            parts.append(f"Type: {self._project_info.project_type}")
            parts.append(f"Language: {self._project_info.primary_language.value}")
            if self._project_info.frameworks_detected:
                parts.append(f"Frameworks: {', '.join(self._project_info.frameworks_detected)}")
            parts.append("")

        # FILE TREE - Critical for environmental awareness
        parts.append("<ProjectStructure>")
        parts.append("## PROJECT FILE TREE")
        parts.append("IMPORTANT: Use this tree to verify file paths before suggesting changes.")
        parts.append("- Do NOT assume a file exists unless you see it in this tree.")
        parts.append("- If a file is MISSING from an expected location, look for it elsewhere in the tree.")
        parts.append("- When suggesting fixes for 'file not found' errors, use this tree to find the actual file location.")
        parts.append("")
        file_tree = self.project_scanner.generate_file_tree(max_depth=5, max_files_per_dir=20)
        parts.append("```")
        parts.append(file_tree)
        parts.append("```")
        parts.append("</ProjectStructure>")
        parts.append("")

        # Error analysis
        if analysis_ctx.error_analysis:
            ea = analysis_ctx.error_analysis
            parts.append("## ERROR ANALYSIS")
            parts.append(f"Error Type: {ea.error_type}")
            parts.append(f"Category: {ea.error_category}")
            if ea.affected_routes:
                parts.append(f"Affected Routes: {', '.join(ea.affected_routes)}")
            parts.append("")

        # Original error message
        parts.append("## ORIGINAL ERROR")
        parts.append("```")
        parts.append(error_log)
        parts.append("```")
        parts.append("")

        # Check for file paths mentioned in error
        parts.append("## FILE EXISTENCE CHECK")
        import re
        file_paths = re.findall(r'[/\w\-\.]+\.(?:html|js|ts|py|css|json)', error_log)
        for fp in file_paths[:5]:
            full_path = self.project_root / fp.lstrip('/')
            exists = full_path.exists()
            parts.append(f"- {fp}: {'EXISTS' if exists else 'MISSING'}")
        parts.append("")

        # FULL contents of relevant files - this is the key fix
        files_added = set()
        parts.append("## SOURCE FILES TO ANALYZE AND FIX")
        parts.append("(Read these files carefully before suggesting fixes)")
        parts.append("")

        # Add entry points with FULL content
        for ep in self.project_info.entry_points[:3]:
            if ep.path in files_added:
                continue
            content = self.project_scanner.get_file_content(ep.path)
            if content:
                files_added.add(ep.path)
                parts.append(f"### FILE: {ep.path}")
                parts.append(f"Language: {ep.language.value}")
                parts.append(f"```{ep.language.value}")
                parts.append(content)  # FULL content, no truncation
                parts.append("```")
                parts.append("")

        # Add relevant files from error analysis with FULL content
        if analysis_ctx.error_analysis and analysis_ctx.error_analysis.relevant_files:
            for rf in analysis_ctx.error_analysis.relevant_files[:5]:
                if rf.path in files_added:
                    continue
                content = self.project_scanner.get_file_content(rf.path)
                if content:
                    files_added.add(rf.path)
                    parts.append(f"### FILE: {rf.path}")
                    parts.append(f"Language: {rf.language.value}")
                    parts.append(f"```{rf.language.value}")
                    parts.append(content)  # FULL content
                    parts.append("```")
                    parts.append("")

        # If error mentions specific directories, check their structure
        if 'public' in error_log.lower() or 'static' in error_log.lower():
            parts.append("## DIRECTORY STRUCTURE CHECK")
            for dirname in ['public', 'static', 'build', 'dist']:
                dir_path = self.project_root / dirname
                if dir_path.exists():
                    files = list(dir_path.iterdir())[:10]
                    parts.append(f"- {dirname}/: {[f.name for f in files]}")
                else:
                    parts.append(f"- {dirname}/: DOES NOT EXIST")
            parts.append("")

        # Instructions for AI
        parts.append("## INSTRUCTIONS")
        parts.append("FIRST: Determine if this is a CODE ERROR or a QUESTION.")
        parts.append("")
        parts.append("If QUESTION (how many files, where is X, explain, list files, etc.):")
        parts.append("- Set action_type to 'ANSWER'")
        parts.append("- LOOK at the <ProjectStructure> file tree above to answer")
        parts.append("- If the item EXISTS: Count/list it precisely from the tree")
        parts.append("- If the item DOESN'T EXIST: Be helpful - say so AND suggest alternatives")
        parts.append("  Example: 'No room/ folder, but these folders exist: src/, tests/, public/'")
        parts.append("- Put your answer in the explanation field")
        parts.append("- Set filepath to null and full_code_block to ''")
        parts.append("- DO NOT write code - just read the tree and answer")
        parts.append("")
        parts.append("If CODE ERROR (traceback, exception, 'not working', crash, bug):")
        parts.append("- Set action_type to 'PATCH'")
        parts.append("- CHECK the <ProjectStructure> tree to verify paths exist")
        parts.append("- Provide MINIMAL fixes - only address the actual error")
        parts.append("- Do NOT add new features or improvements")

        return "\n".join(parts)
