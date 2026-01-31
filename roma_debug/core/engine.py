"""Gemini Fixer Logic for ROMA Debug."""

import time

from google import genai
from google.genai import types

from roma_debug.config import GEMINI_API_KEY
from roma_debug.prompts import SYSTEM_PROMPT


# Model priority: try Lite first (higher quota), then Flash
PRIMARY_MODEL = "gemini-2.5-flash-lite"
FALLBACK_MODEL = "gemini-2.5-flash"


def _get_client() -> genai.Client:
    """Get configured Gemini client.

    Returns:
        Configured genai.Client
    """
    return genai.Client(api_key=GEMINI_API_KEY)


def analyze_error(log: str, context: str, max_retries: int = 3) -> str:
    """Analyze an error log and return a code fix using Gemini.

    Args:
        log: The error log or traceback
        context: Source code context around the error
        max_retries: Number of retries for rate limit errors

    Returns:
        The raw code fix from Gemini

    Raises:
        Exception: If Gemini API call fails after retries
    """
    client = _get_client()

    user_prompt = _build_prompt(log, context)
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

    generation_config = types.GenerateContentConfig(
        temperature=0,
    )

    # Try primary model first, fallback if quota exceeded
    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]

    for model_name in models_to_try:
        last_error = None

        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=full_prompt,
                    config=generation_config,
                )
                return response.text

            except Exception as e:
                error_str = str(e).lower()
                last_error = e

                # Check for quota/rate limit errors
                is_quota_error = any(x in error_str for x in [
                    "429", "quota", "rate limit", "resource exhausted"
                ])

                if is_quota_error:
                    # If quota exceeded, try fallback model
                    if model_name == PRIMARY_MODEL:
                        print(f"Quota exceeded for {model_name}, trying {FALLBACK_MODEL}...")
                        break  # Break retry loop, try next model

                    # For fallback model, do exponential backoff
                    wait_time = (2 ** attempt) * 5  # 5s, 10s, 20s
                    if attempt < max_retries - 1:
                        print(f"Rate limited, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue

                # Non-quota errors: raise immediately
                raise

        # If we completed retry loop without success and it's primary model,
        # continue to fallback model
        if model_name == PRIMARY_MODEL and last_error:
            continue

    # If we get here, all models failed
    raise last_error


def _build_prompt(log: str, context: str) -> str:
    """Build the user prompt from log and context."""
    parts = ["## ERROR LOG", log]

    if context:
        parts.extend(["", "## SOURCE CONTEXT", context])

    return "\n".join(parts)
