"""Regressions spanning Gemini extraction, saved cinema state and public listings."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.fallback import LocalRouter
from app.main import create_app
from app.providers.engine import ProviderDomainEngine
from app.repositories import Repositories
from app.schemas import CinemaParameters
from app.state import SessionState
from conftest import route
from test_cinemaplus_public import client as public_client


@pytest.mark.parametrize("parameters", [
    {"cinema_name": "CinemaPlus", "movie_title": "all movies", "language": "English"},
    {},
])
def test_chat_all_movies_then_today_showtimes(gemini, monkeypatch, parameters):
    monkeypatch.setattr(Settings, "reference_date", lambda self: date(2026, 11, 3))
    _, enqueue = gemini
    enqueue(route("cinema", "cinema", parameters),
            route("cinema", "cinema", {"cinema_name": "CinemaPlus", "date_text": "today"}, intent="details"))
    settings = Settings(api_key="test", routing_mode="strict", tmdb_token="test")
    app = create_app(settings)
    with TestClient(app) as browser:
        http, paths = public_client()
        app.state.chat_service.engine = ProviderDomainEngine(settings, http)
        first = browser.post("/api/chat", json={"message": "Show me all CinemaPlus movies"}).json()
        assert first["results"][0]["status"] == "ok"
        assert len(first["results"][0]["data"]["movies"]) == 2
        second = browser.post("/api/chat", json={"message": "Today's showtimes", "session_id": first["session_id"]}).json()
        result = second["results"][0]
        assert result["status"] == "ok" and len(result["data"]["showtimes"]) == 2
        assert all(s["date"] == "2026-11-03" for s in result["data"]["showtimes"])
        assert all(s["showtimes_url"].startswith("https://cinemastercard.az/en/films/") for s in result["data"]["showtimes"])
        assert result["data"]["provider"]["provider"] == "CinemaPlus Azerbaijan"
        assert "No matching provider results" not in second["message"]
        assert not any(p.startswith("/3/") for p in paths)


def test_explicit_all_movies_clears_old_cinema_filters_only(gemini):
    from app.routing import GeminiRouter
    _, enqueue = gemini
    enqueue(route("cinema", "cinema", {}))
    state = SessionState()
    state.cinema.parameters = CinemaParameters(movie_title="44", cinema_name="Ganjlik", language="Azerbaijani", date="2030-01-01")
    state.shopping.cart = {"EBAY-v1|123|0": 2}
    http, _ = public_client()
    result = GeminiRouter(Settings(api_key="test")).route("Show me all CinemaPlus movies", state)
    outcome = ProviderDomainEngine(Settings(), http).execute(result, state)[0]
    assert outcome.status == "ok" and len(outcome.data["movies"]) == 2
    assert state.cinema.parameters == CinemaParameters()
    assert state.shopping.cart == {"EBAY-v1|123|0": 2}


def test_local_all_movies_clears_old_filters_and_today_preserves_specific_movie():
    router = LocalRouter(Repositories.empty(), lambda: date(2026, 11, 3))
    state = SessionState()
    state.cinema.parameters = CinemaParameters(movie_title="44", cinema_name="Ganjlik", date="2030-01-01")
    http, _ = public_client()
    engine = ProviderDomainEngine(Settings(), http)
    outcome = engine.execute(router.route("Show me all CinemaPlus movies", state), state)[0]
    assert outcome.status == "ok" and len(outcome.data["movies"]) == 2
    state.cinema.parameters.movie_title = "44"
    today = engine.execute(router.route("Today's showtimes", state), state)[0]
    assert today.status == "ok" and len(today.data["showtimes"]) == 1
    assert today.data["movies"][0]["id"] == "CP-44"


@pytest.mark.parametrize("operation", ["search", "details"])
def test_fresh_today_showtimes_without_selection(gemini, operation):
    from app.routing import GeminiRouter
    _, enqueue = gemini
    enqueue(route("cinema", "cinema", {"cinema_name": "CinemaPlus", "date_text": "today"}, intent=operation))
    settings = Settings(api_key="test")
    # Resolve the relative date deterministically without depending on the host clock.
    router = GeminiRouter(settings)
    from unittest.mock import patch
    with patch.object(Settings, "reference_date", return_value=date(2026, 11, 3)):
        state = SessionState()
        extracted = router.route("Show me today's CinemaPlus showtimes", state)
    http, _ = public_client()
    result = ProviderDomainEngine(settings, http).execute(extracted, state)[0]
    assert result.status == "ok" and len(result.data["showtimes"]) == 2
    assert state.cinema.parameters.date == date(2026, 11, 3)


def test_named_movie_and_branch_followups_keep_explicit_filters(gemini):
    from app.routing import GeminiRouter
    _, enqueue = gemini
    enqueue(route("cinema", "cinema", {"date_text": "today"}, intent="details"))
    state = SessionState()
    state.cinema.parameters = CinemaParameters(movie_title="44", cinema_name="Ganjlik", language="Azerbaijani")
    state.cinema.intent = "search"
    http, _ = public_client()
    from unittest.mock import patch
    with patch.object(Settings, "reference_date", return_value=date(2026, 11, 3)):
        extracted = GeminiRouter(Settings(api_key="test")).route("Today's showtimes", state)
    result = ProviderDomainEngine(Settings(), http).execute(extracted, state)[0]
    assert result.status == "ok" and len(result.data["showtimes"]) == 1
    assert state.cinema.parameters.movie_title == "44"
    assert state.cinema.parameters.cinema_name == "Ganjlik"
    assert state.cinema.parameters.language == "Azerbaijani"
