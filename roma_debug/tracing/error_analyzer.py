"""Error analyzer for understanding errors without explicit tracebacks.

Analyzes error messages to:
- Identify error type and category
- Find relevant files in the project
- Provide targeted context for AI fixing
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

from roma_debug.core.models import Language, FileContext
from roma_debug.tracing.project_scanner import ProjectScanner, ProjectInfo, ProjectFile


@dataclass
class ErrorAnalysis:
    """Result of analyzing an error message."""
    error_type: str  # 'http', 'runtime', 'syntax', 'import', 'config', 'unknown'
    error_category: str  # More specific: '404', 'type_error', 'module_not_found', etc.
    error_message: str
    suggested_language: Optional[Language] = None
    relevant_files: List[ProjectFile] = field(default_factory=list)
    affected_routes: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1 confidence in analysis

    def to_context_string(self) -> str:
        """Format analysis as context string for AI."""
        lines = [
            "## ERROR ANALYSIS",
            f"Type: {self.error_type}",
            f"Category: {self.error_category}",
            f"Message: {self.error_message}",
        ]

        if self.suggested_language:
            lines.append(f"Language: {self.suggested_language.value}")

        if self.affected_routes:
            lines.append(f"Affected Routes: {', '.join(self.affected_routes)}")

        if self.relevant_files:
            lines.append("\n### Relevant Files:")
            for f in self.relevant_files:
                lines.append(f"- {f.path}")

        return "\n".join(lines)


# Error pattern matchers
ERROR_PATTERNS = {
    # HTTP/Web errors
    'http_404': [
        (r'cannot\s+(?:get|post|put|delete|patch)\s+[/\w]+', 0.9),
        (r'404\s+(?:not\s+found|\(not\s+found\))', 0.95),
        (r'get\s+http://.*\s+404', 0.95),
        (r'route\s+not\s+found', 0.9),
        (r'no\s+route\s+matches', 0.9),
    ],
    'http_500': [
        (r'500\s+internal\s+server\s+error', 0.95),
        (r'internal\s+server\s+error', 0.8),
    ],
    'http_400': [
        (r'400\s+bad\s+request', 0.95),
        (r'bad\s+request', 0.7),
    ],
    'http_401': [
        (r'401\s+unauthorized', 0.95),
        (r'authentication\s+required', 0.85),
        (r'not\s+authenticated', 0.8),
    ],
    'http_403': [
        (r'403\s+forbidden', 0.95),
        (r'permission\s+denied', 0.8),
        (r'access\s+denied', 0.8),
    ],
    'static_file': [
        (r'cannot\s+(?:get|find|serve)\s+.*\.(?:html|css|js|png|jpg|svg)', 0.9),
        (r'static\s+file\s+not\s+found', 0.9),
        (r'failed\s+to\s+load\s+resource', 0.85),
        (r'enoent.*index\.html', 0.95),
        (r'enoent.*public', 0.9),
        (r'enoent.*static', 0.9),
        (r'no\s+such\s+file.*\.html', 0.95),
        (r'no\s+such\s+file.*public', 0.9),
    ],
    'file_not_found': [
        (r'enoent', 0.9),
        (r'no\s+such\s+file\s+or\s+directory', 0.95),
        (r'file\s+not\s+found', 0.9),
        (r'cannot\s+find\s+(?:file|path)', 0.85),
    ],

    # Python errors
    'python_import': [
        (r'modulenotfounderror', 0.95),
        (r'importerror', 0.9),
        (r'no\s+module\s+named', 0.95),
        (r'cannot\s+import\s+name', 0.9),
    ],
    'python_attribute': [
        (r'attributeerror', 0.95),
        (r'has\s+no\s+attribute', 0.9),
    ],
    'python_type': [
        (r'typeerror', 0.95),
        (r'expected\s+\w+\s+got\s+\w+', 0.8),
    ],
    'python_value': [
        (r'valueerror', 0.95),
        (r'invalid\s+value', 0.7),
    ],
    'python_key': [
        (r'keyerror', 0.95),
    ],
    'python_index': [
        (r'indexerror', 0.95),
        (r'list\s+index\s+out\s+of\s+range', 0.95),
    ],
    'python_name': [
        (r'nameerror', 0.95),
        (r'name\s+[\'"]?\w+[\'"]?\s+is\s+not\s+defined', 0.9),
    ],
    'python_syntax': [
        (r'syntaxerror', 0.95),
        (r'invalid\s+syntax', 0.9),
    ],

    # JavaScript/Node errors
    'js_reference': [
        (r'referenceerror', 0.95),
        (r'is\s+not\s+defined', 0.8),
    ],
    'js_type': [
        (r'typeerror.*undefined', 0.9),
        (r'cannot\s+read\s+propert', 0.9),
        (r'is\s+not\s+a\s+function', 0.9),
    ],
    'js_syntax': [
        (r'syntaxerror.*javascript', 0.9),
        (r'unexpected\s+token', 0.85),
    ],
    'js_module': [
        (r'cannot\s+find\s+module', 0.95),
        (r'module\s+not\s+found', 0.9),
    ],

    # Go errors
    'go_panic': [
        (r'panic:', 0.95),
        (r'runtime\s+error:', 0.9),
    ],
    'go_nil': [
        (r'nil\s+pointer', 0.95),
        (r'invalid\s+memory\s+address', 0.9),
    ],

    # Rust errors
    'rust_panic': [
        (r'thread\s+.*\s+panicked', 0.95),
        (r'called\s+`option::unwrap\(\)`', 0.9),
    ],

    # Database errors
    'database': [
        (r'database\s+error', 0.85),
        (r'sql\s+error', 0.9),
        (r'connection\s+refused.*(?:5432|3306|27017)', 0.9),  # Common DB ports
        (r'operationalerror.*database', 0.9),
    ],

    # Config/Environment errors
    'config': [
        (r'api\s*key\s+(?:not\s+(?:set|found|valid)|invalid)', 0.9),
        (r'missing\s+(?:env|environment)\s+variable', 0.9),
        (r'configuration\s+error', 0.85),
        (r'\.env\s+(?:not\s+found|missing)', 0.9),
    ],

    # Connection errors
    'connection': [
        (r'connection\s+refused', 0.9),
        (r'econnrefused', 0.95),
        (r'connection\s+timed?\s*out', 0.9),
        (r'network\s+error', 0.8),
    ],
}

# Map error categories to error types
CATEGORY_TO_TYPE = {
    'http_404': 'http',
    'http_500': 'http',
    'http_400': 'http',
    'http_401': 'http',
    'http_403': 'http',
    'static_file': 'static',
    'file_not_found': 'filesystem',
    'python_import': 'import',
    'python_attribute': 'runtime',
    'python_type': 'runtime',
    'python_value': 'runtime',
    'python_key': 'runtime',
    'python_index': 'runtime',
    'python_name': 'runtime',
    'python_syntax': 'syntax',
    'js_reference': 'runtime',
    'js_type': 'runtime',
    'js_syntax': 'syntax',
    'js_module': 'import',
    'go_panic': 'runtime',
    'go_nil': 'runtime',
    'rust_panic': 'runtime',
    'database': 'database',
    'config': 'config',
    'connection': 'connection',
}

# Language hints from error patterns
CATEGORY_TO_LANGUAGE = {
    'python_import': Language.PYTHON,
    'python_attribute': Language.PYTHON,
    'python_type': Language.PYTHON,
    'python_value': Language.PYTHON,
    'python_key': Language.PYTHON,
    'python_index': Language.PYTHON,
    'python_name': Language.PYTHON,
    'python_syntax': Language.PYTHON,
    'js_reference': Language.JAVASCRIPT,
    'js_type': Language.JAVASCRIPT,
    'js_syntax': Language.JAVASCRIPT,
    'js_module': Language.JAVASCRIPT,
    'go_panic': Language.GO,
    'go_nil': Language.GO,
    'rust_panic': Language.RUST,
}


class ErrorAnalyzer:
    """Analyzes errors to extract meaning and find relevant files."""

    def __init__(self, project_scanner: Optional[ProjectScanner] = None):
        """Initialize the analyzer.

        Args:
            project_scanner: Optional project scanner for file discovery
        """
        self.scanner = project_scanner

    def analyze(self, error_message: str) -> ErrorAnalysis:
        """Analyze an error message.

        Args:
            error_message: The error message or log to analyze

        Returns:
            ErrorAnalysis with extracted information
        """
        error_lower = error_message.lower()

        # Detect error category
        category, confidence = self._detect_category(error_lower)
        error_type = CATEGORY_TO_TYPE.get(category, 'unknown')
        suggested_lang = CATEGORY_TO_LANGUAGE.get(category)

        # Extract routes from HTTP errors
        affected_routes = self._extract_routes(error_message)

        # Extract keywords
        keywords = self._extract_keywords(error_message)

        # Find relevant files if scanner available
        relevant_files = []
        if self.scanner:
            relevant_files = self.scanner.find_relevant_files(error_message, limit=5)

            # If no language detected, use project's primary language
            if not suggested_lang:
                info = self.scanner.scan()
                suggested_lang = info.primary_language

        return ErrorAnalysis(
            error_type=error_type,
            error_category=category,
            error_message=error_message[:500],  # Truncate long messages
            suggested_language=suggested_lang,
            relevant_files=relevant_files,
            affected_routes=affected_routes,
            keywords=keywords,
            confidence=confidence,
        )

    def _detect_category(self, error_lower: str) -> Tuple[str, float]:
        """Detect error category from message.

        Returns:
            Tuple of (category, confidence)
        """
        best_category = 'unknown'
        best_confidence = 0.0

        for category, patterns in ERROR_PATTERNS.items():
            for pattern, conf in patterns:
                if re.search(pattern, error_lower):
                    if conf > best_confidence:
                        best_category = category
                        best_confidence = conf

        return best_category, best_confidence

    def _extract_routes(self, error_message: str) -> List[str]:
        """Extract URL routes from error message."""
        routes = []

        # Pattern for routes in "Cannot GET /path" style
        route_patterns = [
            r'cannot\s+(?:get|post|put|delete|patch)\s+([/\w\-\.]+)',
            r'(?:get|post|put|delete|patch)\s+([/\w\-\.]+)\s+(?:404|failed)',
            r'route\s+[\'"]?([/\w\-\.]+)[\'"]?',
            r'path\s+[\'"]?([/\w\-\.]+)[\'"]?',
        ]

        for pattern in route_patterns:
            matches = re.findall(pattern, error_message, re.IGNORECASE)
            routes.extend(matches)

        # Deduplicate
        return list(dict.fromkeys(routes))

    def _extract_keywords(self, error_message: str) -> List[str]:
        """Extract relevant keywords from error."""
        keywords = []

        # Extract quoted strings
        quoted = re.findall(r'[\'"]([^\'"]{2,30})[\'"]', error_message)
        keywords.extend(quoted)

        # Extract identifiers
        identifiers = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', error_message)
        keywords.extend(identifiers)

        identifiers = re.findall(r'\b([a-z]+(?:_[a-z]+)+)\b', error_message)
        keywords.extend(identifiers)

        # Extract file references
        files = re.findall(r'[\w\-]+\.(?:py|js|ts|go|rs|java)', error_message)
        keywords.extend(files)

        # Deduplicate and limit
        return list(dict.fromkeys(keywords))[:20]

    def get_fix_context(
        self,
        error_message: str,
        include_project_structure: bool = True,
        include_file_contents: bool = True,
        max_files: int = 3,
    ) -> str:
        """Get comprehensive context for AI to fix the error.

        Args:
            error_message: The error message
            include_project_structure: Include project structure info
            include_file_contents: Include relevant file contents
            max_files: Maximum file contents to include

        Returns:
            Formatted context string for AI
        """
        analysis = self.analyze(error_message)
        parts = []

        # Error analysis
        parts.append(analysis.to_context_string())

        # Project structure
        if include_project_structure and self.scanner:
            parts.append("")
            parts.append(self.scanner.get_project_context(max_files=2))

        # Relevant file contents
        if include_file_contents and self.scanner and analysis.relevant_files:
            parts.append("")
            parts.append("## RELEVANT SOURCE FILES")

            for pf in analysis.relevant_files[:max_files]:
                content = self.scanner.get_file_content(pf.path)
                if content:
                    parts.append(f"\n### {pf.path}")
                    parts.append(f"```{pf.language.value}")
                    # Truncate long files
                    if len(content) > 3000:
                        content = content[:3000] + "\n... (truncated)"
                    parts.append(content)
                    parts.append("```")

        return "\n".join(parts)
