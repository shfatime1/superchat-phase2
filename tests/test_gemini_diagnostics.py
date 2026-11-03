import logging

import pytest
from fastapi.testclient import TestClient
from google.genai import errors
import httpx

from app.config import Settings
from app.main import create_app
from app.routing import GeminiRouter, RouterUnavailable
from app.state import SessionState
from conftest import route


def test_render_environment_is_used_and_whitespace_normalized(monkeypatch):
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("GEMINI_API_KEY", " private-test-key \n")
    monkeypatch.setenv("GEMINI_MODEL", " gemini-flash-latest ")
    monkeypatch.setenv("SUPERCHAT_ROUTING_MODE", " AUTO ")
    settings = Settings.from_env()
    assert settings.api_key == "private-test-key"
    assert settings.model == "gemini-flash-latest"
    assert settings.routing_mode == "auto"
    assert "private-test-key" not in repr(settings)


@pytest.mark.parametrize("failure,reason,status", [
    (errors.ClientError(400, {"error": {"message": "secret-request"}}), "request_rejected", 400),
    (errors.ClientError(403, {"error": {"message": "secret-key"}}), "credentials_or_permissions", 403),
    (errors.ClientError(404, {"error": {"message": "secret-url"}}), "model_not_found", 404),
    (errors.ClientError(429, {"error": {"message": "secret-project"}}), "quota_or_rate_limit", 429),
    (errors.ServerError(503, {"error": {"message": "secret-data"}}), "provider_unavailable", 503),
    (errors.ServerError(504, {"error": {"message": "secret-data"}}), "timeout", 504),
    (httpx.ReadTimeout("secret-url"), "timeout", None),
    (RuntimeError("secret-key"), "sdk_or_network_error", None),
])
def test_safe_error_logging(failure, reason, status, gemini, caplog):
    _, enqueue = gemini
    enqueue(failure)
    with caplog.at_level(logging.WARNING), pytest.raises(RouterUnavailable):
        GeminiRouter(Settings(data_mode="fixtures", api_key="secret-key")).route("secret-user-message", SessionState())
    assert f"reason={reason}" in caplog.text
    assert f"http_status={status}" in caplog.text
    assert "secret" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("settings,status,configured", [
    (Settings(data_mode="fixtures", routing_mode="offline", api_key="secret-key"), "offline", True),
    (Settings(data_mode="fixtures", routing_mode="auto"), "missing_key", False),
    (Settings(data_mode="fixtures", routing_mode="auto", api_key="secret-key"), "ready", True),
])
def test_client_distinguishes_configured_disabled_and_ready(settings, status, configured):
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/client")
        assert response.json()["routing_status"] == status
        assert response.json()["gemini_configured"] is configured
        assert "secret" not in response.text


def test_auto_attempts_gemini_then_falls_back_and_recovers(gemini, caplog):
    generate, enqueue = gemini
    enqueue(errors.ServerError(503, {"error": {"message": "secret-key"}}), route("flights", "flights"))
    with caplog.at_level(logging.WARNING), TestClient(create_app(Settings(data_mode="fixtures", api_key="secret-key"))) as client:
        first = client.post("/api/chat", json={"message": "Flights"}).json()
        assert first["routing"]["source"] == "local"
        assert client.get("/api/client").json()["routing_status"] == "cooldown"
        client.post("/api/chat", json={"message": "Flights"})
        assert generate.call_count == 1
        client.app.state.chat_service.router._unavailable_until = 0
        recovered = client.post("/api/chat", json={"message": "Flights"}).json()
        assert recovered["routing"]["source"] == "gemini"
        assert generate.call_count == 2
        assert client.get("/api/client").json()["routing_status"] == "ready"
    assert "reason=provider_unavailable" in caplog.text
    assert "cooldown_seconds=60" in caplog.text
    assert "secret" not in caplog.text


def test_invalid_output_is_logged_without_model_text(gemini, caplog):
    _, enqueue = gemini
    enqueue({"category": "secret-invalid-category"})
    with caplog.at_level(logging.WARNING), TestClient(create_app(Settings(data_mode="fixtures", api_key="secret-key"))) as client:
        assert client.post("/api/chat", json={"message": "Flights"}).json()["routing"]["source"] == "local"
    assert "reason=invalid_structured_output" in caplog.text
    assert "secret" not in caplog.text
