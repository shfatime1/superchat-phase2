"""Run locally or in Render Shell: bounded, read-only provider/DNS diagnostics.

No credentials, response bodies, query strings or resolved IPs are printed.
Uses the production adapters, normal TLS verification and robots enforcement.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
from queue import Queue, Empty
from threading import Thread
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.diagnostics import Trace
from app.providers.engine import ProviderDomainEngine
from app.providers.network import network_failure
from app.schemas import RoutingResult
from app.state import SessionState


def dns(host):
    started = perf_counter()
    result = Queue(maxsize=1)
    def resolve():
        try:
            result.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError as exc:
            result.put(exc)
    # A system resolver cannot always be interrupted. A daemon diagnostic probe
    # avoids waiting for executor shutdown after the three-second timeout.
    Thread(target=resolve, daemon=True, name="provider-dns-probe").start()
    try:
        rows = result.get(timeout=3)
        if isinstance(rows, OSError):
            return {"host": host, "dns": network_failure(rows)[0]}
        return {"host": host, "dns": "ok", "ipv4": any(r[0] == socket.AF_INET for r in rows),
                "ipv6": any(r[0] == socket.AF_INET6 for r in rows),
                "duration_ms": round((perf_counter() - started) * 1000)}
    except Empty:
        return {"host": host, "dns": "dns_probe_timeout"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["cinema", "shopping", "all"], default="all")
    parser.add_argument("--samples", type=int, choices=[1, 2, 3], default=1)
    args = parser.parse_args()
    settings = Settings.from_env()
    engine = ProviderDomainEngine(settings)
    # Diagnose the active adapters rather than silently changing providers.
    hosts = {"cinema": "api.themoviedb.org" if settings.cinema_provider == "tmdb" else "cinemastercard.az",
             "shopping": "api.ebay.com" if settings.shopping_provider == "ebay" else
                         "birmarket.az" if settings.shopping_provider == "birmarket" else "api.buywhere.ai"}
    domains = list(hosts) if args.provider == "all" else [args.provider]
    print(json.dumps({"connect_timeout_seconds": engine.http.connect_timeout,
        "fetch_budget_seconds": engine.http.request_budget, "domain_budget_seconds": engine.http.domain_budget,
        "tls_verification": True, "robots_enforced": settings.cinema_provider != "tmdb",
        "ca_environment_override": bool(os.getenv("SSL_CERT_FILE") or os.getenv("SSL_CERT_DIR")),
        "proxy_environment_configured": any(os.getenv(k) for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"))}), flush=True)
    probes = {}
    for domain in domains:
        probes[domain] = dns(hosts[domain])
        print(json.dumps(probes[domain]), flush=True)
    for sample in range(args.samples):
        for domain in domains:
            if probes[domain]["dns"] != "ok":
                print(json.dumps({"domain": domain, "skipped": "dns_probe_failed"}), flush=True)
                continue
            trace = Trace(timeout=settings.chat_timeout_seconds, refresh=True)
            trace.scope = "connectivity-check"
            parameters = {"query": "laptops"} if domain == "shopping" else {}
            routing = RoutingResult.model_validate({"category": domain, "domains": [domain],
                "intents": [{"domain": domain, "intent": "search", "parameters": parameters}]})
            with trace.activate():
                result = engine.execute(routing, SessionState())[0]
                debug = trace.finish()
            key = "products" if domain == "shopping" else "movies"
            print(json.dumps({"sample": sample + 1, "domain": domain, "status": result.status,
                "code": result.code, "items": len(result.data.get(key, [])), "debug": debug}), flush=True)


if __name__ == "__main__":
    main()
