from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from app.config import PROJECT_ROOT
from app.domains.engine import DomainEngine
from app.repositories import DataSourceError, Repositories
from app.schemas import RoutingResult
from app.state import SessionState
from conftest import route


@pytest.fixture
def domain_setup():
    return DomainEngine(Repositories.from_json(PROJECT_ROOT / "data")), SessionState()


def run(engine, state, domain, action="search", params=None, **extra):
    payload = route(domain, domain, params, intent=action)
    payload["intents"][0].update(extra)
    with engine.inventory.transaction():
        return engine.execute(RoutingResult.model_validate(payload), state)[0]


FLIGHT = {"origin": "Baku", "destination": "IST", "departure_date": "2026-11-06"}


@pytest.mark.parametrize("extra,expected", [
    ({}, ["F001", "F002", "F013"]),
    ({"max_price_azn": 250}, ["F002", "F013"]),
    ({"min_price_azn": 250}, ["F001"]),
    ({"stops": 0}, ["F001", "F002"]),
    ({"airline": "caspian air"}, ["F001"]),
    ({"departure_time": "14:20"}, ["F002"]),
    ({"departure_time_from": "07:00", "departure_time_to": "08:00"}, ["F001"]),
    ({"passengers": 4}, ["F001", "F013"]),
    ({"sort_by": "price_asc"}, ["F013", "F002", "F001"]),
    ({"sort_by": "price_desc"}, ["F001", "F002", "F013"]),
    ({"sort_by": "departure_asc"}, ["F013", "F001", "F002"]),
    ({"sort_by": "departure_desc"}, ["F002", "F001", "F013"]),
    ({"sort_by": "stops_desc"}, ["F013", "F001", "F002"]),
    ({"sort_by": "airline_asc"}, ["F013", "F002", "F001"]),
    ({"max_price_azn": 1}, []),
])
def test_flight_search_filters_and_sorts(domain_setup, extra, expected):
    engine, state = domain_setup
    answer = run(engine, state, "flights", params={**FLIGHT, **extra})
    assert [row["id"] for row in answer.data["flights"]] == expected
    assert state.flights.last_result_ids == expected
    assert answer.status == ("ok" if expected else "no_results")


def test_flight_details_and_comparison(domain_setup):
    engine, state = domain_setup
    details = run(engine, state, "flights", "details", {"flight_ids": ["F001"]})
    row = details.data["flights"][0]
    assert (row["duration_min"], row["baggage_kg"], row["seats_available"], row["price_azn"]) == (215, 20, 14, 289)
    comparison = run(engine, state, "flights", "compare", {"flight_ids": ["F001", "F013"]})
    assert [row["stops"] for row in comparison.data["flights"]] == [0, 1]
    assert [row["price_azn"] for row in comparison.data["flights"]] == [289, 175]


@pytest.mark.parametrize("params,code", [
    ({"destination": "IST"}, "flight_search"),
    ({**FLIGHT, "departure_time": "evening"}, "invalid_time"),
    ({**FLIGHT, "departure_time_from": "20:00", "departure_time_to": "10:00"}, "invalid_range"),
    ({**FLIGHT, "min_price_azn": 500, "max_price_azn": 10}, "invalid_range"),
    ({**FLIGHT, "sort_by": "imaginary"}, "invalid_sort"),
    ({**FLIGHT, "return_date": "2026-11-09"}, "one_way_only"),
])
def test_flight_invalid_or_missing_input(domain_setup, params, code):
    engine, state = domain_setup
    assert run(engine, state, "flights", params=params).code == code


def test_flight_reservation_unique_ids_cumulative_capacity_and_session_ownership(domain_setup):
    engine, state = domain_setup
    first = run(engine, state, "flights", "reserve", {"flight_ids": ["F002"], "passengers": 2})
    other = SessionState()
    second = run(engine, other, "flights", "reserve", {"flight_ids": ["F002"], "passengers": 1})
    assert first.data["reservation"]["total_azn"] == "490.00"
    assert first.data["reservation"]["confirmation_id"] != second.data["reservation"]["confirmation_id"]
    assert first.data["reservation"]["mock"] is True
    assert first.data["reservation"]["paid"] is False
    denied = run(engine, other, "flights", "reserve", {"flight_ids": ["F002"], "passengers": 1})
    assert denied.code == "insufficient_seats"
    assert denied.data["available"] == 0
    assert len(state.flights.reservations) == len(other.flights.reservations) == 1
    assert engine.services["flights"].repo.get_by_id("F002").seats_available == 3
    assert run(engine, state, "flights", "availability", {"flight_ids": ["F002"]}).data["flights"][0]["seats_available"] == 0


def test_pending_quantity_resolves_once(domain_setup):
    engine, state = domain_setup
    pending = run(engine, state, "flights", "reserve", {"flight_ids": ["F002"]})
    assert pending.code == "flight_reserve"
    assert state.flights.reservations == []
    completed = run(engine, state, "flights", "follow_up", {"passengers": 2})
    assert completed.code == "reserved"
    run(engine, state, "flights", "follow_up", {"reference": "it"})
    assert len(state.flights.reservations) == 1


@pytest.mark.parametrize("params,expected", [
    ({"query": "laptops"}, ["P003", "P004"]),
    ({"query": "headphones", "max_price_azn": 100}, ["P001"]),
    ({"query": "qulaqlıq"}, ["P001"]),
    ({"query": "ноутбук"}, ["P003", "P004"]),
    ({"category": "audio", "brand": "Sonivo", "color": "black"}, ["P001", "P008"]),
    ({"min_price_azn": 1000, "max_price_azn": 1500}, ["P004"]),
    ({"in_stock": False}, ["P002"]),
    ({"query": "laptop", "sort_by": "price_asc"}, ["P004", "P003"]),
    ({"query": "missing product"}, []),
])
def test_shopping_search(domain_setup, params, expected):
    engine, state = domain_setup
    assert [row["id"] for row in run(engine, state, "shopping", params=params).data["products"]] == expected


def test_product_details_comparison_and_stock(domain_setup):
    engine, state = domain_setup
    assert run(engine, state, "shopping", "availability", {"product_ids": ["P002"]}).data["products"][0]["stock"] == 0
    compared = run(engine, state, "shopping", "compare", {"product_ids": ["P003", "P004"]})
    assert [row["price_azn"] for row in compared.data["products"]] == [1899, 1249]
    assert "16 GB RAM" in compared.data["products"][0]["description"]


def test_exact_cart_totals_and_removal(domain_setup):
    engine, state = domain_setup
    run(engine, state, "shopping", "cart_add", {"product_ids": ["P001"], "quantity": 3})
    added = run(engine, state, "shopping", "cart_add", {"product_ids": ["P008"], "quantity": 2})
    assert added.data["cart"]["total_azn"] == "418.70"
    assert [line["subtotal_azn"] for line in added.data["cart"]["lines"]] == ["269.70", "149.00"]
    removed = run(engine, state, "shopping", "cart_remove", {"product_ids": ["P001"], "quantity": 1})
    assert removed.data["cart"]["total_azn"] == "328.80"
    run(engine, state, "shopping", "cart_remove", {"product_ids": ["P001"], "quantity": 2})
    assert state.shopping.cart == {"P008": 2}
    assert run(engine, SessionState(), "shopping", "cart_view").data["cart"]["total_azn"] == "0.00"


def test_cart_cumulative_stock_limit_and_invalid_removal(domain_setup):
    engine, state = domain_setup
    assert run(engine, state, "shopping", "cart_add", {"product_ids": ["P002"], "quantity": 1}).code == "insufficient_stock"
    run(engine, state, "shopping", "cart_add", {"product_ids": ["P003"], "quantity": 6})
    assert run(engine, state, "shopping", "cart_add", {"product_ids": ["P003"], "quantity": 2}).code == "insufficient_stock"
    assert run(engine, state, "shopping", "cart_remove", {"product_ids": ["P003"], "quantity": 7}).code == "cart_quantity"
    assert state.shopping.cart == {"P003": 6}
    # Carts do not reserve global inventory or leak between sessions.
    other = SessionState()
    assert run(engine, other, "shopping", "cart_add", {"product_ids": ["P003"], "quantity": 7}).status == "ok"
    assert state.shopping.cart == {"P003": 6}


def test_missing_cart_quantity_pending_and_no_replay(domain_setup):
    engine, state = domain_setup
    assert run(engine, state, "shopping", "cart_add", {"product_ids": ["P001"]}).code == "cart_item"
    assert state.shopping.cart == {}
    assert run(engine, state, "shopping", "follow_up", {"quantity": 2}).data["cart"]["total_azn"] == "179.80"
    run(engine, state, "shopping", "follow_up", {"reference": "it"})
    assert state.shopping.cart == {"P001": 2}
    assert run(engine, state, "shopping", "cart_add", {"product_ids": ["P008"]}).code == "cart_item"


@pytest.mark.parametrize("params,expected", [
    ({"genre": "sci-fi"}, ["M001", "M008"]),
    ({"min_rating": 8.2}, ["M008"]),
    ({"language": "Azerbaijani"}, ["M002", "M007"]),
    ({"date": "2026-11-02"}, ["M001", "M003", "M008"]),
    ({"date": "2026-11-07", "genre": "sci-fi"}, ["M001", "M008"]),
    ({"cinema_name": "Sumgayit", "date": "2026-11-07"}, ["M005"]),
    ({"genre": "sci-fi", "sort_by": "rating_desc"}, ["M008", "M001"]),
    ({"date": "2026-12-31"}, []),
])
def test_cinema_search(domain_setup, params, expected):
    engine, state = domain_setup
    answer = run(engine, state, "cinema", params=params)
    assert [row["id"] for row in answer.data["movies"]] == expected
    assert all(row["movie_id"] in expected for row in answer.data["showtimes"])


def test_cinema_showtimes_prices_sold_out_and_details(domain_setup):
    engine, state = domain_setup
    result = run(engine, state, "cinema", "details", {"movie_ids": ["M008"], "date": "2026-11-02"})
    assert result.data["showtimes"][0]["id"] == "S003"
    assert result.data["showtimes"][0]["seats_available"] == 0
    assert result.data["showtimes"][0]["price_azn"] == 13
    assert any(row["id"] == "C002" for row in result.data["cinemas"])
    denied = run(engine, state, "cinema", "reserve", {"showtime_ids": ["S003"], "tickets": 1})
    assert denied.code == "insufficient_seats"
    assert state.cinema.reservations == []


def test_cinema_reservation_capacity_and_pending(domain_setup):
    engine, state = domain_setup
    pending = run(engine, state, "cinema", "reserve", {"showtime_ids": ["S012"]})
    assert pending.code == "cinema_reserve"
    first = run(engine, state, "cinema", "follow_up", {"tickets": 3})
    assert first.data["reservation"]["total_azn"] == "42.00"
    other = SessionState()
    second = run(engine, other, "cinema", "reserve", {"showtime_ids": ["S012"], "tickets": 2})
    assert first.data["reservation"]["confirmation_id"] != second.data["reservation"]["confirmation_id"]
    assert run(engine, state, "cinema", "reserve", {"showtime_ids": ["S012"], "tickets": 1}).code == "insufficient_seats"
    assert len(state.cinema.reservations) == 1


@pytest.mark.parametrize("domain,params", [
    ("flights", {"flight_ids": ["F999"]}),
    ("shopping", {"product_ids": ["P999"]}),
    ("cinema", {"movie_ids": ["M999"]}),
    ("cinema", {"showtime_ids": ["S999"]}),
])
def test_unknown_ids_are_not_fabricated(domain_setup, domain, params):
    engine, state = domain_setup
    assert run(engine, state, domain, "details", params).code == "unknown_id"


def test_ordinal_cheapest_and_invalid_followups(domain_setup):
    engine, state = domain_setup
    run(engine, state, "shopping", params={"query": "laptops"})
    second = run(engine, state, "shopping", "availability", {"reference": "the second one"})
    assert second.data["products"][0]["id"] == "P004"
    invalid = run(engine, state, "shopping", "details", {"result_positions": [3]})
    assert invalid.code == "invalid_selection"
    run(engine, state, "flights", params=FLIGHT)
    cheap = run(engine, state, "flights", "details", {"reference": "the cheaper one"})
    assert cheap.data["flights"][0]["id"] == "F013"
    assert cheap.data["flights"][0]["stops"] == 1


def test_mixed_and_multiple_same_domain_operations(domain_setup):
    engine, state = domain_setup
    payload = {"category": "mixed", "domains": ["flights", "shopping", "cinema"], "intents": [
        {"domain": "flights", "intent": "search", "parameters": FLIGHT},
        {"domain": "shopping", "intent": "cart_add", "parameters": {"product_ids": ["P001"], "quantity": 2}},
        {"domain": "shopping", "intent": "cart_add", "parameters": {"product_ids": ["P008"], "quantity": 1}},
        {"domain": "cinema", "intent": "search", "parameters": {"date": "2026-11-02"}},
    ]}
    outcomes = engine.execute(RoutingResult.model_validate(payload), state)
    assert len(outcomes) == 4
    assert state.shopping.cart == {"P001": 2, "P008": 1}
    assert outcomes[2].data["cart"]["total_azn"] == "254.30"
    assert state.last_active_domain is None


def test_concurrent_sessions_cannot_overbook(domain_setup):
    engine, _ = domain_setup
    def book(_):
        return run(engine, SessionState(), "flights", "reserve", {"flight_ids": ["F002"], "passengers": 2})
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(book, range(2)))
    assert sorted(answer.code for answer in answers) == ["insufficient_seats", "reserved"]
    assert engine.inventory.available(engine.services["flights"].repo.get_by_id("F002")) == 1


def test_inventory_rollback_on_unexpected_error(domain_setup):
    engine, state = domain_setup
    with pytest.raises(RuntimeError):
        with engine.inventory.transaction():
            run(engine, state, "flights", "reserve", {"flight_ids": ["F002"], "passengers": 2})
            raise RuntimeError("abort")
    assert engine.inventory.available(engine.services["flights"].repo.get_by_id("F002")) == 3


def test_data_failure_does_not_leak_source_error(domain_setup, monkeypatch):
    engine, state = domain_setup
    def broken():
        raise DataSourceError("private server path")
    monkeypatch.setattr(engine.services["shopping"].repo, "list_all", broken)
    outcome = run(engine, state, "shopping")
    assert outcome.code == "data_unavailable"
    assert "private" not in outcome.model_dump_json()


def test_named_product_operations_and_pending_choice(domain_setup):
    engine, state = domain_setup
    answer = run(engine, state, "shopping", "details", {"query": "headphones"})
    assert answer.data["products"][0]["id"] == "P001"
    added = run(engine, state, "shopping", "cart_add", {"query": "headphones", "quantity": 2})
    assert added.data["cart"]["total_azn"] == "179.80"
    choice = run(engine, state, "shopping", "cart_add", {"query": "laptops", "quantity": 1})
    assert choice.code == "cart_item"
    assert [row["id"] for row in choice.data["products"]] == ["P003", "P004"]
    selected = run(engine, state, "shopping", "follow_up", {"result_positions": [2]})
    assert selected.data["cart"]["total_azn"] == "1428.80"


def test_movie_title_details_and_cinemas_are_grounded(domain_setup):
    engine, state = domain_setup
    answer = run(engine, state, "cinema", "details", {"movie_title": "Deep Signal"})
    assert [row["id"] for row in answer.data["movies"]] == ["M008"]
    assert {row["id"] for row in answer.data["cinemas"]} == {"C001", "C002"}
    assert {row["id"] for row in answer.data["showtimes"]} == {"S003", "S010", "S011"}
    no_match = run(engine, state, "cinema", "details", {"movie_title": "Invented Movie"})
    assert no_match.status == "no_results"
    assert no_match.data["cinemas"] == []


def test_cinema_pending_reservation_can_be_narrowed_by_time(domain_setup):
    engine, state = domain_setup
    pending = run(engine, state, "cinema", "reserve", {"genre": "sci-fi", "date": "2026-11-07", "tickets": 2})
    assert pending.code == "cinema_reserve"
    completed = run(engine, state, "cinema", "follow_up", {"time": "15:00"})
    assert completed.data["reservation"]["record_id"] == "S011"


def test_explicit_movie_id_ignores_stale_genre_filter(domain_setup):
    engine, state = domain_setup
    run(engine, state, "cinema", params={"genre": "comedy"})
    details = run(engine, state, "cinema", "details", {"movie_ids": ["M008"]})
    assert details.data["movies"][0]["id"] == "M008"


def test_flight_number_details_and_conflicting_selections(domain_setup):
    engine, state = domain_setup
    assert run(engine, state, "flights", "details", {"flight_number": "CA101"}).data["flights"][0]["id"] == "F001"
    assert run(engine, state, "flights", "reserve", {"flight_ids": ["F001"], "passengers": 1,
                                                    "departure_date": "2026-11-07"}).code == "selection_mismatch"
    assert state.flights.reservations == []
    assert run(engine, state, "cinema", "reserve", {"showtime_ids": ["S001"], "tickets": 1,
                                                    "date": "2026-11-07"}).code == "selection_mismatch"
    assert state.cinema.reservations == []


def test_resuming_selection_and_reset_preserve_cart_and_reservations(domain_setup):
    engine, state = domain_setup
    run(engine, state, "shopping", "cart_add", {"product_ids": ["P001"], "quantity": 1})
    run(engine, state, "flights", "reserve", {"flight_ids": ["F001"], "passengers": 1})
    resumed = run(engine, state, "shopping", "resume", {"reference": "back to headphones"})
    assert resumed.data["products"][0]["id"] == "P001"
    assert state.shopping.selected_ids == ["P001"]
    run(engine, state, "shopping", params={"query": "laptops"}, reset_context=True)
    assert state.shopping.cart == {"P001": 1}
    run(engine, state, "flights", params={**FLIGHT}, reset_context=True)
    assert len(state.flights.reservations) == 1


def test_unclear_date_never_reserves_using_stale_context(domain_setup):
    engine, state = domain_setup
    answer = run(engine, state, "flights", "reserve", {"flight_ids": ["F001"], "passengers": 1,
                                                        "departure_date_text": "sometime"})
    assert answer.code == "date"
    assert not state.flights.reservations


@pytest.mark.parametrize("domain,action,params", [
    ("flights", "reserve", {"flight_ids": ["F013"], "passengers": 1, "stops": 0}),
    ("flights", "reserve", {"flight_ids": ["F001"], "passengers": 1, "max_price_azn": 100}),
    ("shopping", "cart_add", {"product_ids": ["P001"], "quantity": 1, "max_price_azn": 50}),
    ("cinema", "reserve", {"showtime_ids": ["S001"], "tickets": 1, "movie_title": "Deep Signal"}),
])
def test_selected_records_must_satisfy_explicit_constraints(domain_setup, domain, action, params):
    engine, state = domain_setup
    answer = run(engine, state, domain, action, params)
    assert answer.code == "selection_mismatch"
    assert not state.flights.reservations
    assert not state.cinema.reservations
    assert not state.shopping.cart
