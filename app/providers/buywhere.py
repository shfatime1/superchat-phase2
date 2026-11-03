"""Documented BuyWhere public catalog search; no retailer scraping or private APIs."""

from datetime import datetime, timedelta
from decimal import Decimal
import ipaddress
import re
import logging
from urllib.parse import urlsplit

from app.providers.http import ProviderFailure
from app.providers.models import Price, ProductOffer, Provenance, ProviderResult, unavailable, utcnow

API = "https://api.buywhere.ai/v1"
WEBSITE = "https://buywhere.ai/"
MARKETS = {"US": "USD", "SG": "SGD", "VN": "VND", "TH": "THB", "MY": "MYR"}
logger = logging.getLogger(__name__)
NOTICE = ("BuyWhere multi-retailer catalog, not Birmarket. Advertised catalog prices may be old; "
          "check the price date and retailer checkout. Stock, delivery to Azerbaijan, taxes and final totals "
          "are unverified. BuyWhere may earn a commission through product links. "
          "Details without an API key use the saved search record; no authenticated routes are requested.")


def public_https(value):
    """Validate returned links without fetching merchant pages or following redirects."""
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if url.scheme != "https" or url.username or url.password or url.port not in {None, 443}:
            return None
        if not host or "." not in host or host.endswith((".local", ".internal", ".localhost")):
            return None
        try:
            ipaddress.ip_address(host)
            return None  # Product links must be public DNS names, never IP literals.
        except ValueError:
            return value
    except ValueError:
        return None


class BuyWhereProvider:
    name = "BuyWhere"
    website = WEBSITE

    def __init__(self, http, token=None, market="US"):
        if market not in MARKETS:
            raise ValueError("BUYWHERE_MARKET must be US, SG, VN, TH, or MY")
        self.http, self.token, self.market = http, token, market

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.token} if self.token else {}

    @staticmethod
    def normalize(raw):
        if type(raw["id"]) not in {str, int}:
            raise ValueError("Invalid product ID")
        identifier = str(raw["id"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", identifier):
            raise ValueError("Invalid product ID")
        if not isinstance(raw["title"], str) or not raw["title"].strip():
            raise ValueError("Missing title")
        price = raw.get("price")
        normalized_price = Price(amount=str(price["amount"]), currency=price["currency"]) if price else None
        stamp = raw.get("price_as_of")
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
        if observed and observed.utcoffset() is None:
            raise ValueError("Price date requires timezone")
        categories = raw.get("category_path") or []
        if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
            raise ValueError("Invalid categories")
        link = None
        for key in ("affiliate_redirect_url", "click_url"):
            candidate = public_https(raw.get(key))
            if candidate and urlsplit(candidate).hostname == "buywhere.ai":
                link = candidate
                break
        link = link or public_https(raw.get("url"))
        if not link:
            raise ValueError("Missing public product URL")
        # 'local' / 'unavailable' on the search response describe delivery ranking,
        # not merchant stock. Neither is converted into an inventory claim.
        return ProductOffer(id="BW-" + identifier, title=raw["title"].strip(), price=normalized_price,
            image_url=public_https(raw.get("image_url")), product_url=link,
            category=" / ".join(categories) or None,
            brand=raw.get("brand") if isinstance(raw.get("brand"), str) else None,
            merchant=raw.get("merchant_name") or raw.get("merchant"),
            price_as_of=observed,
            price_stale=utcnow() - observed > timedelta(hours=24) if observed else None)

    def result(self, doc, rows, partial=True, upstream_cached=False):
        return ProviderResult(source=Provenance(provider=self.name,
            status="cached" if doc.cached or upstream_cached else "live", fetched_at=doc.fetched_at,
            local_cache_hit=doc.cached, source_url=WEBSITE,
            notice=f"Browsing {self.market} catalog offers. " + NOTICE), items=rows, partial=partial)

    def failure(self, code, retry_after=None):
        messages = {
            "query_required": "Enter a product name, category or brand to search the BuyWhere catalog.",
            "unsupported_filter": "BuyWhere public search cannot verify stock availability. Colour matching uses explicit catalog text only.",
            "currency_filter_mismatch": f"Use a native {MARKETS[self.market]} budget for this catalog; AZN conversion is unavailable.",
            "currency_required": "Specify a single native currency for price budgets or sorting, for example USD.",
            "invalid_range": "The minimum price must not exceed the maximum price.",
            "invalid_sort": "Choose price ascending or descending; sorting applies to the returned subset.",
            "authorization_required": "BuyWhere product-detail API requires an optional BUYWHERE_API_KEY. Saved search details remain available without a key.",
            "upstream_degraded": "BuyWhere could not complete the search. Try again; an incomplete search does not establish that no products exist.",
        }
        message = messages.get(code, "BuyWhere catalog unavailable: " + code.replace("_", " ") + ".")
        return unavailable(self.name, WEBSITE, message, code, retry_after)

    async def search(self, p):
        query = p.query or p.category or p.brand
        if not query or not query.strip():
            return self.failure("query_required")
        if p.in_stock is not None:
            return self.failure("unsupported_filter")
        if p.min_price_azn is not None or p.max_price_azn is not None:
            return self.failure("currency_filter_mismatch")
        budget = p.min_price is not None or p.max_price is not None
        if budget and not p.currency:
            return self.failure("currency_required")
        if p.currency and p.currency.upper() != MARKETS[self.market]:
            return self.failure("currency_filter_mismatch")
        if p.min_price is not None and p.max_price is not None and p.min_price > p.max_price:
            return self.failure("invalid_range")
        if p.sort_by and p.sort_by not in {"price_asc", "price_desc"}:
            return self.failure("invalid_sort")
        terms = [query.strip()]
        for refinement in (p.category, p.brand, p.color):
            if refinement and refinement.casefold() not in " ".join(terms).casefold():
                terms.append(refinement)
        params = {"q": " ".join(terms), "country_code": self.market, "deliver_to": self.market,
                  "include_unshippable": "false", "limit": 50, "mode": "keyword"}
        if p.offset is not None:
            params["offset"] = p.offset
        if p.currency:
            params["currency"] = p.currency.upper()
        for field in ("min_price", "max_price"):
            if getattr(p, field) is not None:
                params[field] = getattr(p, field)
        try:
            doc = await self.http.get(API + "/products/search", params=params, headers=self.headers)
            if not isinstance(doc.data, dict) or not isinstance(doc.data.get("data"), list):
                raise ProviderFailure("invalid_response")
            meta = doc.data.get("meta", {})
            if not isinstance(meta, dict):
                raise ProviderFailure("invalid_response")
            if meta.get("degraded") or meta.get("status") == "degraded" or meta.get("emptiness_reason") in {"timeout", "api_error", "auth_failure"}:
                raise ProviderFailure("upstream_degraded")
            rows, rejected = [], 0
            for raw in doc.data["data"]:
                try:
                    rows.append(self.normalize(raw))
                except (KeyError, ValueError, TypeError, AttributeError):
                    rejected += 1
            if rejected:
                logger.warning("provider_rows_rejected provider=BuyWhere count=%d", rejected)
                if not rows:
                    raise ProviderFailure("invalid_response")
            rows = list({row.id: row for row in rows}.values())
            merchant_urls = {"BW-" + str(raw.get("id")): str(raw.get("url") or "")
                             for raw in doc.data["data"] if isinstance(raw, dict)}
            rows = self.relevant(rows, query, merchant_urls)
            # Check native response currencies even when upstream filters were ignored.
            if p.currency or budget:
                rows = [r for r in rows if r.price and r.price.currency == p.currency.upper()]
            if budget:
                rows = [r for r in rows if r.price and
                    (p.min_price is None or r.price.amount >= Decimal(str(p.min_price))) and
                    (p.max_price is None or r.price.amount <= Decimal(str(p.max_price)))]
            if p.brand:
                rows = [r for r in rows if (r.brand and r.brand.casefold() == p.brand.casefold()) or
                        re.search(r"\b" + re.escape(p.brand) + r"\b", r.title, re.I)]
            if p.color:
                rows = [r for r in rows if (r.color and r.color.casefold() == p.color.casefold()) or
                        re.search(r"\b" + re.escape(p.color) + r"\b", r.title, re.I)]
            if p.sort_by:
                known = [r for r in rows if r.price]
                if len({r.price.currency for r in known}) > 1:
                    return self.failure("currency_required")
                known.sort(key=lambda r: r.price.amount, reverse=p.sort_by == "price_desc")
                rows = known + [r for r in rows if not r.price]
            result = self.result(doc, rows, upstream_cached=meta.get("cached") is True)
            more = meta.get("has_more") is True and bool(doc.data["data"]) and (p.offset or 0) < 9950
            result.pagination = {"offset": p.offset or 0, "limit": 50, "has_more": more,
                                 "next_offset": (p.offset or 0) + 50 if more else None}
            return result
        except ProviderFailure as exc:
            if exc.code in {"invalid_response", "upstream_degraded"}:
                self.http.discard(host="api.buywhere.ai")
            return self.failure(exc.code, exc.retry_after)
        except (KeyError, ValueError, TypeError, AttributeError):
            self.http.discard(host="api.buywhere.ai")
            return self.failure("invalid_response")

    @staticmethod
    def relevant(rows, query, merchant_urls=None):
        """Rank real returned records; reject accessories for a device-only query.

        Merchant URL words are evidence when a retailer's title is only a model
        number. Coarse upstream categories are not treated as product identity.
        """
        tokens = re.findall(r"[a-z0-9]+", query.casefold())
        tokens = [t[:-1] if t.endswith("s") and len(t) > 3 else t for t in tokens]
        laptop = any(t in {"laptop", "notebook"} for t in tokens)
        accessories = r"\b(?:stand[ıi]?|riser|sleeve|charger|cable|adapter|replacement|screen protector|bag|case|cover|dock|mount|backpack|brush|cleaner|cleaning|toy|play set|tote|desk|support|accessory|accessories)s?\b"
        wants_accessory = re.search(accessories, query, re.I)
        ranked = []
        for index, row in enumerate(rows):
            title = row.title.casefold()
            # URLs are returned by the provider; no merchant page is fetched.
            evidence = title + " " + (row.category or "").casefold() + " " + (merchant_urls or {}).get(row.id, row.product_url).casefold()
            if laptop and not wants_accessory and re.search(accessories, title + " " + (merchant_urls or {}).get(row.id, "").replace("-", " ")):
                continue
            if laptop and not any(term in evidence for term in ("laptop", "notebook", "chromebook")):
                continue
            score = sum(t in title for t in tokens)
            ranked.append((-score, index, row))
        return [row for _, _, row in sorted(ranked)]

    async def details(self, item_id):
        # The documented detail endpoint is authenticated even where anonymous
        # requests happen to succeed. Do not rely on incidental public access.
        if not self.token:
            return self.failure("authorization_required")
        if not re.fullmatch(r"BW-[A-Za-z0-9][A-Za-z0-9_-]{0,127}", item_id):
            return self.failure("unknown_id")
        try:
            doc = await self.http.get(API + "/products/" + item_id[3:], headers=self.headers)
            data = doc.data.get("data") if isinstance(doc.data, dict) else None
            raw = data[0] if isinstance(data, list) and len(data) == 1 else data
            if not isinstance(raw, dict):
                raise ProviderFailure("invalid_response")
            row = self.normalize(raw)
            if row.id != item_id:
                raise ProviderFailure("invalid_response")
            return self.result(doc, [row], partial=False)
        except ProviderFailure as exc:
            if exc.code == "invalid_response":
                self.http.discard(host="api.buywhere.ai")
            return self.failure(exc.code, exc.retry_after)
        except (KeyError, ValueError, TypeError, AttributeError):
            self.http.discard(host="api.buywhere.ai")
            return self.failure("invalid_response")
