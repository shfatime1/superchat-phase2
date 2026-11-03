"""Optional, explicitly named eBay Browse API; never presented as Birmarket."""

from app.providers.http import ProviderFailure
from app.providers.models import Price, ProductOffer, Provenance, ProviderResult, unavailable

URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


class EbayProvider:
    name = "eBay"

    def __init__(self, http, token=None, marketplace="EBAY_US"):
        self.http, self.token, self.marketplace = http, token, marketplace

    async def search(self, p):
        if not self.token:
            return unavailable(self.name, "https://www.ebay.com/", "Set EBAY_ACCESS_TOKEN to use the optional eBay catalog.", "missing_credentials")
        if not p.query:
            return unavailable(self.name, "https://www.ebay.com/", "Enter a product search query for eBay.", "query_required")
        if any(getattr(p, key) is not None for key in ("min_price_azn", "max_price_azn", "in_stock", "color", "brand", "category")):
            return unavailable(self.name, "https://www.ebay.com/", "This eBay adapter supports query and price sorting; AZN budgets and availability filters are unavailable.", "unsupported_filter")
        params = {"q": p.query, "limit": 50}
        if p.sort_by:
            if p.sort_by not in {"price_asc", "price_desc"}:
                return unavailable(self.name, "https://www.ebay.com/", "Choose price ascending or descending.", "invalid_sort")
            params["sort"] = "price" if p.sort_by == "price_asc" else "-price"
        try:
            doc = await self.http.get(URL, params=params, headers={"Authorization": "Bearer " + self.token,
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace})
            if not isinstance(doc.data, dict) or "total" not in doc.data:
                raise ProviderFailure("invalid_response")
            rows = [ProductOffer(id="EBAY-" + r["itemId"], title=r["title"],
                price=Price(amount=r["price"]["value"], currency=r["price"]["currency"]) if r.get("price") else None,
                image_url=r.get("image", {}).get("imageUrl"), product_url=r.get("itemWebUrl"))
                for r in doc.data.get("itemSummaries", [])]
            return ProviderResult(source=Provenance(provider=self.name, status="cached" if doc.cached else "live",
                fetched_at=doc.fetched_at, local_cache_hit=doc.cached, source_url="https://www.ebay.com/",
                notice="eBay results, not Birmarket. Provider currency is preserved; stock, delivery to Azerbaijan, taxes and checkout totals are unverified."),
                items=rows, partial=doc.data["total"] > len(rows))
        except ProviderFailure as exc:
            if exc.code == "invalid_response":
                self.http.discard()
            return unavailable(self.name, "https://www.ebay.com/", "eBay catalog unavailable.", exc.code, exc.retry_after)
        except (KeyError, TypeError, ValueError):
            self.http.discard()
            return unavailable(self.name, "https://www.ebay.com/", "eBay returned invalid data.", "invalid_response")
