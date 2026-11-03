"""Focused streaming, privacy, cache, rate-limit and pagination checks. Offline HTTP."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.diagnostics import Trace
from app.main import create_app
from app.providers.http import ProviderHTTP, ProviderFailure
from app.providers.buywhere import BuyWhereProvider
from app.schemas import ShoppingParameters

ITEM = {"id": "1", "title": "Wireless headphones", "price": {"amount": 49, "currency": "USD"},
        "url": "https://retailer.example/headphones", "category_path": None}


def app_client(**settings):
    return TestClient(create_app(Settings(routing_mode="offline", provider_retries=0, **settings)))


def events(response):
    records = []
    for frame in response.text.split("\n\n"):
        lines = frame.splitlines()
        if len(lines) >= 2 and lines[0].startswith("event:"):
            records.append((lines[0][7:], json.loads(lines[1][6:])))
    return records


def test_stream_progress_text_before_finalization_debug_privacy_and_idempotent_retry(monkeypatch):
    calls, emitted = [], []
    with app_client(buywhere_token="secret-provider-token") as client:
        service = client.app.state.chat_service
        def handler(request):
            calls.append(request)
            assert request.headers["Authorization"] == "Bearer secret-provider-token"
            return httpx.Response(200, json={"data": [ITEM]})
        service.engine.http.transport = httpx.MockTransport(handler)
        original = service.formulator.formulate
        def formulate(*args, **kwargs):
            # The actual SSE callback receives grounded answer text before the
            # response-plan stage finishes, rather than splitting a completed reply.
            assert emitted
            return original(*args, **kwargs)
        monkeypatch.setattr(service.formulator, "formulate", formulate)
        original_chat = service.chat
        def chat(*args, emit=None, **kwargs):
            def observe(event, data):
                if event == "text": emitted.append(data)
                if emit: emit(event, data)
            return original_chat(*args, emit=observe, **kwargs)
        monkeypatch.setattr(service, "chat", chat)
        body = {"message": "Show headphones under $100", "request_id": str(uuid4())}
        response = client.post("/api/chat/stream", json=body)
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        records = events(response)
        assert records[0][0] == "progress" and any(kind == "text" for kind, _ in records)
        final = records[-1][1]
        assert records[-1][0] == "complete" and final["results"][0]["status"] == "ok"
        debug = final["debug"]
        assert debug["routing"]["source"] == "local" and debug["cache"]["misses"] == 1
        assert debug["provider_calls"][0]["status"] == 200 and debug["provider_calls"][0]["attempts"] == 1
        assert "secret-provider-token" not in json.dumps(debug) and "headphones" not in json.dumps(debug)
        retry = client.post("/api/chat", json=body).json()
        assert retry == final and len(calls) == 1 and len(final["state"]["history"]) == 2
        assert client.get("/api/session/" + final["session_id"]).json()["history"][-1]["debug"] == debug


def test_thirty_minute_cache_isolation_expiry_refresh_and_context_invalidation():
    calls, clock = [], [0]
    with app_client() as client:
        http = client.app.state.chat_service.engine.http
        http.clock = lambda: clock[0]
        http.transport = httpx.MockTransport(lambda req: (calls.append(req) or httpx.Response(200, json={"data": [ITEM]})))
        first = client.post("/api/chat", json={"message": "Show headphones under $100"}).json()
        sid = first["session_id"]
        query = {"message": "Show headphones under $100", "session_id": sid}
        cached = client.post("/api/chat", json=query).json()
        assert len(calls) == 1 and cached["debug"]["cache"]["hits"] == 1
        assert cached["debug"]["routing"]["cache"] == "hit"
        # Separate conversation, even for the same browser, cannot read that cache.
        client.post("/api/chat", json={"message": "Show headphones under $100"})
        assert len(calls) == 2
        clock[0] = 1799
        client.post("/api/chat", json=query); assert len(calls) == 2
        clock[0] = 1801
        client.post("/api/chat", json=query); assert len(calls) == 3
        client.post("/api/chat", json={**query, "refresh_cache": True}); assert len(calls) == 4
        client.post("/api/chat", json={"message": "Under $50", "session_id": sid}); assert len(calls) == 5
        assert calls[-1].url.params["max_price"] == "50.0"


def test_owner_authentication_applies_to_json_stream_and_debug_history():
    app = create_app(Settings(routing_mode="offline"))
    with TestClient(app) as owner:
        response = owner.post("/api/chat", json={"message": "Flights"}).json()
        with TestClient(app) as stranger:
            sid = response["session_id"]
            for path in ("/api/chat", "/api/chat/stream"):
                assert stranger.post(path, json={"message": "Flights", "session_id": sid, "request_id": str(uuid4())}).status_code == 404
            assert stranger.get("/api/session/" + sid).status_code == 404


def test_chat_rate_limit_retry_after_and_idempotent_replay_do_not_consume_quota():
    with app_client(chat_rate_limit=2) as client:
        body = {"message": "Flights", "request_id": str(uuid4())}
        assert client.post("/api/chat", json=body).status_code == 200
        assert client.post("/api/chat", json=body).status_code == 200
        assert client.post("/api/chat", json={"message": "Flights"}).status_code == 200
        limited = client.post("/api/chat", json={"message": "Flights"})
        assert limited.status_code == 429 and 1 <= int(limited.headers["retry-after"]) <= 60
        stream = events(client.post("/api/chat/stream", json={"message": "Flights", "request_id": str(uuid4())}))
        assert stream[-1][0] == "error" and stream[-1][1]["code"] == "rate_limited"


@pytest.mark.parametrize("status,code", [(401, "credentials_or_permissions"), (403, "credentials_or_permissions"), (429, "rate_limited")])
def test_provider_auth_and_quota_errors_are_sanitized_in_debug(status, code):
    with app_client() as client:
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(lambda req: httpx.Response(status, text="secret upstream body", headers={"Retry-After": "30"}))
        body = client.post("/api/chat", json={"message": "Show headphones"}).json()
        assert body["results"][0]["data"]["provider_error"]["code"] == code
        assert body["debug"]["provider_calls"][0]["error"] == code
        assert "secret upstream body" not in json.dumps(body)


def test_provider_timeout_and_request_deadline_do_not_commit_a_failed_turn():
    with app_client() as client:
        def timeout(req): raise httpx.ReadTimeout("secret timeout url", request=req)
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(timeout)
        body = client.post("/api/chat", json={"message": "Show headphones"}).json()
        assert body["debug"]["provider_calls"][0]["error"] == "timeout"
        assert "secret timeout url" not in json.dumps(body)
    with app_client(chat_timeout_seconds=0) as client:
        assert client.post("/api/chat", json={"message": "Flights"}).status_code == 504
        assert client.app.state.sessions._sessions == {}


def test_pagination_uses_documented_offsets_stops_on_empty_and_resets_on_filter_changes():
    calls = []
    with app_client() as client:
        def handler(req):
            calls.append(req)
            return httpx.Response(200, json={"data": [ITEM] if len(calls) == 1 else [], "meta": {"has_more": True}})
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(handler)
        first = client.post("/api/chat", json={"message": "Show headphones under $100"}).json()
        assert first["results"][0]["data"]["pagination"]["next_offset"] == 50
        sid = first["session_id"]
        second = client.post("/api/chat", json={"message": "More products.", "session_id": sid}).json()
        assert calls[-1].url.params["offset"] == "50" and calls[-1].url.params["max_price"] == "100.0"
        assert second["results"][0]["data"]["pagination"]["has_more"] is False
        third = client.post("/api/chat", json={"message": "Under $50", "session_id": sid}).json()
        assert "offset" not in calls[-1].url.params and third["state"]["shopping"]["parameters"]["max_price"] == 50
