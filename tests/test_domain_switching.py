"""Focused regressions for switching, context and Gemini recovery."""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routing import routing_context
from app.state import HistoryTurn, SessionState
from conftest import route


def send(client, message, sid=None, **extra):
    response = client.post("/api/chat", json={"message": message, "session_id": sid, **extra})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("messages,expected", [
    (["Flights from GYD to IST on 2026-12-01", "Show me all CinemaPlus movies",
      "Show laptops under $500", "Back to flights"], ["flights", "cinema", "shopping", "flights"]),
    (["Movies tonight", "Show headphones under $100", "Back to cinema"],
     ["cinema", "shopping", "cinema"]),
])
def test_exact_sequences_and_saved_context(messages, expected):
    with TestClient(create_app(Settings(data_mode="fixtures", routing_mode="offline"))) as client:
        sid, snapshots = None, {}
        for message, domain in zip(messages, expected):
            answer = send(client, message, sid)
            sid = answer["session_id"]
            assert answer["routing"]["domains"] == [domain]
            assert answer["state"]["last_active_domain"] == domain
            assert [r["domain"] for r in answer["results"]] == [domain]
            for other, saved in snapshots.items():
                assert answer["state"][other]["parameters"] == saved
            snapshots[domain] = answer["state"][domain]["parameters"]
        if "flights" in snapshots:
            assert snapshots["flights"]["departure_date"] == "2026-12-01"
        assert snapshots["shopping"]["currency"] == "USD"


def test_stale_gemini_domain_falls_back_for_one_turn_and_recovers(gemini):
    generate, enqueue = gemini
    enqueue(route("flights", "flights"),
            route("follow_up", "flights", {"destination": "Istanbul"}),
            route("shopping", "shopping", {"query": "laptops"}))
    with TestClient(create_app(Settings(data_mode="fixtures", api_key="test-key"))) as client:
        first = send(client, "Flights")
        second = send(client, "Show all CinemaPlus movies", first["session_id"])
        assert second["routing"]["domains"] == ["cinema"]
        assert second["routing"]["fallback_reason"] == "explicit_domain_mismatch"
        assert second["state"]["flights"]["parameters"] == first["state"]["flights"]["parameters"]
        assert client.get("/api/client").json()["routing_status"] == "ready"
        third = send(client, "Show laptops", first["session_id"])
        assert third["routing"]["source"] == "gemini"
        assert third["routing"]["domains"] == ["shopping"]
        assert generate.call_count == 3


def test_invalid_gemini_output_does_not_disable_other_turns(gemini):
    _, enqueue = gemini
    enqueue({"category": "invalid"}, route("cinema", "cinema"))
    with TestClient(create_app(Settings(data_mode="fixtures", api_key="test-key"))) as client:
        first = send(client, "Flights")
        assert first["routing"]["fallback_reason"] == "invalid_structured_output"
        assert client.get("/api/client").json()["routing_status"] == "ready"
        assert send(client, "Cinema", first["session_id"])["routing"]["source"] == "gemini"


def test_every_message_routes_again_and_sidebar_hint_never_overrides_explicit_subject(gemini):
    generate, enqueue = gemini
    enqueue(route("shopping", "shopping", {"query": "laptops"}),
            route("cinema", "cinema"), route("shopping", "shopping", {"query": "laptops"}),
            route("follow_up", "cinema", {"date_text": "today"}))
    with TestClient(create_app(Settings(data_mode="fixtures", api_key="test-key"))) as client:
        first = send(client, "Show laptops")
        sid = first["session_id"]
        send(client, "Cinema", sid, domain_hint="flights")
        third = send(client, "Show laptops", sid)
        assert third["routing"]["source"] == "gemini"
        assert generate.call_count == 3
        last = send(client, "What is on today?", sid, domain_hint="cinema")
        assert last["routing"]["domains"] == ["cinema"]
        context = json.loads(generate.call_args.kwargs["contents"])["context"]
        assert context["last_active_domain"] == "cinema"
        assert last["state"]["shopping"]["parameters"]["query"] == "laptops"


def test_routing_context_excludes_large_catalogue_responses_and_debug():
    state = SessionState()
    state.shopping.provider_snapshot = {"items": [{"name": "PRIVATE_PROVIDER_PAYLOAD" * 10000}]}
    state.history = [HistoryTurn(role="user", content="Show laptops"),
                     HistoryTurn(role="assistant", content="VERBOSE_ANSWER" * 10000,
                                 debug={"payload": "DEBUG_PAYLOAD" * 10000})]
    state.shopping.last_result_ids = ["BW-123"]
    context = routing_context(state)
    encoded = json.dumps(context)
    assert "PRIVATE_PROVIDER_PAYLOAD" not in encoded
    assert "VERBOSE_ANSWER" not in encoded and "DEBUG_PAYLOAD" not in encoded
    assert context["shopping"]["last_result_ids"] == ["BW-123"]
    assert context["recent_history"][0]["content"] == "Show laptops"


def test_flight_tickets_are_not_mixed_with_cinema():
    with TestClient(create_app(Settings(data_mode="fixtures", routing_mode="offline"))) as client:
        assert send(client, "Flight tickets from GYD to IST on Friday")["routing"]["domains"] == ["flights"]


def test_new_cinema_listing_overrides_model_resume_and_old_movie_filter(gemini):
    _, enqueue = gemini
    enqueue(route("cinema", "cinema", {"movie_title": "Dune"}),
            route("shopping", "shopping", {"query": "laptops"}),
            route("follow_up", "cinema", {"movie_title": "Dune"}, intent="resume"))
    with TestClient(create_app(Settings(data_mode="providers", api_key="test-key"))) as client:
        # Only test routing/state here; provider access is verified separately live.
        from app.domains.engine import DomainEngine
        from app.repositories import Repositories
        client.app.state.chat_service.engine = DomainEngine(Repositories.empty())
        first = send(client, 'Show movie "Dune"')
        send(client, "Show laptops", first["session_id"])
        last = send(client, "Show me all CinemaPlus movies", first["session_id"])
        assert last["routing"]["domains"] == ["cinema"]
        assert last["routing"]["intents"][0]["intent"] == "search"
        assert last["state"]["cinema"]["parameters"] == {}
        assert last["state"]["shopping"]["parameters"]["query"] == "laptops"
