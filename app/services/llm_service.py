"""
LLM service — abstraction over OpenAI-compatible APIs.

Provides:
  - chat_completion(system, user) → raw text
  - structured_completion(system, user, response_model) → parsed Pydantic model

Features:
  - Exponential backoff retry (configurable)
  - Rate-limit awareness (handles 429)
  - Timeout handling
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import LLMServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# ── Lazy client initialization ─────────────────────────────────────────────

_client = None


def _get_client():
    """Lazily initialize the OpenAI async client."""
    global _client
    if _client is None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise LLMServiceError(
                "openai package not installed. Run: pip install openai"
            )

        kwargs = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url

        _client = AsyncOpenAI(**kwargs)
    return _client


# ── Core completion functions ──────────────────────────────────────────────


async def chat_completion(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """
    Send a chat completion request and return the raw text response.

    Retries on transient failures with exponential backoff.
    """
    client = _get_client()
    _model = model or settings.openai_model

    for attempt in range(1, settings.llm_max_retries + 1):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                timeout=settings.llm_timeout_seconds,
            )
            content = response.choices[0].message.content
            if content is None:
                raise LLMServiceError("LLM returned empty content")
            return content.strip()

        except asyncio.TimeoutError:
            logger.warning(
                "LLM timeout on attempt %d/%d", attempt, settings.llm_max_retries
            )
            if attempt == settings.llm_max_retries:
                raise LLMServiceError(
                    f"LLM request timed out after {settings.llm_max_retries} attempts"
                )

        except Exception as exc:
            err_str = str(exc).lower()
            # Retry on rate limits and server errors
            if "429" in err_str or "rate" in err_str or "500" in err_str:
                wait = 2**attempt
                logger.warning(
                    "LLM transient error on attempt %d/%d, retrying in %ds: %s",
                    attempt, settings.llm_max_retries, wait, exc,
                )
                if attempt == settings.llm_max_retries:
                    raise LLMServiceError(f"LLM failed after {settings.llm_max_retries} retries: {exc}")
                await asyncio.sleep(wait)
            else:
                raise LLMServiceError(f"LLM request failed: {exc}") from exc

    raise LLMServiceError("LLM failed: exhausted retries")


async def structured_completion(
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    model: str | None = None,
    temperature: float = 0.4,
) -> T:
    """
    Send a chat completion and parse the response into a Pydantic model.

    The system prompt instructs the LLM to return valid JSON matching
    the model schema. The response is stripped of markdown fences and
    parsed.
    """
    schema_json = json.dumps(response_model.model_json_schema(), indent=2)
    full_system = (
        f"{system_prompt}\n\n"
        f"IMPORTANT: Respond ONLY with valid JSON matching this schema:\n"
        f"```json\n{schema_json}\n```\n"
        f"Do not include any text outside the JSON object."
    )

    raw = await chat_completion(
        system_prompt=full_system,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
        max_tokens=4096,
    )

    # Strip markdown code fences if present
    cleaned = _strip_json_fences(raw)

    try:
        return response_model.model_validate_json(cleaned)
    except Exception as exc:
        logger.error("Failed to parse LLM response into %s: %s", response_model.__name__, exc)
        logger.debug("Raw LLM response:\n%s", raw)
        raise LLMServiceError(
            f"Could not parse LLM output into {response_model.__name__}: {exc}"
        ) from exc


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` fences from LLM output."""
    # Try to extract JSON from code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()
