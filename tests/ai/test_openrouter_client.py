import pytest
import requests

from src.ai.openrouter_client import LLMAuthError, LLMConnectionError, LLMError, OpenRouterClient
from tests.conftest import FakeResponse, FakeSession, chat_ok

SECRET = "sk-or-SUPERSECRETKEY123456"


def client(session, retries=2, **kw):
    return OpenRouterClient(SECRET, "test/model", session=session, max_retries=retries,
                            sleep=lambda s: None, **kw)


def test_success_sends_expected_payload_and_auth_header():
    session = FakeSession(chat_ok("hi"))
    assert client(session).complete([{"role": "user", "content": "yo"}]) == "hi"
    sent = session.requests[0]
    assert sent["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert sent["json"]["model"] == "test/model"
    assert sent["json"]["messages"] == [{"role": "user", "content": "yo"}]
    assert sent["json"]["response_format"] == {"type": "json_object"}
    assert sent["timeout"] == 30.0


def test_json_mode_can_be_disabled():
    session = FakeSession(chat_ok("hi"))
    client(session, json_mode=False).complete([])
    assert "response_format" not in session.requests[0]["json"]


def test_retries_transient_status_then_succeeds():
    session = FakeSession(FakeResponse(429, {"error": {"message": "slow down"}}),
                          FakeResponse(503), chat_ok("ok"))
    assert client(session).complete([]) == "ok"
    assert len(session.requests) == 3


def test_retries_timeouts_then_raises_connection_error():
    session = FakeSession(requests.Timeout(), requests.Timeout(), requests.Timeout())
    with pytest.raises(LLMConnectionError):
        client(session).complete([])
    assert len(session.requests) == 3


def test_auth_error_is_not_retried():
    session = FakeSession(FakeResponse(401, {"error": {"message": "bad key"}}))
    with pytest.raises(LLMAuthError):
        client(session).complete([])
    assert len(session.requests) == 1


def test_client_error_is_not_retried_and_reports_detail():
    session = FakeSession(FakeResponse(400, {"error": {"message": "model not found"}}))
    with pytest.raises(LLMError, match="model not found"):
        client(session).complete([])
    assert len(session.requests) == 1


def test_http_200_with_error_body_is_retried():
    session = FakeSession(FakeResponse(200, {"error": {"message": "upstream hiccup"}}), chat_ok("fine"))
    assert client(session).complete([]) == "fine"


def test_errors_never_contain_the_api_key():
    leaky = requests.ConnectionError(f"failed for Authorization: Bearer {SECRET}")
    session = FakeSession(leaky, leaky, leaky)
    with pytest.raises(LLMConnectionError) as info:
        client(session).complete([])
    assert SECRET not in str(info.value)


def test_missing_key_is_rejected_at_construction():
    with pytest.raises(LLMAuthError):
        OpenRouterClient("", "m")
