"""Bounded HTTP verification against a running app; no browser or mocked routing."""
import argparse
import json

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8012")
    args = parser.parse_args()
    flows = [
        [("Flights from GYD to IST on 2026-12-01", "flights"),
         ("Show me all CinemaPlus movies", "cinema"),
         ("Show laptops under $500", "shopping"), ("Back to flights", "flights")],
        [("Show me all CinemaPlus movies", "cinema"),
         ("Show wireless headphones under $100", "shopping"), ("Back to cinema", "cinema")],
    ]
    with httpx.Client(base_url=args.url, timeout=130, trust_env=False) as client:
        info = client.get("/api/client")
        info.raise_for_status()
        print(json.dumps({"runtime": info.json()}, ensure_ascii=True), flush=True)
        for number, flow in enumerate(flows, 1):
            sid, saved = None, {}
            for message, domain in flow:
                response = client.post("/api/chat", json={"message": message, "session_id": sid})
                response.raise_for_status()
                answer = response.json()
                sid = answer["session_id"]
                routing, state = answer["routing"], answer["state"]
                assert routing["domains"] == [domain], routing
                assert state["last_active_domain"] == domain, state["last_active_domain"]
                assert [r["domain"] for r in answer["results"]] == [domain]
                for previous, parameters in saved.items():
                    assert state[previous]["parameters"] == parameters, previous
                saved[domain] = state[domain]["parameters"]
                print(json.dumps({"flow": number, "message": message, "domain": domain,
                    "category": routing["category"], "source": routing["source"],
                    "fallback_reason": routing.get("fallback_reason"),
                    "parameters": state[domain]["parameters"], "contexts_preserved": True,
                    "providers": [{"domain": r["domain"], "status": r["status"],
                        "items": len(r["data"].get({"flights": "flights", "shopping": "products", "cinema": "movies"}[domain], [])),
                        "error": r["data"].get("provider_error")} for r in answer["results"]],
                    "duration_ms": answer["debug"]["total_ms"]}, ensure_ascii=True), flush=True)
    print("PASS: both requested sequences routed correctly and retained domain contexts.", flush=True)


if __name__ == "__main__":
    main()
