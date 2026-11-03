import hashlib
import json
from datetime import date

import pytest

from app.config import PROJECT_ROOT
from app.records import Flight
from app.repositories import (CinemaRepository, DataSourceError, FlightRepository,
                              JsonRepository, MovieRepository, ProductRepository,
                              QueryFilter, Repositories, ShowtimeRepository)

DATA = PROJECT_ROOT / "data"


@pytest.mark.parametrize("repository,count,first_id", [
    (FlightRepository, 17, "F001"), (ProductRepository, 12, "P001"),
    (MovieRepository, 8, "M001"), (CinemaRepository, 3, "C001"),
    (ShowtimeRepository, 16, "S001"),
])
def test_official_json_loading(repository, count, first_id):
    repo = repository(DATA)
    assert len(repo.list_all()) == count
    assert repo.get_by_id(first_id).id == first_id
    assert repo.get_by_id("missing") is None


def test_official_files_unchanged():
    original = {
        "cinemas.json": "a13cb662ed85617c26ba2ace94b984c8c209ebab64e457547530b3242fbfc5ca",
        "flights.json": "528eba22d7e7d72aca0c947dd8c882ae7eafff34db4488052656ccf6aa2850d0",
        "movies.json": "7ba4a3c1e0bb9995c3780e0a14eb1faeee4bd425bd77fce5d1d5d4e5d6f56c89",
        "products.json": "0b171f3ca0d7d8151cdca7eccbdb2c44514f95bf943216e5bb2c867a6f0efe61",
        "showtimes.json": "c394092f974821dd7cd4aa60324abad10f6e06aede8f79a9174787027e9854aa",
    }
    for name, expected in original.items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == expected


def test_query_nested_fields_ranges_lists_and_dates():
    repos = Repositories.from_json(DATA)
    assert {f.id for f in repos.flights.query([
        QueryFilter("origin.city", "baku"), QueryFilter("destination.code", "IST"),
        QueryFilter("price_azn", 250, "lte"),
    ])} == {"F002", "F013"}
    assert {m.id for m in repos.movies.query([QueryFilter("genre", "sci-fi", "contains")])} == {"M001", "M008"}
    assert {s.id for s in repos.showtimes.query([QueryFilter("date", date(2026, 11, 2))])} == {"S001", "S002", "S003"}
    assert repos.cinemas.query([QueryFilter("district", "sumgayit")])[0].id == "C003"
    assert repos.products.query([QueryFilter("name.en", "headphones", "contains")])[0].id == "P001"


def test_native_names_and_defensive_copies():
    repo = ProductRepository(DATA)
    item = repo.get_by_id("P001")
    assert item.name.az == "Simsiz qulaqlıq"
    assert item.name.ru == "Беспроводные наушники"
    item.name.en = "Changed"
    repo.list_all()[0].stock = -1
    repo.query()[0].stock = -1
    assert repo.get_by_id("P001").name.en == "Wireless Headphones"
    assert repo.get_by_id("P001").stock == 23


@pytest.mark.parametrize("content", ["broken", "{}", '[{"id":"F001"}]'])
def test_bad_data(content, tmp_path):
    path = tmp_path / "flights.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DataSourceError):
        JsonRepository(path, Flight)


def test_duplicate_ids_and_missing_source(tmp_path):
    row = json.loads((DATA / "flights.json").read_text())[0]
    path = tmp_path / "flights.json"
    path.write_text(json.dumps([row, row]))
    with pytest.raises(DataSourceError):
        FlightRepository(tmp_path)
    with pytest.raises(DataSourceError):
        ProductRepository(tmp_path)


def test_broken_showtime_reference(tmp_path):
    for path in DATA.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    showtimes = json.loads((tmp_path / "showtimes.json").read_text())
    showtimes[0]["movie_id"] = "M999"
    (tmp_path / "showtimes.json").write_text(json.dumps(showtimes))
    with pytest.raises(DataSourceError):
        Repositories.from_json(tmp_path)


@pytest.mark.parametrize("condition", [QueryFilter("bad", "x"),
    QueryFilter("origin.bad", "x"), QueryFilter("id.bad", "x"),
    QueryFilter("id", "x", "bad"), QueryFilter("price_azn", "cheap", "lt")])
def test_invalid_queries(condition):
    with pytest.raises(ValueError):
        FlightRepository(DATA).query([condition])
