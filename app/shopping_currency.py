"""Normalize stated Shopping currencies without converting monetary amounts."""

import re

SYMBOLS = {"$": "USD", "₼": "AZN", "€": "EUR"}
CODES = r"azn|usd|eur|gbp|rub|try|aed|sgd|vnd|thb|myr"
BUDGET_WORDS = r"under|below|less than|up to|max(?:imum)?|(?:with\s+)?(?:a\s+)?budget(?:\s+(?:of|up to))?"


def shopping_price_bounds(message):
    prefix = r"(?:(?:[$₼€]|\b(?:" + CODES + r")\b)\s*)?"
    bounds = {}
    for kind, words in (("min", r"over|above|at least|min(?:imum)?"), ("max", BUDGET_WORDS)):
        bound = re.search(r"\b(?:" + words + r")\s+" + prefix + r"(\d+(?:\.\d+)?)", message, re.IGNORECASE)
        if bound:
            bounds[kind] = float(bound[1])
    suffix_budget = re.search(prefix + r"(\d+(?:\.\d+)?)\s*(?:(?:" + CODES + r"|[$₼€])\s*)?budget\b", message, re.IGNORECASE)
    if suffix_budget and "max" not in bounds:
        bounds["max"] = float(suffix_budget[1])
    return bounds


def normalize_shopping_money(message, parameters):
    """Explicit ISO codes take precedence over symbols and extracted defaults."""
    values = dict(parameters)
    code = re.search(r"\b(" + CODES + r")\b", message, re.IGNORECASE)
    symbols = {currency for symbol, currency in SYMBOLS.items() if symbol in message}
    if code:
        currency = code[1].upper()
    elif len(symbols) == 1:
        currency = next(iter(symbols))
    else:
        currency = values.get("currency")
    bounds = shopping_price_bounds(message)
    if not currency:
        for kind, amount in bounds.items():
            values[f"{kind}_price_azn"] = amount
        return values, []
    currency = currency.upper()
    values["currency"] = currency
    for kind in ("min", "max"):
        native, azn = f"{kind}_price", f"{kind}_price_azn"
        target, other = (azn, native) if currency == "AZN" else (native, azn)
        if kind in bounds:
            values[target] = bounds[kind]
        elif values.get(target) is None and values.get(other) is not None:
            values[target] = values[other]
        values.pop(other, None)
    # Remove incompatible bounds inherited from a previous turn as well.
    clears = ["min_price", "max_price"] if currency == "AZN" else ["min_price_azn", "max_price_azn"]
    return values, clears
