"""Scope deterministic extraction to the domain clauses in the current message."""

import re
from app.languages import normalize_text

PRODUCTS = ("headphones", "earbuds", "laptops", "laptop", "smartphone", "phone", "smartwatch", "speaker",
            "running shoes", "backpack", "coffee machine", "board game", "coffee maker", "vacuum cleaner",
            "keyboard", "monitor", "tablet", "boots", "toys", "desk chair")


def explicit_domains(text):
    text = normalize_text(text)
    found = []
    if re.search(r"\b(flights?|airlines?|aviasales|baggage|passengers?|f\d{3}|av-[a-f0-9]{16})\b", text):
        found.append("flights")
    if re.search(r"\b(shopping|birmarket|ebay|buywhere|bw-[a-z0-9_-]+|products?|cart|stock|p\d{3})\b", text) or any(word in text for word in PRODUCTS):
        found.append("shopping")
    if re.search(r"\b(cinema\w*|tmdb-\d+|cp-[\w-]+|movies?|films?|showtimes?|tickets?|playing|[msc]\d{3}|sci-fi|comedy|horror)\b", text):
        found.append("cinema")
    return found


def domain_clauses(message, identify=explicit_domains):
    """Keep 'and under $100' with its subject while separating explicit domains."""
    message = normalize_text(message)
    parts = []
    for clause in re.split(r"\s+(?:and|also|plus)\s+|\s*;\s*", message):
        domains = identify(clause.casefold())
        if not domains and parts:
            previous, previous_domains = parts[-1]
            parts[-1] = (previous + " and " + clause, previous_domains)
        else:
            parts.append((clause, domains))
    return parts


def intent_messages(message, result):
    if len(result.domains) == 1 and len(result.intents) == 1:
        return [(result.intents[0], message)]
    parts = domain_clauses(message)
    scoped = []
    for intent in result.intents:
        candidates = [text for text, domains in parts if domains == [intent.domain]]
        if len(candidates) == 1 and sum(i.domain == intent.domain for i in result.intents) == 1:
            scoped.append((intent, candidates[0]))
    return scoped
