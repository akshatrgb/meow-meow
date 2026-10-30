"""OpenRouter chat-completions client.

Same endpoint, headers and payload shape as the original implementation, now
with timeouts, retries with backoff for transient failures, and error messages
that never contain credentials.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Protocol, Sequence

import requests

from src.config.settings import Settings

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """Base error for LLM failures. Messages are safe to log and show."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class LLMConnectionError(LLMError):
    """The network or the provider could not be reached (treat as offline)."""


class LLMAuthError(LLMError):
    """The API key was rejected."""


class ChatClient(Protocol):
    """What the conversation manager needs from an LLM client."""

    async def acomplete(self, messages: Sequence[dict[str, str]]) -> str: ...


class OpenRouterClient:
    """Thin, robust client for OpenRouter's chat completions API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        url: str = "https://openrouter.ai/api/v1/chat/completions",
        *,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        max_tokens: int = 200,
        temperature: float = 0.8,
        json_mode: bool = True,
        session: Any | None = None,
        sleep=time.sleep,
    ) -> None:
        if not api_key:
            raise LLMAuthError("OpenRouter API key is missing.")
        self._api_key = api_key
        self.model = model
        self._url = url
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._json_mode = json_mode
        self._session = session or requests.Session()
        self._sleep = sleep

    @classmethod
    def from_settings(cls, s: Settings) -> "OpenRouterClient":
        return cls(
            s.openrouter_api_key, s.openrouter_model, s.openrouter_url,
            timeout_s=s.llm_timeout_s, max_retries=s.llm_max_retries,
            max_tokens=s.llm_max_tokens, temperature=s.llm_temperature, json_mode=s.llm_json_mode,
        )

    def complete(self, messages: Sequence[dict[str, str]]) -> str:
        """Send ``messages`` and return the assistant text (blocking).

        Raises:
            LLMAuthError: key rejected (never retried).
            LLMConnectionError: network failure or provider unavailable after retries.
            LLMError: any other API error.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if self._json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        last: LLMError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._attempt(payload, headers)
            except LLMError as error:
                last = error
                if not error.retryable or attempt == self._max_retries:
                    break
                delay = min(8.0, 0.5 * 2**attempt) + random.uniform(0, 0.25)
                log.warning("LLM request failed (%s); retry %d/%d in %.1fs",
                            error, attempt + 1, self._max_retries, delay)
                self._sleep(delay)
        assert last is not None
        raise last

    async def acomplete(self, messages: Sequence[dict[str, str]]) -> str:
        """Async wrapper: runs the blocking request in a worker thread."""
        return await asyncio.to_thread(self.complete, messages)

    def _attempt(self, payload: dict[str, Any], headers: dict[str, str]) -> str:
        try:
            response = self._session.post(self._url, headers=headers, json=payload, timeout=self._timeout)
        except requests.Timeout as exc:
            raise LLMConnectionError("OpenRouter request timed out.", retryable=True) from exc
        except requests.RequestException as exc:
            # Only the exception class is reported: URLs/headers must not leak into logs.
            raise LLMConnectionError(f"Could not reach OpenRouter ({type(exc).__name__}).",
                                     retryable=True) from exc

        status = response.status_code
        if status in (401, 403):
            raise LLMAuthError("OpenRouter rejected the API key.", status=status)
        if status >= 400:
            raise LLMError(f"OpenRouter error {status}: {self._error_detail(response)}",
                           status=status, retryable=status in RETRYABLE_STATUS)
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            # OpenRouter can return HTTP 200 with an {"error": ...} body.
            detail = self._error_detail(response)
            raise LLMError(f"Unexpected OpenRouter response: {detail}", retryable=True) from exc
        if not isinstance(content, str):
            raise LLMError("OpenRouter returned no text content.", retryable=True)
        return content

    @staticmethod
    def _error_detail(response: Any) -> str:
        try:
            error = response.json().get("error")
            if isinstance(error, dict):
                error = error.get("message")
            if error:
                return str(error)[:200]
        except (ValueError, AttributeError):
            pass
        return "no details"
