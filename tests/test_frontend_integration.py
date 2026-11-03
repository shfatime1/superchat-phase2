"""Part 3: real local routing, transport ownership, and retry integration."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, Settings
from app.fallback import LocalRouter, ResilientRouter
from app.main import create_app
from app.repositories import Repositories
from app.routing import InvalidRouterResponse, RouterUnavailable
from app.schemas import Domain
from app.state import SessionState


@pytest.fixture
def offline():
    with TestClient(create_app(Settings(data_mode="fixtures", routing_mode="offline"))) as client:
        client.get("/api/client")
        yield client


@pytest.fixture
def local():
    return LocalRouter(Repositories.from_json(PROJECT_ROOT / "data"))


@pytest.mark.parametrize("message,category", [
    ("Flights from Baku to Istanbul on Friday", "flights"),
    ("Show wireless headphones under 100 AZN", "shopping"),
    ("What movies are playing tonight?", "cinema"),
    ("Flights from Baku to Istanbul on Friday and a backpack under 100 AZN", "mixed"),
    ("Help me choose", "ambiguous"),
    ("Write a poem about the weather", "out_of_scope"),
    ("Book it", "ambiguous"),
    ("Flights and shopping", "mixed"),
])
def test_local_categories(local, message, category):
    answer = local.route(message, SessionState())
    assert answer.category.value == category
    assert answer.source == "local"


@pytest.mark.parametrize("message", [
    "Don't reserve F001 for 1 passenger", "Reserve F001 if it is refundable",
    "Add -1 P001 to my cart", "Add 1.5 P001 to my cart", "Add 1,5 P001 to my cart",
    "Add 0 P001 to my cart", "Reserve 1 or 2 tickets for S001",
    "Reserve flight F001 for 1 passenger without baggage",
    "Add 1 P001 and remove 1 P008", "Reserve F001 for 1 passenger tomorrow",
    "Add 2 P001 except the black one", "Reserve 1 ticket for S001 and a mystery item",
    "Add 2 P001 for 3 units", "Reserve 2 passengers for F002 9",
    "Movies rated 99", "Flights from Baku to Istanbul on 2026-99-99",
])
def test_uncertain_local_input_never_executes(local, message):
    answer = local.route(message, SessionState())
    assert answer.category.value == "ambiguous"
    assert not answer.intents


def post(client, message, session=None, request_id=None):
    payload = {"message": message}
    if session:
        payload["session_id"] = session
    if request_id:
        payload["request_id"] = str(request_id)
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_local_full_domain_switch_and_followups(offline):
    flights = post(offline, "Flights from Baku to Istanbul on Friday, cheapest first")
    sid = flights["session_id"]
    assert [f["id"] for f in flights["results"][0]["data"]["flights"]] == ["F013", "F002", "F001"]
    direct = post(offline, "Only direct", sid)
    assert direct["routing"]["category"] == "follow_up"
    assert {f["id"] for f in direct["results"][0]["data"]["flights"]} == {"F001", "F002"}
    shop = post(offline, "Show headphones under 100 AZN", sid)
    assert shop["results"][0]["data"]["products"][0]["id"] == "P001"
    cart = post(offline, "Add two of the first one", sid)
    assert cart["state"]["shopping"]["cart"] == {"P001": 2}
    cinema = post(offline, "What movies are playing tonight?", sid)
    assert {r["id"] for r in cinema["results"][0]["data"]["movies"]} == {"M001", "M003", "M008"}
    resumed = post(offline, "Back to flights", sid)
    assert resumed["state"]["flights"]["parameters"]["departure_date"] == "2026-11-06"
    assert resumed["state"]["shopping"]["cart"] == {"P001": 2}
    assert resumed["state"]["cinema"]["parameters"]["date"] == "2026-11-02"


def test_local_mixed_executes_both_and_unqualified_followup_is_ambiguous(offline):
    answer = post(offline, "Find a flight from Baku to Istanbul on Friday and a backpack under 100 AZN")
    assert [r["domain"] for r in answer["results"]] == ["flights", "shopping"]
    assert all(r["status"] == "ok" for r in answer["results"])
    assert post(offline, "The first one", answer["session_id"])["routing"]["category"] == "ambiguous"


def test_local_pending_quantity_and_safe_mock_reservations(offline):
    pending = post(offline, "Reserve flight F002")
    assert pending["results"][0]["status"] == "clarification"
    booked = post(offline, "Two passengers", pending["session_id"])
    reservation = booked["results"][0]["data"]["reservation"]
    assert reservation["quantity"] == 2 and reservation["mock"] and not reservation["paid"]
    movie = post(offline, "Reserve 2 tickets for showtime S001", pending["session_id"])
    assert movie["results"][0]["code"] == "reserved"
    assert movie["results"][0]["data"]["reservation"]["confirmation_id"] != reservation["confirmation_id"]
    unavailable = post(offline, "Reserve 2 passengers for flight F002", pending["session_id"])
    assert unavailable["results"][0]["code"] == "insufficient_seats"


def test_no_assumed_quantity_and_unknown_id(offline):
    answer = post(offline, "Add P001 to my cart")
    assert answer["results"][0]["status"] == "clarification"
    assert not answer["state"]["shopping"]["cart"]
    assert post(offline, "Show details for P999")["results"][0]["code"] == "unknown_id"


def test_explicit_domain_followup_can_return_to_saved_context(offline):
    start = post(offline, "Show me laptops")
    sid = start["session_id"]
    answer = post(offline, "The second one, is it in stock?", sid)
    assert answer["routing"]["category"] == "follow_up"
    assert answer["results"][0]["data"]["products"][0]["id"] == "P004"
    post(offline, "What is playing tonight?", sid)
    post(offline, "Show me laptops", sid)
    returned = post(offline, "The sci-fi one, any seats on Saturday?", sid)
    assert returned["routing"]["category"] == "follow_up"
    assert returned["routing"]["domains"] == ["cinema"]
    assert returned["state"]["cinema"]["parameters"]["date"] == "2026-11-07"


@pytest.mark.parametrize("failure", [RouterUnavailable("Service unavailable"), InvalidRouterResponse("invalid")])
def test_provider_failure_uses_circuit_breaker(monkeypatch, failure):
    router = ResilientRouter(Settings(data_mode="fixtures", api_key="test-placeholder"), Repositories.from_json(PROJECT_ROOT / "data"))
    calls = []
    def fail(*args):
        calls.append(1)
        raise failure
    monkeypatch.setattr(router.primary, "route", fail)
    assert router.route("Show headphones", SessionState()).source == "local"
    assert router.route("Flights", SessionState()).source == "local"
    assert len(calls) == 1
    router._unavailable_until = 0
    router.route("Movies", SessionState())
    assert len(calls) == 2


def test_auto_without_key_never_calls_gemini(block_live_gemini):
    with TestClient(create_app(Settings(data_mode="fixtures", api_key=None))) as client:
        answer = post(client, "Show headphones")
        assert answer["routing"]["source"] == "local"
    block_live_gemini.assert_not_called()


def test_auto_503_outage_still_serves_grounded_results(gemini):
    _, enqueue = gemini
    enqueue(RuntimeError("503 private provider detail"))
    with TestClient(create_app(Settings(data_mode="fixtures", api_key="test-placeholder"))) as client:
        result = post(client, "Show headphones under 100 AZN")
        assert result["routing"]["source"] == "local"
        assert result["results"][0]["data"]["products"][0]["price_azn"] == 89.9
        assert "private provider" not in str(result)


def test_browser_ownership_and_cookie_namespace(offline):
    first = offline.get("/api/client")
    namespace = first.json()["namespace"]
    result = post(offline, "Add 2 P001 to my cart")
    sid = result["session_id"]
    assert offline.get(f"/api/session/{sid}").status_code == 200
    old_owner = offline.cookies.get("superchat_owner")
    offline.cookies.clear()
    assert offline.get("/api/client").json()["namespace"] != namespace
    assert offline.get(f"/api/session/{sid}").status_code == 404
    assert offline.post("/api/chat", json={"message": "Show cart", "session_id": sid}).status_code == 404
    assert post(offline, "Show cart")["state"]["shopping"]["cart"] == {}
    offline.cookies.clear()
    offline.cookies.set("superchat_owner", old_owner)
    assert offline.get(f"/api/session/{sid}").json()["shopping"]["cart"] == {"P001": 2}


@pytest.mark.parametrize("message,domain,collection", [
    ("Add 2 P001 to my cart", "shopping", "cart"),
    ("Reserve flight F002 for 1 passenger", "flights", "reservations"),
    ("Reserve 1 ticket for showtime S001", "cinema", "reservations"),
])
def test_retry_returns_same_committed_result_once(offline, message, domain, collection):
    request_id = uuid4()
    first = post(offline, message, request_id=request_id)
    second = post(offline, message, request_id=request_id)
    assert first == second
    state = offline.get(f"/api/session/{first['session_id']}").json()
    assert len(state["history"]) == 2
    assert len(state[domain][collection]) == 1
    assert offline.post("/api/chat", json={"message": "Show cart", "request_id": str(request_id)}).status_code == 409


def test_simultaneous_retries_commit_once(offline):
    request_id = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(offline, "Reserve flight F002 for 1 passenger", request_id=request_id), range(2)))
    assert results[0] == results[1]
    assert len(results[0]["state"]["flights"]["reservations"]) == 1


def test_structured_history_survives_session_fetch(offline):
    result = post(offline, "Show headphones")
    state = offline.get(f"/api/session/{result['session_id']}").json()
    assert state["history"][-1]["results"] == result["results"]
    assert state["history"][-1]["routing"]["source"] == "local"


def test_static_page_assets_and_headers(offline):
    page = offline.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "Content-Security-Policy" in page.headers
    for path, mime in (("app.js", "javascript"), ("styles.css", "text/css"), ("favicon.svg", "image/svg+xml")):
        response = offline.get("/static/" + path)
        assert response.status_code == 200 and mime in response.headers["content-type"]
    assert offline.get("/api/client").headers["cache-control"] == "no-store"
    offline.cookies.clear()
    cookie = offline.get("/api/client").headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_secure_cookie_setting():
    with TestClient(create_app(Settings(data_mode="fixtures", secure_cookies=True)), base_url="https://testserver") as client:
        assert "Secure" in client.get("/api/client").headers["set-cookie"]


def test_port_entrypoint_uses_environment(monkeypatch):
    import runpy
    import uvicorn
    captured = {}
    monkeypatch.setenv("PORT", "9100")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs))
    runpy.run_module("app.serve", run_name="__main__")
    assert captured == {"app": "app.main:app", "host": "127.0.0.1", "port": 9100, "workers": 1}
