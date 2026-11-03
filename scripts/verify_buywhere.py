"""Optional live verification of BuyWhere's documented, read-only catalog API."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
BASE = "https://api.buywhere.ai"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", action="store_true")
    args = parser.parse_args()
    if args.provider:
        asyncio.run(verify_provider())
        return
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        spec = client.get(BASE + "/openapi.json")
        spec.raise_for_status()
        data = spec.json()
        output = Path("artifacts/provider-research/buywhere")
        output.mkdir(parents=True, exist_ok=True)
        (output / "openapi.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        for path in ("/products/search", "/products/{id}", "/categories"):
            method = data["paths"][path]["get"]
            print(path, json.dumps({k: method.get(k) for k in ("description", "security", "parameters")}, ensure_ascii=True)[:6000], flush=True)
        for query, market in (("laptop", "US"), ("backpack", "US"), ("wireless headphones", "SG")):
            response = client.get(BASE + "/v1/products/search", params={"q": query, "deliver_to": market,
                "country_code": market, "include_unshippable": "false", "limit": 3})
            response.raise_for_status()
            payload = response.json()
            print("Search", query, market, response.status_code, "meta", payload.get("meta"), flush=True)
            rows = payload.get("data", [])
            for row in rows:
                print(json.dumps({k: row.get(k) for k in ("id", "title", "price", "image_url", "url", "availability", "price_as_of", "category_path")}, ensure_ascii=True), flush=True)
            if query == "backpack" and rows and not data["paths"]["/products/{id}"]["get"].get("security"):
                item = client.get(BASE + "/v1/products/" + str(rows[0]["id"]))
                print("Detail", item.status_code, item.text[:4500].encode("ascii", "backslashreplace").decode(), flush=True)
        if not data["paths"]["/categories"]["get"].get("security"):
            response = client.get(BASE + "/v1/categories")
            print("Categories", response.status_code, response.text[:4000].encode("ascii", "backslashreplace").decode(), flush=True)
        else:
            print("Authenticated details/categories are excluded from anonymous checks.", flush=True)


async def verify_provider():
    from app.providers.buywhere import BuyWhereProvider
    from app.providers.http import ProviderHTTP
    from app.schemas import ShoppingParameters
    provider = BuyWhereProvider(ProviderHTTP())
    params = ShoppingParameters(query="headphones", currency="USD", max_price=100)
    first = await provider.search(params)
    assert first.error is None and first.items, first.error
    assert all(row.price.currency == "USD" and row.price.amount <= 100 for row in first.items)
    from app.config import Settings
    from app.providers.engine import ProviderDomainEngine
    from app.schemas import RoutingResult
    from app.state import SessionState
    engine, state = ProviderDomainEngine(Settings(), provider.http), SessionState()
    state.shopping.provider_snapshot = first.model_dump(mode="json")
    state.shopping.last_result_ids = [row.id for row in first.items]
    request = RoutingResult.model_validate({"category": "shopping", "domains": ["shopping"], "intents": [
        {"domain": "shopping", "intent": "details", "parameters": {"result_positions": [1]}}]})
    detail = (await asyncio.to_thread(engine.execute, request, state))[0]
    assert detail.status == "ok" and detail.data["provider"]["status"] == "cached"
    cached = await provider.search(params)
    assert cached.source.local_cache_hit
    print("Provider verified:", len(first.items), "real products, currency/budget, details, cache.")


if __name__ == "__main__":
    main()
