"""Authorized eBay Browse catalog, clearly separate from Birmarket."""

import re
from decimal import Decimal
from urllib.parse import quote

from bs4 import BeautifulSoup

from app.providers.http import ProviderFailure
from app.providers.models import Price, ProductOffer, Provenance, ProviderResult, unavailable
from app.providers.ebay_auth import EbayCredentials

URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
NOTICE = ("eBay catalog, not Birmarket. Prices retain their provider currency. Availability is only "
          "reported when eBay supplies it; delivery to Azerbaijan, taxes and final checkout totals are unverified.")


class EbayProvider:
    name = "eBay"

    def __init__(self, http, token=None, marketplace="EBAY_US", client_id=None, client_secret=None):
        self.http, self.token, self.marketplace = http, token, marketplace
        self.credentials = EbayCredentials(http, token, client_id, client_secret)

    async def get(self, url, params=None):
        token = await self.credentials.token()
        try:
            return await self.http.get(url, params=params, headers={"Authorization": "Bearer " + token,
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace})
        except ProviderFailure as exc:
            if exc.code != "credentials_or_permissions" or self.credentials.static_token:
                raise
            self.credentials.invalidate()
            token = await self.credentials.token()
            return await self.http.get(url, params=params, headers={"Authorization": "Bearer " + token,
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace})

    @staticmethod
    def normalize(raw):
        if not re.fullmatch(r"v1\|[0-9]+\|[0-9]+", raw["itemId"]):
            raise ValueError("Invalid item ID")
        aspects = {a["name"].casefold(): a["value"] for a in raw.get("localizedAspects", [])}
        categories = raw.get("categories", [])
        statuses = {a.get("estimatedAvailabilityStatus") for a in raw.get("estimatedAvailabilities", [])}
        known_statuses = statuses - {None, "UNKNOWN"}
        available = True if known_statuses & {"IN_STOCK", "LIMITED_STOCK"} else False if known_statuses == {"OUT_OF_STOCK"} else None
        description = raw.get("shortDescription")
        return ProductOffer(id="EBAY-" + raw["itemId"], title=raw["title"],
            price=Price(amount=raw["price"]["value"], currency=raw["price"]["currency"]) if raw.get("price") else None,
            image_url=raw.get("image", {}).get("imageUrl"), product_url=raw.get("itemWebUrl"),
            category=categories[0].get("categoryName") if categories else raw.get("categoryPath"),
            category_id=categories[0].get("categoryId") if categories else raw.get("categoryId"),
            brand=aspects.get("brand"), color=aspects.get("color"), condition=raw.get("condition"),
            description=BeautifulSoup(description, "html.parser").get_text(" ", strip=True)[:500] if description else None,
            in_stock=available, availability_status=next(iter(known_statuses)) if len(known_statuses) == 1 else None)

    def result(self, doc, rows, partial=False):
        return ProviderResult(source=Provenance(provider=self.name, status="cached" if doc.cached else "live",
            fetched_at=doc.fetched_at, local_cache_hit=doc.cached, source_url="https://www.ebay.com/", notice=NOTICE), items=rows, partial=partial)

    def failure(self, exc):
        if exc.code == "invalid_response":
            self.http.discard()
        message = "Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET (or EBAY_ACCESS_TOKEN) in Render to enable real eBay products." if exc.code == "missing_credentials" else "eBay catalog unavailable: " + exc.code.replace("_", " ") + "."
        return unavailable(self.name, "https://www.ebay.com/", message, exc.code, exc.retry_after)

    async def search(self, p):
        if not self.credentials.configured:
            return self.failure(ProviderFailure("missing_credentials"))
        if not p.query:
            return unavailable(self.name, "https://www.ebay.com/", "Enter a product search query for eBay.", "query_required")
        if p.in_stock is not None or p.min_price_azn is not None or p.max_price_azn is not None:
            return unavailable(self.name, "https://www.ebay.com/", "eBay uses native listing currencies; AZN budgets and search-time stock filters are unavailable. Request item details for provider-reported availability.", "unsupported_filter")
        params = {"q": p.query, "limit": 50}
        if p.offset is not None:
            params["offset"] = p.offset
        if p.min_price is not None or p.max_price is not None:
            if not p.currency:
                return self.failure(ProviderFailure("currency_required"))
            if p.min_price is not None and p.max_price is not None and p.min_price > p.max_price:
                return self.failure(ProviderFailure("invalid_range"))
            lower = str(p.min_price) if p.min_price is not None else ""
            upper = str(p.max_price) if p.max_price is not None else ""
            bounds = lower + ".." + upper if upper else lower
            params["filter"] = "price:[" + bounds + "],priceCurrency:" + p.currency.upper()
        if p.sort_by:
            if p.sort_by not in {"price_asc", "price_desc"}:
                return unavailable(self.name, "https://www.ebay.com/", "Choose price ascending or descending.", "invalid_sort")
            params["sort"] = "price" if p.sort_by == "price_asc" else "-price"
        try:
            if p.category or p.brand or p.color:
                refinement_doc = await self.get(URL, params={"q": p.query, "fieldgroups": "ASPECT_REFINEMENTS,CATEGORY_REFINEMENTS", "limit": 1})
                if not isinstance(refinement_doc.data, dict):
                    raise ProviderFailure("invalid_response")
                refinement = refinement_doc.data.get("refinement", {})
                if not isinstance(refinement, dict):
                    raise ProviderFailure("invalid_response")
                category = p.category if p.category and p.category.isdigit() else refinement.get("dominantCategoryId")
                if p.category and not p.category.isdigit():
                    category = next((c["categoryId"] for c in refinement.get("categoryDistributions", []) if c.get("categoryName", "").casefold() == p.category.casefold()), None)
                if not category or not str(category).isdigit():
                    raise ProviderFailure("category_required")
                params["category_ids"] = str(category)
                clauses = ["categoryId:" + str(category)]
                for field, value in (("Brand", p.brand), ("Color", p.color)):
                    if value:
                        if re.search(r"[{}:,\\|]", value):
                            raise ProviderFailure("unsupported_filter")
                        available_aspect = next((a["localizedAspectName"] for a in refinement.get("aspectDistributions", []) if a.get("localizedAspectName", "").casefold() == field.casefold()), None)
                        if available_aspect is None:
                            raise ProviderFailure("unsupported_filter")
                        clauses.append(available_aspect + ":{" + value + "}")
                if len(clauses) > 1:
                    params["aspect_filter"] = ",".join(clauses)
            doc = await self.get(URL, params=params)
            if not isinstance(doc.data, dict) or "total" not in doc.data:
                raise ProviderFailure("invalid_response")
            if doc.data.get("warnings") and (p.sort_by or p.brand or p.color or p.category or p.min_price is not None or p.max_price is not None):
                raise ProviderFailure("unsupported_filter")
            rows = [self.normalize(r) for r in doc.data.get("itemSummaries", [])]
            if p.min_price is not None or p.max_price is not None:
                if any(r.price and r.price.currency != p.currency.upper() for r in rows):
                    raise ProviderFailure("currency_mismatch")
                rows = [r for r in rows if r.price and
                    (p.min_price is None or r.price.amount >= Decimal(str(p.min_price))) and
                    (p.max_price is None or r.price.amount <= Decimal(str(p.max_price)))]
            result = self.result(doc, rows, partial=doc.data["total"] > len(rows))
            more = bool(doc.data.get("itemSummaries")) and doc.data["total"] > (p.offset or 0) + 50 and (p.offset or 0) < 9950
            result.pagination = {"offset": p.offset or 0, "limit": 50, "has_more": more,
                                 "next_offset": (p.offset or 0) + 50 if more else None}
            return result
        except ProviderFailure as exc:
            return self.failure(exc)
        except (KeyError, TypeError, ValueError):
            self.http.discard()
            return unavailable(self.name, "https://www.ebay.com/", "eBay returned invalid data.", "invalid_response")

    async def details(self, item_id):
        if not re.fullmatch(r"EBAY-v1\|[0-9]+\|[0-9]+", item_id):
            return unavailable(self.name, "https://www.ebay.com/", "Choose a valid eBay item ID.", "unknown_id")
        try:
            doc = await self.get("https://api.ebay.com/buy/browse/v1/item/" + quote(item_id[5:], safe=""))
            row = self.normalize(doc.data)
            if row.id != item_id:
                raise ProviderFailure("invalid_response")
            return self.result(doc, [row])
        except ProviderFailure as exc:
            return self.failure(exc)
        except (KeyError, TypeError, ValueError):
            self.http.discard()
            return self.failure(ProviderFailure("invalid_response"))
