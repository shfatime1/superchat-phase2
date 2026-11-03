"""Read-only public BuyWhere contract diagnostics; never prints credentials."""
import asyncio
import json
from pathlib import Path
import sys
import argparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.providers.buywhere import API, BuyWhereProvider


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    if parser.parse_args().verify:
        from app.fallback import LocalRouter
        from app.repositories import Repositories
        from app.providers.http import ProviderHTTP
        from app.state import SessionState
        provider = BuyWhereProvider(ProviderHTTP(timeout=25, retries=0))
        router = LocalRouter(Repositories.empty())
        for query in ("500$ dan ucuz notebooklar", "laptops under $500", "laptops is price under 500$"):
            routed = router.route(query, SessionState())
            params = routed.intents[0].parameters
            assert params.query == "laptops" and params.currency == "USD" and params.max_price == 500
            response = await provider.search(params)
            assert response.error is None and response.items, response.error
            assert all(row.price.currency == "USD" and row.price.amount <= 500 for row in response.items)
            print("VERIFIED", query.encode("ascii", "backslashreplace").decode(), "query=", params.query,
                  "currency=USD max_price=500", "products=", len(response.items), "cached=", response.source.local_cache_hit, flush=True)
        return
    output = Path("artifacts/provider-research/buywhere/diagnostics")
    output.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        for i, query in enumerate(("laptops", "laptops is price under 500$", "500$ dan ucuz notebooklar")):
            params = dict(q=query, country_code="US", deliver_to="US", include_unshippable="false",
                          limit=50, mode="keyword", currency="USD", max_price=500)
            response = await client.get(API + "/products/search", params=params)
            print("REQUEST", str(response.request.url), "STATUS", response.status_code, flush=True)
            response.raise_for_status()
            payload = response.json()
            (output / f"response-{i}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            rows = payload.get("data", [])
            print("ENVELOPE", list(payload), "ROWS", len(rows), "META", json.dumps(payload.get("meta"), ensure_ascii=True)[:500], flush=True)
            for row in rows:
                try:
                    BuyWhereProvider.normalize(row)
                except Exception as exc:
                    print("REJECTED", type(exc).__name__, str(exc).encode("ascii", "backslashreplace").decode()[:700],
                          json.dumps(row, ensure_ascii=True)[:2200], flush=True)
            print("SAMPLE", json.dumps(rows[:1], ensure_ascii=True)[:1600], flush=True)


if __name__ == "__main__":
    asyncio.run(main())
