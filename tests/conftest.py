"""Shared test helpers."""

from __future__ import annotations

import json

import requests


class FakeResponse:
    def __init__(self, status: int = 200, json_data=None, content: bytes = b"", text: str = "") -> None:
        self.status_code = status
        self._json = json_data
        self.content = content
        self.text = text or (json.dumps(json_data) if json_data is not None else "")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    """Returns queued responses (or raises queued exceptions) and records requests."""

    def __init__(self, *results) -> None:
        self.results = list(results)
        self.requests: list[dict] = []

    def _next(self, **kwargs):
        self.requests.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, **kwargs):
        return self._next(method="POST", url=url, **kwargs)

    def get(self, url, **kwargs):
        return self._next(method="GET", url=url, **kwargs)


def chat_ok(text: str) -> FakeResponse:
    return FakeResponse(200, {"choices": [{"message": {"content": text}}]})
