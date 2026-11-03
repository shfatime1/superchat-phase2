"""Official Travelpayouts Data API; indicative cached fares, never inventory."""

from datetime import datetime, time
from decimal import Decimal
from hashlib import sha256
import json
import re

from pydantic import ValidationError

from app.providers.http import ProviderFailure
from app.providers.models import FlightOffer, Price, Provenance, ProviderResult, unavailable

URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
NOTICE = ("Aviasales cached search prices, not live quotes. Price and availability must be "
          "rechecked on Aviasales. Seats, baggage and cabin are unknown. Prices are per traveler; "
          "passenger availability and group totals are not verified. Results may be incomplete.")


class AviasalesProvider:
    name = "Aviasales / Travelpayouts"

    def __init__(self, http, token=None, currency="AZN", market=None):
        self.http, self.token, self.currency, self.market = http, token, currency, market

    async def resolve_iata(self, value):
        if re.fullmatch(r"[A-Za-z]{3}", value.strip()):
            return value.strip().upper()
        doc = await self.http.get("https://autocomplete.travelpayouts.com/places2",
            params={"term": value, "locale": "en", "types[]": ["city", "airport"]}, ttl=86400)
        if not isinstance(doc.data, list):
            raise ProviderFailure("invalid_response")
        candidates = [r for r in doc.data if isinstance(r, dict) and
            r.get("type") in {"city", "airport"} and re.fullmatch(r"[A-Z]{3}", str(r.get("code", ""))) and
            value.casefold().strip() in {str(r.get("name", "")).casefold(),
                                       str(r.get("city_name", "")).casefold()}]
        cities = [r for r in candidates if r["type"] == "city"]
        codes = {r["code"] for r in cities or candidates}
        if len(codes) != 1:
            raise ProviderFailure("iata_required")
        return codes.pop()

    async def search(self, p):
        if not self.token:
            return unavailable(self.name, URL, "Set TRAVELPAYOUTS_API_TOKEN to enable cached flight prices.", "missing_credentials")
        try:
            if not p.origin or not p.destination or not p.departure_date:
                raise ProviderFailure("flight_search")
            currency = (p.currency or self.currency).upper()
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise ProviderFailure("invalid_currency")
            if (p.min_price_azn is not None or p.max_price_azn is not None) and currency != "AZN":
                raise ProviderFailure("currency_filter_mismatch")
            if p.baggage_kg is not None or p.cabin:
                raise ProviderFailure("unsupported_filter")
            if p.return_date and p.return_date < p.departure_date:
                raise ProviderFailure("invalid_range")
            if p.min_price_azn is not None and p.max_price_azn is not None and p.min_price_azn > p.max_price_azn:
                raise ProviderFailure("invalid_range")
            origin, destination = await self.resolve_iata(p.origin), await self.resolve_iata(p.destination)
            params = {"origin": origin, "destination": destination,
                "departure_at": p.departure_date.isoformat(), "currency": currency.lower(),
                "one_way": str(p.return_date is None).lower(), "direct": str(p.stops == 0).lower(),
                "sorting": "price", "limit": 100, "page": 1}
            if p.return_date:
                params["return_at"] = p.return_date.isoformat()
            if self.market:
                params["market"] = self.market
            doc = await self.http.get(URL, params=params, headers={"X-Access-Token": self.token})
            payload = doc.data
            if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), list):
                raise ProviderFailure("invalid_response")
            actual_currency = str(payload.get("currency", currency)).upper()
            if actual_currency != currency:
                raise ProviderFailure("currency_mismatch")
            rows = []
            exact, start, end = [time.fromisoformat(v) if v else None for v in
                                 (p.departure_time, p.departure_time_from, p.departure_time_to)]
            if start and end and start > end:
                raise ProviderFailure("invalid_range")
            for raw in payload["data"]:
                price = Price(amount=raw["price"], currency=actual_currency)
                departure = datetime.fromisoformat(raw["departure_at"])
                return_at = datetime.fromisoformat(raw["return_at"]) if raw.get("return_at") else None
                # Defend against broad or mismatched upstream results.
                if departure.date() != p.departure_date or (p.return_date and (not return_at or return_at.date() != p.return_date)):
                    continue
                if not p.return_date and return_at:
                    continue
                if origin not in {raw["origin"], raw.get("origin_airport")} or destination not in {raw["destination"], raw.get("destination_airport")}:
                    continue
                if p.stops is not None and raw.get("transfers") != p.stops:
                    continue
                if p.airline and p.airline.casefold() != str(raw.get("airline", "")).casefold():
                    continue
                if p.flight_number and p.flight_number.casefold() not in {
                    str(raw.get("flight_number", "")).casefold(),
                    (str(raw.get("airline", "")) + str(raw.get("flight_number", ""))).casefold()}:
                    continue
                if p.min_price_azn is not None and price.amount < Decimal(str(p.min_price_azn)) or p.max_price_azn is not None and price.amount > Decimal(str(p.max_price_azn)):
                    continue
                dep_time = departure.time()
                if exact and dep_time != exact or start and dep_time < start or end and dep_time > end:
                    continue
                link = raw.get("link")
                booking_url = "https://www.aviasales.com" + link if isinstance(link, str) and link.startswith("/") and not link.startswith("//") else None
                identity = {k: raw.get(k) for k in ("origin", "destination", "origin_airport", "destination_airport", "departure_at", "return_at", "airline", "flight_number", "transfers")}
                rows.append(FlightOffer(id="AV-" + sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16],
                    origin=raw["origin"], destination=raw["destination"], origin_airport=raw.get("origin_airport"),
                    destination_airport=raw.get("destination_airport"), departure_at=departure, return_at=return_at,
                    airline=raw.get("airline"), flight_number=str(raw["flight_number"]) if raw.get("flight_number") is not None else None,
                    stops=raw.get("transfers"), duration_min=raw.get("duration_to") if return_at else raw.get("duration"),
                    price=price, booking_url=booking_url))
            sorts = {"price_asc": (lambda r: r.price.amount, False), "price_desc": (lambda r: r.price.amount, True),
                "stops_asc": (lambda r: r.stops if r.stops is not None else 999, False),
                "stops_desc": (lambda r: r.stops if r.stops is not None else -1, True),
                "departure_asc": (lambda r: r.departure_at.isoformat(), False),
                "departure_desc": (lambda r: r.departure_at.isoformat(), True),
                "airline_asc": (lambda r: r.airline or "", False), "airline_desc": (lambda r: r.airline or "", True)}
            if p.sort_by and p.sort_by not in sorts:
                raise ProviderFailure("invalid_sort")
            key, reverse = sorts[p.sort_by or "price_asc"]
            rows.sort(key=key, reverse=reverse)
            rows = list({r.id: r for r in rows}.values())
            return ProviderResult(source=Provenance(provider=self.name, status="cached", fetched_at=doc.fetched_at,
                local_cache_hit=doc.cached, source_url=URL, notice=NOTICE), items=rows, partial=True)
        except ProviderFailure as exc:
            if exc.code in {"invalid_response", "currency_mismatch"}:
                self.http.discard()
            return unavailable(self.name, URL, "Flight data unavailable: " + exc.code.replace("_", " ") + ".", exc.code, exc.retry_after)
        except (KeyError, ValueError, TypeError, ValidationError):
            self.http.discard()
            return unavailable(self.name, URL, "The flight provider returned invalid data.", "invalid_response")
