"""Genblaze RetryPolicy-backed transient retries for Gemini calls.

Retries the *individual* failed call (chat / generate_content / image generate)
in place — never restarts a Genblaze pipeline from the top.

Note: ``genblaze_google.chat(retry_on_rate_limit=True)`` only retries RATE_LIMIT
(429). This helper also retries SERVER_ERROR (503 UNAVAILABLE / high demand),
TIMEOUT, etc., using Genblaze's ``RetryPolicy.should_retry`` / ``compute_delay``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from genblaze_core.exceptions import ProviderError
from genblaze_core.models.enums import ProviderErrorCode
from genblaze_core.providers import RetryPolicy
from genblaze_google import chat as _genblaze_chat
from genblaze_google._errors import map_google_error

log = logging.getLogger("founderblaze.gemini_retry")

_T = TypeVar("_T")

# Flat ~30s between attempts (+ full jitter); honor Retry-After when present.
DEFAULT_GEMINI_RETRY_POLICY = RetryPolicy(
    max_attempts=6,
    initial_backoff_sec=30.0,
    max_backoff_sec=30.0,
    backoff_multiplier=1.0,
    jitter="full",
    respect_retry_after=True,
)


def gemini_image_retry_policy() -> RetryPolicy:
    """RetryPolicy for GeminiImageProvider construction."""
    return DEFAULT_GEMINI_RETRY_POLICY


def call_with_transient_retry(
    fn: Callable[[], _T],
    *,
    policy: RetryPolicy | None = None,
) -> _T:
    """Run ``fn()``, retrying transient ProviderErrors per Genblaze RetryPolicy.

    Covers RATE_LIMIT, SERVER_ERROR (503), TIMEOUT by default — not only 429.
    """
    policy = policy or DEFAULT_GEMINI_RETRY_POLICY
    attempt = 1
    while True:
        try:
            return fn()
        except ProviderError as exc:
            if not policy.should_retry(exc.error_code, attempt):
                exc.attempts = attempt
                raise
            delay = policy.compute_delay(attempt, retry_after=exc.retry_after)
            log.warning(
                "gemini transient retry %s/%s code=%s in %.1fs: %s",
                attempt,
                policy.max_attempts,
                exc.error_code,
                delay,
                exc,
            )
            time.sleep(delay)
            attempt += 1
        except Exception as exc:  # noqa: BLE001
            code = map_google_error(exc)
            wrapped = ProviderError(str(exc), error_code=code)
            if not policy.should_retry(code, attempt):
                wrapped.attempts = attempt
                raise wrapped from exc
            delay = policy.compute_delay(attempt, retry_after=None)
            log.warning(
                "gemini transient retry %s/%s code=%s in %.1fs: %s",
                attempt,
                policy.max_attempts,
                code,
                delay,
                exc,
            )
            time.sleep(delay)
            attempt += 1


def chat_with_retry(
    model: str,
    messages: list[Any] | None = None,
    *,
    prompt: str | None = None,
    system: str | None = None,
    tools: list[Any] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    api_key: str | None = None,
    project: str | None = None,
    location: str = "us-central1",
    client: Any = None,
    policy: RetryPolicy | None = None,
    **kwargs: Any,
) -> Any:
    """``genblaze_google.chat`` with FounderBlaze 503-capable RetryPolicy."""

    def _once() -> Any:
        return _genblaze_chat(
            model,
            messages,
            prompt=prompt,
            system=system,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            project=project,
            location=location,
            client=client,
            # FB owns transient retries (incl. SERVER_ERROR); avoid 429-only path.
            retry_on_rate_limit=False,
            **kwargs,
        )

    return call_with_transient_retry(_once, policy=policy)


def generate_content_with_retry(
    fn: Callable[[], _T],
    *,
    policy: RetryPolicy | None = None,
) -> _T:
    """Wrap a zero-arg ``client.models.generate_content(...)`` closure."""
    return call_with_transient_retry(fn, policy=policy)


__all__ = [
    "DEFAULT_GEMINI_RETRY_POLICY",
    "call_with_transient_retry",
    "chat_with_retry",
    "generate_content_with_retry",
    "gemini_image_retry_policy",
]
