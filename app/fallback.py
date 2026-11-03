"""Conservative AZ/EN/RU outage routing. No catalogue facts or actions are generated.

Only explicit supported entities/constraints are extracted. Ambiguity is returned
to the user instead of guessing. Domain services remain the authority for all data.
"""

import re
import logging
import time
from threading import Lock

from pydantic import ValidationError

from app.dates import date_expression, resolve_date
from app.cinema_queries import normalize_cinema_discovery
from app.routing import GeminiRouter, InvalidRouterResponse, RouterUnavailable, normalize_request_queries, product_search_query
from app.query_context import PRODUCTS, domain_clauses
from app.schemas import RoutingResult
from app.shopping_currency import normalize_shopping_money
from app.languages import detect_language, normalize_text

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
NUMBER = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
logger = logging.getLogger(__name__)


def number(value):
    return WORDS[value] if value in WORDS else int(value)


class LocalRouter:
    def __init__(self, repositories, reference_date=None):
        self.repos = repositories
        self.reference_date = reference_date

    def domains(self, text):
        found = []
        if re.search(r"\b(flights?|airlines?|aviasales|baggage|passengers?|f\d{3}|av-[a-f0-9]{16})\b", text):
            found.append("flights")
        if re.search(r"\b(shopping|birmarket|ebay|buywhere|bw-[a-z0-9_-]+|products?|cart|stock|p\d{3})\b", text) or any(word in text for word in PRODUCTS):
            found.append("shopping")
        if re.search(r"\b(cinema\w*|tmdb-\d+|cp-[\w-]+|movies?|films?|showtimes?|tickets?|playing|[msc]\d{3}|sci-fi|comedy|horror)\b", text):
            found.append("cinema")
        if any(movie.title.casefold() in text for movie in self.repos.movies.list_all()) and "cinema" not in found:
            found.append("cinema")
        return found

    def route(self, message, state):
        language = detect_language(message, state.language)
        semantic = normalize_text(message)
        try:
            result = normalize_request_queries(semantic, self._route(semantic, state), state,
                                               self.reference_date() if self.reference_date else None)
            result.language = language
            return normalize_cinema_discovery(semantic, result)
        except (ValidationError, ValueError):
            # An unsupported local extraction must never become an HTTP 500.
            return RoutingResult(category="ambiguous", source="local", language=language)

    def _route(self, message, state):
        text = message.casefold().strip()
        language = "ru" if re.search(r"[А-Яа-яЁё]", text) else "az" if re.search(r"[əğıİşç]", text) else "en"
        def unresolved(category="ambiguous"):
            return RoutingResult(category=category, source="local", language=language)
        # Do not accidentally execute a negated or conditional mutation.
        if re.search(r"\b(don't|do not|never|cancel|if|unless|except|instead|without|not)\b", text):
            return unresolved()
        domains = self.domains(text)
        if len(domains) > 1:
            parts = domain_clauses(text, self.domains)
            if len(parts) < 2 or any(len(ds) != 1 for _, ds in parts):
                return unresolved()
            intents = [self.extract(clause, ds[0], state) for clause, ds in parts]
            if any(intent is None for intent in intents):
                return unresolved()
            return RoutingResult.model_validate({"category": "mixed", "source": "local", "language": language,
                                                  "domains": list(dict.fromkeys(i["domain"] for i in intents)), "intents": intents})
        contextual = False
        if not domains:
            if re.search(r"\b(weather|president|politics|recipe|code|poem|football)\b", text):
                return unresolved("out_of_scope")
            supported = re.search(r"\b(cheaper|cheapest|first|second|third|tomorrow|today|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|direct|compare|book|reserve|add|remove|under|details|available|any brand)\b", text)
            supported = supported or re.fullmatch(NUMBER + r"(?:\s+(?:please|seats|units))?\.?", text)
            supported = supported or re.fullmatch(r"(?:from )?(?:baku|istanbul|dubai|moscow|tbilisi|tashkent|gyd|ist|dxb|svo|tbs|tas)\.?", text)
            if not state.last_active_domain or not supported:
                return unresolved()
            domains, contextual = [state.last_active_domain.value], True
        domain = domains[0]
        contextual = contextual or bool(re.search(r"\b(back to|return to)\b", text))
        contextual = contextual or bool(re.search(r"\b(?:first|second|third|fourth|cheaper|cheapest|sci-fi) one\b", text))
        if contextual and getattr(state, domain).intent is None:
            contextual = False
        intent = self.extract(text, domain, state)
        if intent is None:
            return unresolved()
        contextual = contextual or intent["intent"] == "follow_up"
        return RoutingResult.model_validate({"category": "follow_up" if contextual else domain, "source": "local",
                                              "language": language, "domains": [domain], "intents": [intent]})

    def extract(self, text, domain, state):
        p, action = {}, "search"
        clear_parameters = []
        ctx = getattr(state, domain)
        ids = re.findall(r"\b([fpmsc]\d{3})\b", text)
        id_fields = {"f": "flight_ids", "p": "product_ids", "m": "movie_ids", "s": "showtime_ids", "c": "cinema_ids"}
        for prefix, field in id_fields.items():
            values = [item.upper() for item in ids if item.startswith(prefix)]
            if values:
                p[field] = values
        for pattern, field in ((r"\bav-[a-f0-9]{16}\b", "flight_ids"),
                               (r"\btmdb-\d+\b", "movie_ids"),
                               (r"\bcp-[\w-]+\b", "movie_ids"),
                               (r"\bbw-[a-z0-9_-]+\b", "product_ids"),
                               (r"\bebay-v1\|\d+\|\d+\b", "product_ids")):
            matches = re.findall(pattern, text)
            if matches:
                p[field] = [value.replace("av-", "AV-").replace("tmdb-", "TMDB-").replace("cp-", "CP-").replace("ebay-", "EBAY-").replace("bw-", "BW-", 1) for value in matches]
                ids.extend(matches)
        if ids:
            action = "details"
        if re.search(r"\b(compare|comparison)\b", text):
            action = "compare"
        elif domain == "shopping" and "cart" in text and not re.search(r"\b(add|remove)\b", text):
            action = "cart_view"
        elif re.search(r"\badd\b", text):
            if domain != "shopping":
                return None
            action = "cart_add"
        elif re.search(r"\bremove\b", text):
            if domain != "shopping":
                return None
            action = "cart_remove"
        elif re.search(r"\b(book|reserve|reservation)\b", text):
            if domain == "shopping":
                return None
            action = "reserve"
        elif re.search(r"\b(stock|available|availability|seats)\b", text):
            action = "availability"
        elif re.search(r"\b(details|tell me about)\b", text):
            action = "details"
        if re.search(r"\b(back to|return to)\b", text) and action == "search":
            action = "resume"
        if action in {"reserve", "cart_add", "cart_remove"}:
            # Outage mode only executes a small, fully understood action grammar.
            # Do not drop an unknown qualifier and accidentally change its meaning.
            action_words = re.findall(r"\b(add|remove|book|reserve)\b", text)
            if len(action_words) != 1:
                return None
            action_text = re.sub(r"\b(?:av-[a-f0-9]{16}|tmdb-\d+|cp-[\w-]+|bw-[a-z0-9_-]+|ebay-v1\|\d+\|\d+)\b", " ", text)
            remainder = re.sub(r"\b[fpmsc]\d{3}\b", " ", action_text)
            quantity_text = re.sub(r"\b(?:first|second|third|fourth|cheaper|cheapest) one\b", " ", remainder)
            if len(re.findall(r"\b" + NUMBER + r"\b", quantity_text)) > 1:
                return None
            for term in PRODUCTS:
                remainder = re.sub(r"\b" + re.escape(term) + r"\b", " ", remainder)
            allowed = r"add|remove|book|reserve|flight|flights|product|products|showtime|showtimes|movie|movies|ticket|tickets|passenger|passengers|seat|seats|unit|units|of|the|a|an|for|to|from|my|cart|please|it|first|second|third|fourth|one|option|cheaper|cheapest|two|three|four|five|six|seven|eight|nine|ten|\d+"
            remainder = re.sub(r"\b(?:" + allowed + r")\b", " ", remainder)
            if remainder.strip(" .!?") or re.search(r"\d[.,]\d|[-+]\d", action_text):
                return None
        quantity = re.search(NUMBER + r"\s+(?:passengers?|seats?|tickets?|units?|of\b)", text)
        if quantity is None:
            quantity = re.search(r"\b(?:add|remove|book|reserve)\s+" + NUMBER + r"\b", text)
        if ctx.pending and re.fullmatch(NUMBER + r"(?:\s+please)?\.?", text):
            quantity = re.match(NUMBER, text)
            action = "follow_up"
        if ctx.pending and quantity and action in {"search", "availability"}:
            action = "follow_up"
        if quantity:
            value = number(quantity[1])
            if value <= 0:
                return None
            p[{"flights": "passengers", "shopping": "quantity", "cinema": "tickets"}[domain]] = value
        for word, position in (("first", 1), ("second", 2), ("third", 3), ("fourth", 4)):
            if re.search(r"\b" + word + r"\s+(?:one|option|flight|product|movie|showtime)\b", text):
                p.setdefault("result_positions", []).append(position)
        if re.search(r"\b(cheaper|cheapest) one\b", text):
            p["reference"] = "the cheaper one"
        elif re.search(r"\b(book|reserve|add|remove) it\b", text):
            p["reference"] = "it"
        if p.get("result_positions") or p.get("reference"):
            if action == "search":
                action = "details"
        maximum = re.search(r"\b(?:under|below|less than|up to|max(?:imum)?)\s+(\d+(?:\.\d+)?)", text)
        if maximum:
            p["max_price_azn"] = float(maximum[1])
        minimum = re.search(r"\b(?:over|above|at least|min(?:imum)?)\s+(\d+(?:\.\d+)?)", text)
        if minimum and domain != "cinema":
            p["min_price_azn"] = float(minimum[1])
        if "cheapest first" in text or "price ascending" in text:
            p["sort_by"] = "price_asc"
        elif "most expensive first" in text or "price descending" in text:
            p["sort_by"] = "price_desc"
        if p.get("sort_by") and action == "search" and ctx.intent:
            action = "sort"
        expression = date_expression(text)
        if expression and domain != "shopping":
            resolved = resolve_date(expression, self.reference_date() if self.reference_date else None)
            if resolved is None:
                return None
            field = "departure_date" if domain == "flights" else "date"
            p[field], p[field + "_text"] = resolved.isoformat(), expression
        if domain == "flights":
            currency = re.search(r"\b(azn|usd|eur|rub|gbp|try|aed)\b", text)
            if currency:
                p["currency"] = currency[1].upper()
            origin = re.search(r"\bfrom\s+([a-z]+)", text)
            destination = re.search(r"\bto\s+(?!flights\b)([a-z]+)", text)
            if origin:
                p["origin"] = origin[1]
            if destination:
                p["destination"] = destination[1]
            if not origin and not destination and re.fullmatch(r"(?:baku|istanbul|dubai|moscow|tbilisi|tashkent|gyd|ist|dxb|svo|tbs|tas)\.?", text):
                if not ctx.parameters.origin:
                    p["origin"] = text.rstrip(".")
                elif not ctx.parameters.destination:
                    p["destination"] = text.rstrip(".")
            if "direct" in text or "nonstop" in text:
                p["stops"] = 0
            if "direct flights" in text:
                action, p["stops"] = "search", 0
            for row in self.repos.flights.list_all():
                if row.airline.casefold() in text:
                    p["airline"] = row.airline
                if re.search(r"\b" + row.flight_number.casefold() + r"\b", text):
                    p["flight_number"] = row.flight_number
        elif domain == "shopping":
            p, clear_parameters = normalize_shopping_money(text, p)
            if "any brand" in text:
                clear_parameters.append("brand")
            explicit_query = product_search_query(text) if action in {"search", "sort"} else None
            for term in PRODUCTS:
                if term in text:
                    p["query"] = term
                    break
            for row in self.repos.products.list_all():
                for field in ("category", "brand", "color"):
                    value = getattr(row, field)
                    if re.search(r"\b" + re.escape(value.casefold()) + r"\b", text):
                        p[field] = value
            if explicit_query:
                for field in ("category", "brand", "color"):
                    if p.get(field):
                        explicit_query = re.sub(r"\b" + re.escape(p[field].casefold()) + r"\b", "", explicit_query)
                p["query"] = explicit_query.strip() or None
            elif explicit_query == "":
                p = {}
        else:
            screening = re.search(r"\bin\s+(english|russian|azerbaijani)\b", text, re.I)
            if screening:
                p["language"] = screening[1].title()
            quoted = re.search(r'["“]([^"”]+)["”]', text)
            if quoted:
                p["movie_title"] = quoted[1]
            for movie in self.repos.movies.list_all():
                if movie.title.casefold() in text:
                    p["movie_title"] = movie.title
                for genre in movie.genre:
                    if genre in text:
                        p["genre"] = genre
                if movie.language.casefold() in text:
                    p["language"] = movie.language
            if "sci-fi one" in text:
                p["reference"] = "the sci-fi one"
            for cinema in self.repos.cinemas.list_all():
                if cinema.name.casefold() in text:
                    p["cinema_name"] = cinema.name
            at_time = re.search(r"\b([0-2]\d:[0-5]\d)\b", text)
            if at_time:
                p["time"] = at_time[1]
            rating = re.search(r"\brat(?:ing|ed)\s+(?:above|over|at least)?\s*(\d+(?:\.\d+)?)", text)
            if rating:
                p["min_rating"] = float(rating[1])
        reset = bool(re.search(r"\b(new search|start over)\b", text))
        if domain == "shopping" and explicit_query == "":
            reset = True
        # A newly named shopping query should not inherit an unrelated prior brand/budget.
        if action == "search" and p.get("query") and ctx.parameters.query and p["query"] != ctx.parameters.query:
            reset = True
        return {"domain": domain, "intent": action, "parameters": p, "reset_context": reset,
                "clear_parameters": clear_parameters}


class ResilientRouter:
    def __init__(self, settings, repositories):
        if settings.routing_mode not in {"auto", "offline", "strict"}:
            raise ValueError("SUPERCHAT_ROUTING_MODE must be auto, offline, or strict")
        self.settings, self.primary, self.local = settings, GeminiRouter(settings), LocalRouter(repositories, settings.reference_date)
        self._unavailable_until = 0.0
        self._lock = Lock()
        if settings.routing_mode == "offline":
            logger.warning("gemini_routing_disabled reason=offline_mode")
        elif not settings.api_key:
            logger.warning("gemini_routing_disabled reason=missing_api_key")

    def status(self):
        if self.settings.routing_mode == "offline":
            return "offline"
        if not self.settings.api_key:
            return "missing_key"
        with self._lock:
            return "cooldown" if time.monotonic() < self._unavailable_until else "ready"

    def route(self, message, state):
        if self.settings.routing_mode == "strict":
            return self.primary.route(message, state)
        with self._lock:
            unavailable = time.monotonic() < self._unavailable_until
        if self.settings.routing_mode == "offline" or not self.settings.api_key or unavailable:
            return self.local.route(message, state)
        try:
            return self.primary.route(message, state)
        except (RouterUnavailable, InvalidRouterResponse):
            logger.warning("gemini_routing_fallback reason=primary_failure cooldown_seconds=60")
            with self._lock:
                self._unavailable_until = time.monotonic() + 60
            return self.local.route(message, state)
