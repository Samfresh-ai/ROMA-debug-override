"""Centralized configuration for ROMA Debug.

This module is the single source of truth for all configuration.
It loads the .env file once at import time and exposes settings lazily.
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


_CACHED_API_KEY: str | None = None
_CACHED_API_KEYS: list[str] | None = None


def _load_config() -> str | None:
    """Load configuration from .env file (lazy).

    Returns:
        The Gemini API key, or None if not set
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
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _load_keys() -> list[str]:
    # Ensure .env is loaded before reading env vars
    _load_config()
    keys_env = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GOOGLE_API_KEYS") or ""
    keys = [k.strip() for k in keys_env.split(",") if k.strip()]
    if keys:
        return keys

    # Fall back to GEMINI_API_KEY, GEMINI_API_KEY2, GEMINI_API_KEY3... if present
    indexed_keys = []
    base = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if base:
        indexed_keys.append(base)

    for i in range(2, 6):
        k = os.environ.get(f"GEMINI_API_KEY{i}") or os.environ.get(f"GOOGLE_API_KEY{i}")
        if k:
            indexed_keys.append(k)

    if indexed_keys:
        return indexed_keys

    key = _load_config()
    return [key] if key else []


def get_api_key() -> str | None:
    """Get the Gemini API key, loading once and caching."""
    global _CACHED_API_KEY
    if _CACHED_API_KEY is None:
        _CACHED_API_KEY = _load_config()
    return _CACHED_API_KEY


def get_api_keys() -> list[str]:
    """Get all available Gemini API keys (rotation pool)."""
    global _CACHED_API_KEYS
    if _CACHED_API_KEYS is None:
        _CACHED_API_KEYS = _load_keys()
    return _CACHED_API_KEYS


def get_api_key_status() -> str:
    """Get human-readable API key status for logging.

    Returns:
        'OK' if key is loaded, 'MISSING' otherwise
    """
    return "OK" if get_api_keys() else "MISSING"
