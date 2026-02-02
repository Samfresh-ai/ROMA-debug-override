"""Parser registry for language detection and parser dispatch.

Provides centralized parser management and language detection from file extensions.
"""

import os
from typing import Dict, Optional, Type, Callable

from roma_debug.core.models import Language
from roma_debug.parsers.base import BaseParser


class ParserRegistry:
    """Registry for language parsers.

    Manages parser registration and provides parser lookup by language
    or file extension.
    """

    def __init__(self):
        """Initialize the registry."""
        self._parsers: Dict[Language, Type[BaseParser]] = {}
        self._parser_factories: Dict[Language, Callable[[], BaseParser]] = {}
        self._instances: Dict[Language, BaseParser] = {}

    def register(
        self,
        language: Language,
        parser_class: Type[BaseParser],
        factory: Optional[Callable[[], BaseParser]] = None,
    ):
        """Register a parser for a language.

        Args:
            language: The language this parser handles
            parser_class: The parser class
            factory: Optional factory function to create parser instances
        """
        self._parsers[language] = parser_class
        if factory:
            self._parser_factories[language] = factory

    def get_parser(
        self,
        language: Language,
        create_new: bool = False,
    ) -> Optional[BaseParser]:
        """Get a parser for the given language.

        Args:
            language: The language to get a parser for
            create_new: If True, create a new instance instead of reusing

        Returns:
            Parser instance or None if no parser registered
        """
        if language not in self._parsers:
            return None

        if create_new or language not in self._instances:
            if language in self._parser_factories:
                parser = self._parser_factories[language]()
            else:
                parser = self._parsers[language]()
            if not create_new:
                self._instances[language] = parser
            return parser

        return self._instances[language]

    def get_parser_for_file(
        self,
        filepath: str,
        create_new: bool = False,
    ) -> Optional[BaseParser]:
        """Get a parser based on file extension.

        Args:
            filepath: Path to the file
            create_new: If True, create a new instance

        Returns:
            Parser instance or None if language not supported
        """
        language = detect_language(filepath)
        return self.get_parser(language, create_new)

    def supports_language(self, language: Language) -> bool:
        """Check if a language is supported.

        Args:
            language: The language to check

        Returns:
            True if a parser is registered for this language
        """
        return language in self._parsers

    def supports_file(self, filepath: str) -> bool:
        """Check if a file type is supported.

        Args:
            filepath: Path to the file

        Returns:
            True if the file's language has a registered parser
        """
        language = detect_language(filepath)
        return self.supports_language(language)

    @property
    def supported_languages(self) -> list:
        """Get list of supported languages."""
        return list(self._parsers.keys())

    def clear_instances(self):
        """Clear cached parser instances."""
        self._instances.clear()


# Global registry instance
_registry = ParserRegistry()


def detect_language(filepath: str) -> Language:
    """Detect programming language from file path.

    Args:
        filepath: Path to the source file

    Returns:
        Language enum value
    """
    _, ext = os.path.splitext(filepath)
    return Language.from_extension(ext)


def get_parser(
    filepath_or_language,
    create_new: bool = False,
) -> Optional[BaseParser]:
    """Get a parser for a file or language.

    Args:
        filepath_or_language: File path string or Language enum
        create_new: If True, create a new parser instance

    Returns:
        Parser instance or None if not supported
    """
    if isinstance(filepath_or_language, Language):
        return _registry.get_parser(filepath_or_language, create_new)
    return _registry.get_parser_for_file(filepath_or_language, create_new)


def register_parser(
    language: Language,
    parser_class: Type[BaseParser],
    factory: Optional[Callable[[], BaseParser]] = None,
):
    """Register a parser in the global registry.

    Args:
        language: The language this parser handles
        parser_class: The parser class
        factory: Optional factory function
    """
    _registry.register(language, parser_class, factory)


def get_registry() -> ParserRegistry:
    """Get the global parser registry.

    Returns:
        The global ParserRegistry instance
    """
    return _registry


# Register built-in parsers
def _register_builtin_parsers():
    """Register the built-in parsers."""
    from roma_debug.parsers.python_ast_parser import PythonAstParser

    register_parser(Language.PYTHON, PythonAstParser)

    # Import tree-sitter parser module to trigger its auto-registration
    # This allows graceful degradation if tree-sitter is not installed
    try:
        import roma_debug.parsers.treesitter_parser  # noqa: F401
    except ImportError:
        pass  # tree-sitter not available, only Python will be supported


# Auto-register built-in parsers on module import
_register_builtin_parsers()
