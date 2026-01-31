"""Centralized configuration for ROMA Debug.

This module is the single source of truth for all configuration.
It loads the .env file once at import time and exposes validated settings.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def _find_project_root() -> Path:
    """Find project root by searching for .env file.

    Searches upward from this file's location until .env is found.
    Falls back to the parent of roma_debug package.

    Returns:
        Path to project root directory
    """
    current = Path(__file__).resolve().parent

    # Search upward for .env file (max 5 levels)
    for _ in range(5):
        if (current / ".env").exists():
            return current
        if current.parent == current:
            break
        current = current.parent

    # Fallback: assume project root is parent of roma_debug/
    return Path(__file__).resolve().parent.parent


def _load_config() -> str:
    """Load configuration from .env file.

    Returns:
        The Gemini API key

    Raises:
        RuntimeError: If GEMINI_API_KEY is not set
    """
    project_root = _find_project_root()
    env_path = project_root / ".env"

    # Load .env file
    if env_path.exists():
        load_dotenv(env_path, override=True)
    else:
        # Try loading from environment anyway
        load_dotenv()

    # Get API key from environment
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if not api_key:
        raise RuntimeError(
            f"GEMINI_API_KEY not found!\n"
            f"Searched .env at: {env_path}\n"
            f"Please set GEMINI_API_KEY in your .env file or environment."
        )

    return api_key


# Load configuration at import time
# This ensures consistent behavior across CLI and server
GEMINI_API_KEY: str = _load_config()


def get_api_key_status() -> str:
    """Get human-readable API key status for logging.

    Returns:
        'OK' if key is loaded, 'MISSING' otherwise
    """
    return "OK" if GEMINI_API_KEY else "MISSING"
