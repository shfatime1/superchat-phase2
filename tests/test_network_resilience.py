"""Essential timeout, privacy, access and cross-domain failure regressions."""
import asyncio
import json
import socket
import ssl
from time import perf_counter, sleep

import httpx
import pytest

from app.config import Settings
from app.diagnostics import Trace
from app.providers.engine import ProviderDomainEngine
from app.providers.http import ProviderHTTP, ProviderFailure
from app.providers.buywhere import BuyWhereProvider
from app.providers.network import network_failure
from app.providers.public_cinema_http import PublicCinemaPages
from app.schemas import RoutingResult, ShoppingParameters
from app.state import SessionState
from test_cinemaplus_public import HOME_HTML, ABOUT_HTML


@pytest.mark.parametrize("cause,reason,retryable", [
    (socket.gaierror(socket.EAI_NONAME, "SECRET_DNS"), "dns_error", False),
    (socket.gaierror(socket.EAI_AGAIN, "SECRET_DNS"), "dns_temporary", True),
    (ssl.SSLCertVerificationError(1, "SECRET_CERT"), "tls_certificate_error", False),
    (ConnectionResetError(104, "SECRET_IP"), "connection_reset", True),
])
def test_nested_network_causes_are_sanitized(cause, reason, retryable):
    failure = httpx.ConnectError("SECRET_URL")
    failure.__cause__ = cause
    assert network_failure(failure) == (reason, retryable)


def test_cinema_connect_timeout_has_detailed_trace_and_never_skips_robots():
    calls = []
    async def handler(request):
        calls.append(request.url.path)
        await request.extensions["trace"]("connection.connect_tcp.started", {"secret": "SECRET"})
        raise httpx.ConnectTimeout("SECRET")
    async def no_sleep(_): pass
    http = ProviderHTTP(transport=httpx.MockTransport(handler), retries=2, sleep=no_sleep)
    trace = Trace()
    with trace.activate(), pytest.raises(ProviderFailure, match="timeout"):
        asyncio.run(PublicCinemaPages(http).read("https://cinemastercard.az/en/"))
    call = trace.data["provider_calls"][0]
    assert calls == ["/robots.txt"] * 3
    assert call["failure_reason"] == "connect_timeout"
    assert call["attempt_details"][0]["stage"] == "connect"
    assert all(a["reason"] == "connect_timeout" for a in call["attempt_details"])
    assert "SECRET" not in json.dumps(trace.data)


def test_tls_failure_is_not_retried_or_leaked():
    calls = []
    def handler(request):
        calls.append(request)
        failure = httpx.ConnectError("SECRET")
        failure.__cause__ = ssl.SSLCertVerificationError(1, "SECRET")
        raise failure
    trace = Trace()
    with trace.activate(), pytest.raises(ProviderFailure, match="network_error"):
        asyncio.run(ProviderHTTP(transport=httpx.MockTransport(handler)).get("https://api.buywhere.ai/products/search"))
    assert len(calls) == 1
    assert trace.data["provider_calls"][0]["failure_reason"] == "tls_certificate_error"
    assert "SECRET" not in json.dumps(trace.data)


def test_wall_clock_budget_bounds_slow_body_and_retries():
    async def handler(request):
        await asyncio.sleep(2)
        return httpx.Response(200, json={"data": []})
    trace = Trace()
    started = perf_counter()
    with trace.activate(), pytest.raises(ProviderFailure) as failed:
        asyncio.run(ProviderHTTP(transport=httpx.MockTransport(handler), request_budget=.03).get("https://api.buywhere.ai/products/search"))
    assert failed.value.reason == "request_budget_exhausted"
    assert perf_counter() - started < .8
    assert trace.data["provider_calls"][0]["attempts"] == 1


@pytest.mark.parametrize("blocked_domain", ["cinema", "shopping"])
def test_slow_provider_does_not_abort_other_domain(blocked_domain):
    async def handler(request):
        domain = "cinema" if request.url.host == "cinemastercard.az" else "shopping"
        if domain == blocked_domain:
            await asyncio.sleep(2)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"})
        if request.url.host == "cinemastercard.az":
            return httpx.Response(200, text=HOME_HTML if request.url.path == "/en/" else ABOUT_HTML, headers={"Content-Type": "text/html"})
        return httpx.Response(200, json={"data": []})
    async def no_sleep(_): pass
    http = ProviderHTTP(transport=httpx.MockTransport(handler), retries=0, sleep=no_sleep, domain_budget=.06)
    engine = ProviderDomainEngine(Settings(), http)
    other = "shopping" if blocked_domain == "cinema" else "cinema"
    routing = RoutingResult.model_validate({"category": "mixed", "domains": [blocked_domain, other], "intents": [
        {"domain": d, "intent": "search", "parameters": {"query": "laptops"} if d == "shopping" else {}}
        for d in (blocked_domain, other)]})
    trace, state = Trace(), SessionState()
    with trace.activate():
        results = engine.execute(routing, state)
    assert results[0].code == "timeout"
    assert results[1].status in {"ok", "no_results"}
    assert state.shopping.parameters.query == "laptops"
    assert any(e.get("reason") == "domain_budget_exhausted" for e in trace.data["errors"])


@pytest.mark.parametrize("response", [httpx.Response(403), httpx.Response(200, text="<html>challenge</html>", headers={"Content-Type": "text/html"})])
def test_robots_access_failure_is_never_bypassed(response):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return response
    http = ProviderHTTP(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure, match="public_access_restricted"):
        asyncio.run(PublicCinemaPages(http).read("https://cinemastercard.az/en/"))
    assert calls == ["/robots.txt"]


def test_cancelled_dns_worker_cleanup_does_not_hold_up_next_domain():
    async def handler(request):
        if request.url.host == "api.buywhere.ai":
            # Model an uninterruptible native resolver in the default executor.
            await asyncio.get_running_loop().run_in_executor(None, sleep, .5)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"})
        return httpx.Response(200, text=HOME_HTML if request.url.path == "/en/" else ABOUT_HTML, headers={"Content-Type": "text/html"})
    async def no_sleep(_): pass
    http = ProviderHTTP(transport=httpx.MockTransport(handler), retries=0, domain_budget=.03, sleep=no_sleep)
    engine = ProviderDomainEngine(Settings(), http)
    routing = RoutingResult.model_validate({"category": "mixed", "domains": ["shopping", "cinema"], "intents": [
        {"domain": "shopping", "intent": "search", "parameters": {"query": "laptops"}},
        {"domain": "cinema", "intent": "search", "parameters": {}}]})
    started = perf_counter()
    results = engine.execute(routing, SessionState())
    assert results[0].code == "timeout" and results[1].status == "ok"
    assert perf_counter() - started < .35


def test_bad_shopping_payload_does_not_invalidate_flight_cache():
    def handler(request):
        return httpx.Response(200, json={"data": {}} if request.url.host == "api.buywhere.ai" else {"safe": True})
    http = ProviderHTTP(transport=httpx.MockTransport(handler))
    async def check():
        url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
        await http.get(url)
        result = await BuyWhereProvider(http).search(ShoppingParameters(query="laptops"))
        assert result.error.code == "invalid_response"
        assert (await http.get(url)).cached
    asyncio.run(check())


def test_transient_read_and_upstream_error_recover_with_safe_attempt_history():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("SECRET")
        return httpx.Response(503 if len(calls) == 2 else 200, json={"data": []})
    async def no_sleep(_): pass
    trace = Trace()
    with trace.activate():
        asyncio.run(ProviderHTTP(transport=httpx.MockTransport(handler), sleep=no_sleep).get("https://api.buywhere.ai/products/search"))
    call = trace.data["provider_calls"][0]
    assert call["attempts"] == 3 and call["status"] == 200 and "error" not in call
    assert call["attempt_details"][0]["reason"] == "read_timeout"
    assert call["attempt_details"][1]["status"] == 503
    assert "SECRET" not in json.dumps(trace.data)


def test_bad_ca_configuration_is_sanitized_instead_of_crashing_chat(monkeypatch):
    def fail(**kwargs):
        assert kwargs["verify"] is True
        raise FileNotFoundError("SECRET_CA_PATH")
    monkeypatch.setattr("app.providers.http.httpx.AsyncClient", fail)
    trace = Trace()
    with trace.activate():
        result = asyncio.run(BuyWhereProvider(ProviderHTTP()).search(ShoppingParameters(query="laptops")))
    assert result.error.code == "network_error"
    call = trace.data["provider_calls"][0]
    assert call["attempts"] == 0 and call["failure_reason"] == "tls_configuration_error"
    assert "SECRET" not in json.dumps(trace.data) + result.model_dump_json()
