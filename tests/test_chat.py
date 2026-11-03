import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.state import SessionStore
from conftest import route


def send(client, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_existing_routes_preserved(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "text/html" in home.headers["content-type"]
    assert "SuperChat" in home.text
    assert client.get("/health").json() == {"status": "ok"}


def test_switch_across_three_domains_and_return(client, gemini):
    generate, enqueue = gemini
    enqueue(
        route("flights", "flights", {"origin": "Baku", "destination": "Istanbul", "departure_date_text": "Friday"}),
        route("cinema", "cinema", {"date_text": "tonight", "genre": "sci-fi"}),
        route("shopping", "shopping", {"query": "headphones", "max_price_azn": 100}),
        route("follow_up", "flights", {"sort_by": "price_asc"}, intent="sort"),
        route("follow_up", "cinema", {"date_text": "Saturday", "reference": "the sci-fi one"}, intent="availability"),
        route("follow_up", "shopping", intent="resume"),
    )
    first = send(client, "Find a flight from Baku to Istanbul on Friday")
    sid = first["session_id"]
    for message in ["What sci-fi is playing tonight?", "Headphones under 100 AZN",
                    "Back to flights, cheapest first", "The sci-fi one, any seats on Saturday?",
                    "Back to the headphones"]:
        result = send(client, message, sid)
    state = result["state"]
    assert state["flights"]["parameters"]["origin"] == "Baku"
    assert state["flights"]["parameters"]["departure_date"] == "2026-11-06"
    assert state["flights"]["parameters"]["sort_by"] == "price_asc"
    assert state["cinema"]["parameters"]["date"] == "2026-11-07"
    assert state["cinema"]["parameters"]["genre"] == "sci-fi"
    assert state["shopping"]["parameters"] == {"query": "headphones", "max_price_azn": 100}
    assert state["last_active_domain"] == "shopping"
    assert len(state["history"]) == 12
    assert client.get(f"/api/session/{sid}").json() == state
    context = json.loads(generate.call_args.kwargs["contents"])["context"]
    assert context["flights"]["parameters"]["origin"] == "Baku"
    assert context["cinema"]["parameters"]["date"] == "2026-11-07"
    assert len(context["recent_history"]) == 10


def test_short_follow_up_preserves_missing_parameters(client, gemini):
    _, enqueue = gemini
    enqueue(route("shopping", "shopping", {"query": "laptops"}),
            route("follow_up", "shopping", {"reference": "the second one"}, intent="availability"))
    first = send(client, "Show me laptops")
    follow = send(client, "The second one, is it in stock?", first["session_id"])
    assert follow["routing"]["category"] == "follow_up"
    params = follow["state"]["shopping"]["parameters"]
    assert params == {"query": "laptops", "reference": "the second one"}
    assert "product_ids" not in params


def test_unclear_replacement_date_does_not_reuse_old_date(client, gemini):
    _, enqueue = gemini
    enqueue(route("flights", "flights", {"destination": "Istanbul", "departure_date_text": "Friday"}),
            route("follow_up", "flights", {"departure_date_text": "sometime later"}))
    first = send(client, "Flights to Istanbul on Friday")
    second = send(client, "Actually, sometime later", first["session_id"])
    assert "departure_date" not in second["state"]["flights"]["parameters"]
    assert second["state"]["flights"]["parameters"]["destination"] == "Istanbul"
    assert second["routing"]["clarification"]


def test_mixed_updates_both_domains_and_requires_follow_up_target(client, gemini):
    _, enqueue = gemini
    enqueue({"category": "mixed", "domains": ["flights", "shopping"], "intents": [
        {"domain": "flights", "intent": "search", "parameters": {"destination": "Istanbul"}},
        {"domain": "shopping", "intent": "search", "parameters": {"query": "backpack"}},
    ]}, route("follow_up"))
    first = send(client, "A flight to Istanbul and a backpack for the trip")
    assert first["state"]["flights"]["parameters"] == {"destination": "Istanbul"}
    assert first["state"]["shopping"]["parameters"] == {"query": "backpack"}
    assert first["state"].get("last_active_domain") is None
    second = send(client, "book it", first["session_id"])
    assert second["routing"]["category"] == "ambiguous"


def test_session_isolation(client, gemini):
    generate, enqueue = gemini
    enqueue(route("flights", "flights", {"destination": "Istanbul"}),
            route("shopping", "shopping", {"query": "laptop"}))
    first = send(client, "Flights to Istanbul")
    second = send(client, "Show me laptops")
    assert first["session_id"] != second["session_id"]
    assert second["state"]["flights"]["parameters"] == {}
    assert first["state"]["shopping"]["parameters"] == {}
    assert "Istanbul" not in generate.call_args.kwargs["contents"]
    assert client.get(f"/api/session/{first['session_id']}").json() == first["state"]


@pytest.mark.parametrize("message,payload", [
    ("Show me something good", route("ambiguous")),
    ("Book two seats", route("ambiguous", clarification="Which flight or cinema showtime?")),
    ("What is the weather in Ganja?", route("out_of_scope")),
])
def test_ambiguous_out_of_scope_do_not_overwrite_domains(client, gemini, message, payload):
    _, enqueue = gemini
    enqueue(route("flights", "flights", {"destination": "Istanbul"}), payload)
    before = send(client, "Flights to Istanbul")
    after = send(client, message, before["session_id"])
    assert after["routing"]["category"] == payload["category"]
    assert after["routing"]["domains"] == []
    for domain in ["flights", "shopping", "cinema", "last_active_domain"]:
        assert after["state"][domain] == before["state"][domain]
    assert after["message"]


def test_explicit_reset_clear_and_shared_preferences(client, gemini):
    _, enqueue = gemini
    initial = route("shopping", "shopping", {"query": "laptops", "brand": "Nexar", "max_price_azn": 1500},
                    language="en", preferences=["Prefer low prices"])
    cleared = route("follow_up", "shopping")
    cleared["intents"][0]["clear_parameters"] = ["brand"]
    reset = route("shopping", "shopping", {"query": "backpack"})
    reset["intents"][0]["reset_context"] = True
    enqueue(initial, cleared, reset)
    one = send(client, "Nexar laptops under 1500; I prefer low prices")
    two = send(client, "Any brand is fine", one["session_id"])
    assert "brand" not in two["state"]["shopping"]["parameters"]
    assert two["state"]["shopping"]["parameters"]["max_price_azn"] == 1500
    three = send(client, "Start a new search for a backpack", one["session_id"])
    assert three["state"]["shopping"]["parameters"] == {"query": "backpack"}
    assert three["state"]["language"] == "en"
    assert three["state"]["preferences"] == ["Prefer low prices"]


@pytest.mark.parametrize("failure,status", [(RuntimeError("secret-key"), 503), ({"category": "bad"}, 502)])
def test_failed_calls_rollback_and_hide_errors(client, gemini, failure, status):
    _, enqueue = gemini
    enqueue(route("flights", "flights", {"destination": "Istanbul"}), failure)
    first = send(client, "Flights to Istanbul")
    sid = first["session_id"]
    response = client.post("/api/chat", json={"message": "tomorrow", "session_id": sid})
    assert response.status_code == status
    assert "secret-key" not in response.text
    assert client.get(f"/api/session/{sid}").json() == first["state"]


def test_missing_key_does_not_affect_health_or_create_session(block_live_gemini):
    app = create_app(Settings(data_mode="fixtures", routing_mode="strict"))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/api/chat", json={"message": "Flights"}).status_code == 503
        assert app.state.sessions._sessions == {}
    block_live_gemini.assert_not_called()


def test_missing_data_is_reported_safely(tmp_path):
    with TestClient(create_app(Settings(data_mode="fixtures", data_dir=tmp_path))) as client:
        assert client.get("/health").status_code == 503
        result = client.post("/api/chat", json={"message": "Flights"})
        assert result.status_code == 503
        assert str(tmp_path) not in result.text


@pytest.mark.parametrize("body", [{}, {"message": ""}, {"message": "  "},
    {"message": "x" * 8001}, {"message": "Flights", "session_id": "invalid"},
    {"message": "Flights", "unexpected": 1}])
def test_invalid_input(client, gemini, body):
    assert client.post("/api/chat", json=body).status_code == 422
    gemini[0].assert_not_called()


def test_unknown_sessions_and_invalid_id(client, gemini):
    sid = str(uuid4())
    assert client.get(f"/api/session/{sid}").status_code == 404
    assert client.get("/api/session/invalid").status_code == 422
    assert client.post("/api/chat", json={"message": "hello", "session_id": sid}).status_code == 404
    gemini[0].assert_not_called()


def test_session_copies_and_transaction_rollback():
    store = SessionStore()
    with store.transaction(None) as state:
        state.preferences.append("original")
    sid = state.session_id
    state.preferences.append("external mutation")
    store.get(sid).preferences.append("another mutation")
    with pytest.raises(RuntimeError):
        with store.transaction(sid) as update:
            update.preferences.append("uncommitted")
            raise RuntimeError("abort")
    assert store.get(sid).preferences == ["original"]


def test_concurrent_turns_are_serialized_per_session():
    store = SessionStore()
    with store.transaction(None) as initial:
        pass
    first_entered, release_first, second_started = Event(), Event(), Event()

    def first():
        with store.transaction(initial.session_id) as state:
            first_entered.set()
            assert release_first.wait(5)
            state.preferences.append("first")

    def second():
        assert first_entered.wait(5)
        second_started.set()
        with store.transaction(initial.session_id) as state:
            assert state.preferences == ["first"]
            state.preferences.append("second")

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(first), pool.submit(second)
        try:
            assert second_started.wait(5)
            # An unrelated session remains usable while the first one is busy.
            with store.transaction(None) as other:
                assert other.session_id != initial.session_id
        finally:
            release_first.set()
        a.result(timeout=5)
        b.result(timeout=5)
    assert store.get(initial.session_id).preferences == ["first", "second"]
