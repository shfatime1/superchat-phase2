"""Shared validation, reference resolution, money, and mock seat inventory."""

import re
from contextlib import contextmanager
from decimal import Decimal
from threading import RLock

from app.domain_models import DomainResult, Reservation


class DomainIssue(Exception):
    def __init__(self, code, *, missing=(), data=None, status="clarification"):
        self.code, self.missing, self.data, self.status = code, list(missing), data or {}, status


def money(value):
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):.2f}"


def total(price, quantity):
    return money(Decimal(str(price)) * quantity)


def same(left, right):
    return left.casefold() == right.casefold()


def price_range(parameters):
    low = getattr(parameters, "min_price_azn", None)
    high = parameters.max_price_azn
    if low is not None and high is not None and low > high:
        raise DomainIssue("invalid_range", status="error")


def by_ids(repo, ids):
    ids = list(dict.fromkeys(ids))
    rows = [repo.get_by_id(item) for item in ids]
    if any(row is None for row in rows):
        raise DomainIssue("unknown_id", status="error")
    return rows


def resolve_ids(repo, explicit, positions, reference, last_ids, selected_ids):
    """Never turn an unresolved pronoun into an arbitrary first result."""
    if explicit is not None:
        by_ids(repo, explicit)
        return list(dict.fromkeys(explicit))
    if positions is not None:
        if not positions or any(type(i) is not int or i < 1 or i > len(last_ids) for i in positions):
            raise DomainIssue("invalid_selection")
        return list(dict.fromkeys(last_ids[i - 1] for i in positions))
    if reference:
        text = reference.casefold().strip()
        ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                    "1st": 1, "2nd": 2, "3rd": 3}
        found = [n for word, n in ordinals.items() if re.search(r"\b" + word + r"\b", text)]
        if found:
            return resolve_ids(repo, None, found, None, last_ids, selected_ids)
        rows = by_ids(repo, last_ids)
        named = []
        for row in rows:
            names = [row.id, getattr(row, "title", ""), getattr(row, "flight_number", "")]
            if hasattr(row, "name") and hasattr(row.name, "model_dump"):
                names.extend(row.name.model_dump().values())
            if any(name and name.casefold() in text for name in names):
                named.append(row.id)
        if named:
            return named
        if "cheap" in text or "expensive" in text:
            priced = [row for row in rows if hasattr(row, "price_azn")]
            if not priced:
                raise DomainIssue("choose_item")
            value = (max if "expensive" in text else min)(row.price_azn for row in priced)
            return [row.id for row in priced if row.price_azn == value]
        if text in {"both", "all", "all of them", "both of them"}:
            return last_ids.copy()
        # Genre references are evaluated against the actual displayed film list.
        matching = [row.id for row in rows if any(g.casefold() in text for g in getattr(row, "genre", []))]
        if matching:
            return matching
        if text in {"it", "that", "that one", "this one", "the one", "them"}:
            return selected_ids.copy() or (last_ids.copy() if len(last_ids) == 1 else [])
        raise DomainIssue("choose_item")
    return selected_ids.copy() or (last_ids.copy() if len(last_ids) == 1 else [])


def result(domain, operation, key, rows):
    return DomainResult(domain=domain, operation=operation,
                        status="ok" if rows else "no_results",
                        code="results" if rows else "no_results",
                        data={key: [row.model_dump(mode="json") for row in rows]})


class SeatInventory:
    """Global per-app remaining seats, with rollback and a lock across a turn."""
    def __init__(self):
        self._used: dict[str, int] = {}
        self._lock = RLock()

    @contextmanager
    def transaction(self):
        with self._lock:
            before = self._used.copy()
            try:
                yield self
            except BaseException:
                self._used = before
                raise

    def available(self, row):
        with self._lock:
            return max(0, row.seats_available - self._used.get(row.id, 0))

    def view(self, row):
        copied = row.model_copy(deep=True)
        copied.seats_available = self.available(row)
        return copied

    def reserve(self, row, quantity):
        with self._lock:
            if type(quantity) is not int or quantity <= 0:
                raise DomainIssue("quantity", missing=["quantity"])
            available = self.available(row)
            if quantity > available:
                raise DomainIssue("insufficient_seats", status="error", data={"available": available})
            booking = Reservation(record_id=row.id, quantity=quantity,
                                  unit_price_azn=money(row.price_azn), total_azn=total(row.price_azn, quantity))
            self._used[row.id] = self._used.get(row.id, 0) + quantity
            return booking
