"""Exact Render failures: local fallback must call BuyWhere with a clean query."""
import httpx
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.languages import normalize_text


@pytest.mark.parametrize("message", ["Mənə noutbukları ver", "mene notebokklari ver"])
def test_exact_az_request_calls_buywhere_despite_previous_flight_domain(message):
    calls = []
    with TestClient(create_app(Settings(routing_mode="auto"))) as client:
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"data": []})
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(handler)
        first = client.post("/api/chat", json={"message": "Flights"}).json()
        response = client.post("/api/chat", json={"message": message, "session_id": first["session_id"], "domain_hint": "cinema"})
        assert response.status_code == 200
        body = response.json()
        assert body["routing"]["category"] == "shopping"
        assert body["routing"]["domains"] == ["shopping"]
        assert body["routing"]["language"] == "az"
        assert body["state"]["shopping"]["parameters"]["query"] == "laptops"
        assert body["state"]["last_active_domain"] == "shopping"
        assert len(calls) == 1 and calls[0].url.host == "api.buywhere.ai"
        assert calls[0].url.path == "/v1/products/search" and calls[0].url.params["q"] == "laptops"
        print(f"VERIFIED: {ascii(message)} -> shopping -> BuyWhere q=laptops, language=az")


def test_case_endings_typos_and_other_queries_remain_stable():
    for phrase in ("Mənə noutbukları ver", "mene notebokklari ver", "mene notebooklari verin", "mene noutbuklari ver", "mene noutbuku ver"):
        assert normalize_text(phrase) == "laptops"
    assert normalize_text("laptops under $500") == "laptops under $500"
    assert normalize_text("Flights from Baku to Istanbul tomorrow") == "flights from baku to istanbul tomorrow"


@pytest.mark.parametrize("message", ["Mənə noutbukları ver", "mene notebokklari ver"])
def test_gemini_ambiguous_falls_back_to_shopping(message, gemini):
    _, enqueue = gemini
    enqueue({"category": "ambiguous", "domains": [], "intents": []})
    with TestClient(create_app(Settings(api_key="test", routing_mode="auto"))) as client:
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"data": []})
        client.app.state.chat_service.engine.http.transport = httpx.MockTransport(handler)
        body = client.post("/api/chat", json={"message": message}).json()
        assert body["routing"]["domains"] == ["shopping"]
        assert calls and calls[0].url.params["q"] == "laptops"
