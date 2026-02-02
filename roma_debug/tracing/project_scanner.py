"""Project scanner for deep project awareness.

Scans project structure to understand:
- Project type (Flask, FastAPI, Express, etc.)
- Entry points (main.py, app.py, server.py)
- File structure and relationships
- Configuration files
"""

import os
import re
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set
from pathlib import Path

from roma_debug.core.models import Language


@dataclass
class ProjectFile:
    """Represents a file in the project."""
    path: str
    language: Language
    is_entry_point: bool = False
    is_config: bool = False
    size: int = 0

    @property
    def filename(self) -> str:
        return os.path.basename(self.path)

    @property
    def relative_path(self) -> str:
        return self.path


@dataclass
class ProjectInfo:
    """Information about a scanned project."""
    root: str
    project_type: str  # 'flask', 'fastapi', 'express', 'go', 'rust', 'unknown'
    primary_language: Language
    entry_points: List[ProjectFile] = field(default_factory=list)
    source_files: List[ProjectFile] = field(default_factory=list)
    config_files: List[ProjectFile] = field(default_factory=list)
    frameworks_detected: List[str] = field(default_factory=list)

    def get_files_by_language(self, language: Language) -> List[ProjectFile]:
        """Get all files of a specific language."""
        return [f for f in self.source_files if f.language == language]

    def find_file(self, filename: str) -> Optional[ProjectFile]:
        """Find a file by name (partial match)."""
        filename_lower = filename.lower()
        for f in self.source_files:
            if filename_lower in f.path.lower():
                return f
        return None

    def find_files_by_pattern(self, pattern: str) -> List[ProjectFile]:
        """Find files matching a regex pattern."""
        regex = re.compile(pattern, re.IGNORECASE)
        return [f for f in self.source_files if regex.search(f.path)]

    def to_summary(self) -> str:
        """Generate a human-readable summary."""
        lines = [
            f"Project Type: {self.project_type}",
            f"Primary Language: {self.primary_language.value}",
            f"Frameworks: {', '.join(self.frameworks_detected) or 'None detected'}",
            f"Entry Points: {len(self.entry_points)}",
            f"Source Files: {len(self.source_files)}",
        ]

        if self.entry_points:
            lines.append("\nEntry Points:")
            for ep in self.entry_points[:5]:
                lines.append(f"  - {ep.path}")

        return "\n".join(lines)


# Common entry point file patterns
ENTRY_POINT_PATTERNS = {
    Language.PYTHON: [
        r'^main\.py$',
        r'^app\.py$',
        r'^server\.py$',
        r'^run\.py$',
        r'^wsgi\.py$',
        r'^asgi\.py$',
        r'^manage\.py$',
        r'^__main__\.py$',
        r'^index\.py$',
    ],
    Language.JAVASCRIPT: [
        r'^index\.js$',
        r'^app\.js$',
        r'^server\.js$',
        r'^main\.js$',
        r'^src/index\.js$',
    ],
    Language.TYPESCRIPT: [
        r'^index\.ts$',
        r'^app\.ts$',
        r'^server\.ts$',
        r'^main\.ts$',
        r'^src/index\.ts$',
    ],
    Language.GO: [
        r'^main\.go$',
        r'^cmd/.*\.go$',
    ],
    Language.RUST: [
        r'^main\.rs$',
        r'^lib\.rs$',
        r'^src/main\.rs$',
        r'^src/lib\.rs$',
    ],
    Language.JAVA: [
        r'^Main\.java$',
        r'^App\.java$',
        r'^Application\.java$',
    ],
}

# Framework detection patterns (file content)
FRAMEWORK_PATTERNS = {
    'flask': [
        (r'from\s+flask\s+import', Language.PYTHON),
        (r'import\s+flask', Language.PYTHON),
        (r'Flask\s*\(', Language.PYTHON),
    ],
    'fastapi': [
        (r'from\s+fastapi\s+import', Language.PYTHON),
        (r'FastAPI\s*\(', Language.PYTHON),
    ],
    'django': [
        (r'from\s+django', Language.PYTHON),
        (r'import\s+django', Language.PYTHON),
        (r'DJANGO_SETTINGS_MODULE', Language.PYTHON),
    ],
    'express': [
        (r'require\s*\(\s*[\'"]express[\'"]\s*\)', Language.JAVASCRIPT),
        (r'from\s+[\'"]express[\'"]', Language.JAVASCRIPT),
        (r'express\s*\(\s*\)', Language.JAVASCRIPT),
    ],
    'react': [
        (r'from\s+[\'"]react[\'"]', Language.JAVASCRIPT),
        (r'import\s+React', Language.JAVASCRIPT),
        (r'React\.createElement', Language.JAVASCRIPT),
    ],
    'vue': [
        (r'from\s+[\'"]vue[\'"]', Language.JAVASCRIPT),
        (r'createApp', Language.JAVASCRIPT),
        (r'\.vue$', None),  # File extension check
    ],
    'gin': [
        (r'github\.com/gin-gonic/gin', Language.GO),
    ],
    'actix': [
        (r'actix_web', Language.RUST),
    ],
    'spring': [
        (r'org\.springframework', Language.JAVA),
        (r'@SpringBootApplication', Language.JAVA),
    ],
}

# Config file patterns
CONFIG_FILES = [
    'package.json',
    'requirements.txt',
    'setup.py',
    'pyproject.toml',
    'Pipfile',
    'go.mod',
    'Cargo.toml',
    'pom.xml',
    'build.gradle',
    '.env',
    'config.py',
    'config.js',
    'config.json',
    'settings.py',
    'docker-compose.yml',
    'Dockerfile',
]

# Directories to skip
SKIP_DIRS = {
    'node_modules',
    '__pycache__',
    '.git',
    '.svn',
    '.hg',
    'venv',
    'env',
    '.venv',
    '.env',
    'dist',
    'build',
    'target',
    '.idea',
    '.vscode',
    'coverage',
    '.pytest_cache',
    '.mypy_cache',
    'eggs',
    '*.egg-info',
}


class ProjectScanner:
    """Scans and analyzes project structure."""

    def __init__(self, project_root: str, max_files: int = 1000):
        """Initialize the scanner.

        Args:
            project_root: Root directory of the project
            max_files: Maximum number of files to scan
        """
        self.project_root = os.path.abspath(project_root)
        self.max_files = max_files
        self._project_info: Optional[ProjectInfo] = None

    def scan(self) -> ProjectInfo:
        """Scan the project and return project info.

        Returns:
            ProjectInfo with project structure analysis
        """
        if self._project_info is not None:
            return self._project_info

        source_files: List[ProjectFile] = []
        config_files: List[ProjectFile] = []
        entry_points: List[ProjectFile] = []
        frameworks_detected: Set[str] = set()
        language_counts: Dict[Language, int] = {}

        # Scan files
        file_count = 0
        for root, dirs, files in os.walk(self.project_root):
            # Skip unwanted directories
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]

            for filename in files:
                if file_count >= self.max_files:
                    break

                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, self.project_root)

                # Check if config file
                if filename in CONFIG_FILES:
                    try:
                        size = os.path.getsize(filepath)
                        config_files.append(ProjectFile(
                            path=rel_path,
                            language=Language.UNKNOWN,
                            is_config=True,
                            size=size,
                        ))
                    except OSError:
                        pass
                    continue

                # Detect language
                language = self._detect_language(filename)
                if language == Language.UNKNOWN:
                    continue

                try:
                    size = os.path.getsize(filepath)
                except OSError:
                    size = 0

                # Check if entry point
                is_entry = self._is_entry_point(rel_path, language)

                pf = ProjectFile(
                    path=rel_path,
                    language=language,
                    is_entry_point=is_entry,
                    size=size,
                )

                source_files.append(pf)
                if is_entry:
                    entry_points.append(pf)

                # Count languages
                language_counts[language] = language_counts.get(language, 0) + 1
                file_count += 1

            if file_count >= self.max_files:
                break

        # Detect frameworks from entry points and key files
        frameworks_detected = self._detect_frameworks(entry_points + source_files[:50])

        # Determine primary language
        primary_language = max(language_counts, key=language_counts.get) if language_counts else Language.UNKNOWN

        # Determine project type
        project_type = self._determine_project_type(frameworks_detected, primary_language)

        self._project_info = ProjectInfo(
            root=self.project_root,
            project_type=project_type,
            primary_language=primary_language,
            entry_points=entry_points,
            source_files=source_files,
            config_files=config_files,
            frameworks_detected=list(frameworks_detected),
        )

        return self._project_info

    def _detect_language(self, filename: str) -> Language:
        """Detect language from filename."""
        ext = os.path.splitext(filename)[1].lower()
        return Language.from_extension(ext)

    def _is_entry_point(self, rel_path: str, language: Language) -> bool:
        """Check if file is likely an entry point."""
        patterns = ENTRY_POINT_PATTERNS.get(language, [])
        filename = os.path.basename(rel_path)

        for pattern in patterns:
            if re.match(pattern, filename, re.IGNORECASE):
                return True
            if re.match(pattern, rel_path, re.IGNORECASE):
                return True

        return False

    def _detect_frameworks(self, files: List[ProjectFile]) -> Set[str]:
        """Detect frameworks from file contents."""
        frameworks: Set[str] = set()

        for pf in files:
            filepath = os.path.join(self.project_root, pf.path)

            try:
                # Only read first 10KB
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(10240)
            except (IOError, OSError):
                continue

            for framework, patterns in FRAMEWORK_PATTERNS.items():
                for pattern, lang in patterns:
                    if lang is None:
                        # File extension check
                        if re.search(pattern, pf.path):
                            frameworks.add(framework)
                    elif lang == pf.language:
                        if re.search(pattern, content):
                            frameworks.add(framework)

        return frameworks

    def _determine_project_type(self, frameworks: Set[str], primary_lang: Language) -> str:
        """Determine project type from frameworks and language."""
        # Priority order for project type
        if 'flask' in frameworks:
            return 'flask'
        if 'fastapi' in frameworks:
            return 'fastapi'
        if 'django' in frameworks:
            return 'django'
        if 'express' in frameworks:
            return 'express'
        if 'gin' in frameworks:
            return 'gin'
        if 'actix' in frameworks:
            return 'actix'
        if 'spring' in frameworks:
            return 'spring'
        if 'react' in frameworks:
            return 'react'
        if 'vue' in frameworks:
            return 'vue'

        # Fall back to language
        lang_types = {
            Language.PYTHON: 'python',
            Language.JAVASCRIPT: 'javascript',
            Language.TYPESCRIPT: 'typescript',
            Language.GO: 'go',
            Language.RUST: 'rust',
            Language.JAVA: 'java',
        }
        return lang_types.get(primary_lang, 'unknown')

    def find_relevant_files(self, error_message: str, limit: int = 10) -> List[ProjectFile]:
        """Find files relevant to an error message.

        Uses keyword extraction and pattern matching to find files
        that might be related to the error.

        Args:
            error_message: The error message to analyze
            limit: Maximum number of files to return

        Returns:
            List of potentially relevant ProjectFiles
        """
        if self._project_info is None:
            self.scan()

        # Extract potential filenames and keywords from error
        keywords = self._extract_keywords(error_message)

        scored_files: List[tuple] = []

        for pf in self._project_info.source_files:
            score = self._score_relevance(pf, keywords, error_message)
            if score > 0:
                scored_files.append((score, pf))

        # Sort by score descending
        scored_files.sort(key=lambda x: x[0], reverse=True)

        return [pf for _, pf in scored_files[:limit]]

    def _extract_keywords(self, error_message: str) -> Set[str]:
        """Extract relevant keywords from error message."""
        keywords = set()

        # Common error-related words to ignore
        ignore_words = {
            'error', 'exception', 'failed', 'cannot', 'could', 'not',
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'at', 'in', 'on', 'to', 'for', 'of', 'with', 'by', 'from',
            'get', 'post', 'put', 'delete', 'http', 'https',
        }

        # Extract potential file names
        file_patterns = [
            r'[\w\-]+\.(?:py|js|ts|go|rs|java|jsx|tsx)',
            r'/[\w\-/]+\.(?:py|js|ts|go|rs|java|jsx|tsx)',
        ]
        for pattern in file_patterns:
            matches = re.findall(pattern, error_message, re.IGNORECASE)
            keywords.update(m.lower() for m in matches)

        # Extract route patterns
        route_patterns = re.findall(r'/[\w\-/]+', error_message)
        for route in route_patterns:
            parts = route.strip('/').split('/')
            keywords.update(p.lower() for p in parts if len(p) > 2)

        # Extract identifiers (CamelCase, snake_case)
        identifiers = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', error_message)  # CamelCase
        keywords.update(i.lower() for i in identifiers)

        identifiers = re.findall(r'\b[a-z]+(?:_[a-z]+)+\b', error_message)  # snake_case
        keywords.update(identifiers)

        # Extract quoted strings
        quoted = re.findall(r'[\'"]([^\'"]+)[\'"]', error_message)
        for q in quoted:
            if len(q) > 2 and not q.startswith('http'):
                keywords.add(q.lower())

        # Remove ignored words
        keywords -= ignore_words

        return keywords

    def _score_relevance(self, pf: ProjectFile, keywords: Set[str], error_message: str) -> float:
        """Score how relevant a file is to the error."""
        score = 0.0
        path_lower = pf.path.lower()
        filename_lower = pf.filename.lower()

        # Entry points get a boost
        if pf.is_entry_point:
            score += 2.0

        # Direct filename match
        for kw in keywords:
            if kw in filename_lower:
                score += 3.0
            elif kw in path_lower:
                score += 1.5

        # Route-related files for HTTP errors
        if 'cannot get' in error_message.lower() or '404' in error_message:
            if any(x in filename_lower for x in ['route', 'app', 'server', 'index', 'view', 'controller']):
                score += 2.0

        # Static file serving errors
        if 'static' in error_message.lower() or 'index.html' in error_message.lower():
            if any(x in path_lower for x in ['static', 'public', 'build', 'dist', 'frontend']):
                score += 1.5
            if any(x in filename_lower for x in ['app', 'server', 'main', 'index']):
                score += 2.0

        # API errors
        if 'api' in error_message.lower():
            if 'api' in path_lower:
                score += 2.0

        return score

    def get_file_content(self, rel_path: str) -> Optional[str]:
        """Read file content by relative path.

        Args:
            rel_path: Relative path from project root

        Returns:
            File content or None if not readable
        """
        filepath = os.path.join(self.project_root, rel_path)
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except (IOError, OSError):
            return None

    def get_project_context(self, max_files: int = 5) -> str:
        """Generate project context string for AI.

        Args:
            max_files: Maximum number of entry point contents to include

        Returns:
            Formatted project context string
        """
        if self._project_info is None:
            self.scan()

        info = self._project_info
        lines = [
            "## PROJECT STRUCTURE",
            f"Type: {info.project_type}",
            f"Language: {info.primary_language.value}",
            f"Frameworks: {', '.join(info.frameworks_detected) or 'None detected'}",
            "",
            "### Entry Points:",
        ]

        for ep in info.entry_points[:max_files]:
            lines.append(f"- {ep.path}")

        lines.append("")
        lines.append("### Key Files:")

        # Include content of entry points
        for ep in info.entry_points[:max_files]:
            content = self.get_file_content(ep.path)
            if content:
                lines.append(f"\n#### {ep.path}")
                lines.append("```" + ep.language.value)
                # Limit content length
                if len(content) > 2000:
                    content = content[:2000] + "\n... (truncated)"
                lines.append(content)
                lines.append("```")

        return "\n".join(lines)

    def generate_file_tree(
        self,
        max_depth: int = 4,
        max_files_per_dir: int = 20,
        show_hidden: bool = False,
    ) -> str:
        """Generate a visual file tree representation of the project.

        Creates a tree-style output similar to the Unix 'tree' command,
        respecting .gitignore patterns and skipping common non-source directories.

        Args:
            max_depth: Maximum directory depth to traverse (default: 4)
            max_files_per_dir: Max files to show per directory before truncating (default: 20)
            show_hidden: Whether to show hidden files/dirs starting with '.' (default: False)

        Returns:
            String representation of the project file tree
        """
        # Load .gitignore patterns if present
        gitignore_patterns = self._load_gitignore_patterns()

        tree_lines = [os.path.basename(self.project_root) + "/"]
        self._build_tree(
            self.project_root,
            "",
            tree_lines,
            depth=0,
            max_depth=max_depth,
            max_files_per_dir=max_files_per_dir,
            show_hidden=show_hidden,
            gitignore_patterns=gitignore_patterns,
        )

        return "\n".join(tree_lines)

    def _load_gitignore_patterns(self) -> Set[str]:
        """Load patterns from .gitignore file.

        Returns:
            Set of gitignore patterns (simple glob matching)
        """
        patterns = set()
        gitignore_path = os.path.join(self.project_root, ".gitignore")

        if os.path.isfile(gitignore_path):
            try:
                with open(gitignore_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        # Skip comments and empty lines
                        if line and not line.startswith('#'):
                            # Normalize pattern (remove trailing slashes for dirs)
                            pattern = line.rstrip('/')
                            patterns.add(pattern)
            except (IOError, OSError):
                pass

        return patterns

    def _should_skip_entry(
        self,
        name: str,
        rel_path: str,
        is_dir: bool,
        show_hidden: bool,
        gitignore_patterns: Set[str],
    ) -> bool:
        """Check if a file/directory should be skipped.

        Args:
            name: File or directory name
            rel_path: Relative path from project root
            is_dir: Whether this is a directory
            show_hidden: Whether to show hidden files
            gitignore_patterns: Patterns from .gitignore

        Returns:
            True if the entry should be skipped
        """
        # Skip hidden files/dirs unless explicitly requested
        if not show_hidden and name.startswith('.'):
            return True

        # Always skip directories in SKIP_DIRS
        if is_dir and name in SKIP_DIRS:
            return True

        # Check against gitignore patterns
        for pattern in gitignore_patterns:
            # Handle wildcard patterns
            if pattern.startswith('*'):
                if name.endswith(pattern[1:]):
                    return True
            elif pattern.endswith('*'):
                if name.startswith(pattern[:-1]):
                    return True
            # Direct name match
            elif name == pattern or rel_path == pattern:
                return True
            # Check if pattern matches any part of path
            elif '/' not in pattern and pattern in name:
                # Only match if it's a suffix pattern like *.pyc
                if pattern.startswith('*.') and name.endswith(pattern[1:]):
                    return True

        return False

    def _build_tree(
        self,
        current_path: str,
        prefix: str,
        tree_lines: List[str],
        depth: int,
        max_depth: int,
        max_files_per_dir: int,
        show_hidden: bool,
        gitignore_patterns: Set[str],
    ) -> None:
        """Recursively build the file tree representation.

        Args:
            current_path: Current directory path
            prefix: Line prefix for tree formatting
            tree_lines: List to append tree lines to
            depth: Current depth level
            max_depth: Maximum depth to traverse
            max_files_per_dir: Max items before truncating
            show_hidden: Whether to show hidden files
            gitignore_patterns: Patterns from .gitignore
        """
        if depth >= max_depth:
            return

        try:
            entries = sorted(os.listdir(current_path))
        except (PermissionError, OSError):
            return

        # Separate and filter directories and files
        dirs = []
        files = []

        for entry in entries:
            entry_path = os.path.join(current_path, entry)
            rel_path = os.path.relpath(entry_path, self.project_root)
            is_dir = os.path.isdir(entry_path)

            if self._should_skip_entry(entry, rel_path, is_dir, show_hidden, gitignore_patterns):
                continue

            if is_dir:
                dirs.append(entry)
            else:
                files.append(entry)

        # Sort: directories first, then files
        all_entries = dirs + files
        total_entries = len(all_entries)

        # Truncate if too many entries
        if total_entries > max_files_per_dir:
            all_entries = all_entries[:max_files_per_dir]
            truncated = total_entries - max_files_per_dir
        else:
            truncated = 0

        for i, entry in enumerate(all_entries):
            entry_path = os.path.join(current_path, entry)
            is_last = (i == len(all_entries) - 1) and (truncated == 0)

            # Determine connector
            if is_last:
                connector = "└── "
                new_prefix = prefix + "    "
            else:
                connector = "├── "
                new_prefix = prefix + "│   "

            is_dir = os.path.isdir(entry_path)

            if is_dir:
                tree_lines.append(f"{prefix}{connector}{entry}/")
                self._build_tree(
                    entry_path,
                    new_prefix,
                    tree_lines,
                    depth + 1,
                    max_depth,
                    max_files_per_dir,
                    show_hidden,
                    gitignore_patterns,
                )
            else:
                tree_lines.append(f"{prefix}{connector}{entry}")

        # Show truncation indicator
        if truncated > 0:
            tree_lines.append(f"{prefix}└── ... ({truncated} more items)")
