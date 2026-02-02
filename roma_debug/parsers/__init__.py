"""ROMA Debug Parsers - Multi-language source code parsing.

This package provides extensible parser support for extracting
semantic information from source files in multiple programming languages.
"""

from roma_debug.parsers.base import BaseParser
from roma_debug.parsers.registry import (
    get_parser,
    detect_language,
    register_parser,
    ParserRegistry,
)

__all__ = [
    "BaseParser",
    "get_parser",
    "detect_language",
    "register_parser",
    "ParserRegistry",
]
