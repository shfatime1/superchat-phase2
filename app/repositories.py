"""Read-only adapters. Future API adapters implement Repository, not JSON internals."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, Protocol, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from app.records import Cinema, Flight, Movie, Product, Record, Showtime

T = TypeVar("T", bound=Record)


class DataSourceError(RuntimeError):
    """An unavailable or invalid source; callers should not expose its internals."""


@dataclass(frozen=True)
class QueryFilter:
    field: str
    value: object
    operator: Literal["eq", "contains", "lt", "lte", "gt", "gte"] = "eq"


class Repository(Protocol[T]):
    def list_all(self) -> list[T]: ...
    def get_by_id(self, record_id: str) -> T | None: ...
    def query(self, filters: Sequence[QueryFilter] = ()) -> list[T]: ...


class JsonRepository(Generic[T]):
    def __init__(self, path: Path, model: type[T]):
        self._model = model
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("Expected an array")
            self._records = [model.model_validate(row) for row in raw]
            self._by_id = {row.id: row for row in self._records}
            if len(self._by_id) != len(self._records):
                raise ValueError("Duplicate record IDs")
        except (OSError, ValueError, ValidationError) as exc:
            raise DataSourceError(f"Unable to load {path.name}") from exc

    def list_all(self) -> list[T]:
        return [row.model_copy(deep=True) for row in self._records]

    def get_by_id(self, record_id: str) -> T | None:
        row = self._by_id.get(record_id)
        return row.model_copy(deep=True) if row is not None else None

    def query(self, filters: Sequence[QueryFilter] = ()) -> list[T]:
        # Validate paths even for an empty source; typos must not silently match.
        for condition in filters:
            model = self._model
            for part in condition.field.split("."):
                if not isinstance(model, type) or not issubclass(model, BaseModel):
                    raise ValueError(f"Invalid query field: {condition.field}")
                if part not in model.model_fields:
                    raise ValueError(f"Invalid query field: {condition.field}")
                model = model.model_fields[part].annotation
            if condition.operator not in {"eq", "contains", "lt", "lte", "gt", "gte"}:
                raise ValueError("Unsupported query operator")
        return [row.model_copy(deep=True) for row in self._records
                if all(self._matches(row, condition) for condition in filters)]

    @staticmethod
    def _matches(row: T, condition: QueryFilter) -> bool:
        actual = row
        for part in condition.field.split("."):
            actual = getattr(actual, part)
        expected = condition.value
        if isinstance(actual, str) and isinstance(expected, str):
            actual, expected = actual.casefold(), expected.casefold()
        if condition.operator == "eq":
            return actual == expected
        if actual is None:
            return False
        try:
            if condition.operator == "contains":
                if isinstance(actual, list):
                    return any(str(item).casefold() == str(expected).casefold() for item in actual)
                return expected in actual
            if condition.operator == "lt":
                return actual < expected
            if condition.operator == "lte":
                return actual <= expected
            if condition.operator == "gt":
                return actual > expected
            return actual >= expected
        except TypeError as exc:
            raise ValueError(f"Incompatible query value for {condition.field}") from exc


class FlightRepository(JsonRepository[Flight]):
    def __init__(self, data_dir: Path):
        super().__init__(data_dir / "flights.json", Flight)


class ProductRepository(JsonRepository[Product]):
    def __init__(self, data_dir: Path):
        super().__init__(data_dir / "products.json", Product)


class MovieRepository(JsonRepository[Movie]):
    def __init__(self, data_dir: Path):
        super().__init__(data_dir / "movies.json", Movie)


class CinemaRepository(JsonRepository[Cinema]):
    def __init__(self, data_dir: Path):
        super().__init__(data_dir / "cinemas.json", Cinema)


class ShowtimeRepository(JsonRepository[Showtime]):
    def __init__(self, data_dir: Path):
        super().__init__(data_dir / "showtimes.json", Showtime)


@dataclass(frozen=True)
class Repositories:
    flights: Repository[Flight]
    products: Repository[Product]
    movies: Repository[Movie]
    cinemas: Repository[Cinema]
    showtimes: Repository[Showtime]

    @classmethod
    def empty(cls):
        """Routing without fixture-backed catalog facts in provider mode."""
        class EmptyRepository:
            def list_all(self):
                return []

            def get_by_id(self, record_id):
                return None

        return cls(*(EmptyRepository() for _ in range(5)))

    @classmethod
    def from_json(cls, data_dir: Path) -> "Repositories":
        repos = cls(FlightRepository(data_dir), ProductRepository(data_dir),
                    MovieRepository(data_dir), CinemaRepository(data_dir),
                    ShowtimeRepository(data_dir))
        for showtime in repos.showtimes.list_all():
            if (repos.movies.get_by_id(showtime.movie_id) is None
                    or repos.cinemas.get_by_id(showtime.cinema_id) is None):
                raise DataSourceError("Showtime references an unknown movie or cinema")
        return repos
