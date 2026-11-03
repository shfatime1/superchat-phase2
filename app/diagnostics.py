"""Request-scoped, allowlisted diagnostics. Never capture prompts or HTTP secrets."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic, perf_counter
from urllib.parse import urlsplit
from uuid import uuid4
import logging

current = ContextVar("superchat_trace", default=None)
active_call = ContextVar("superchat_http_call", default=None)
logger = logging.getLogger(__name__)


def configure_logging():
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s level=%(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class RequestTimeout(RuntimeError):
    pass


class Trace:
    def __init__(self, emit=None, timeout=120, refresh=False):
        self.started, self.deadline = perf_counter(), monotonic() + timeout
        self.emit = emit or (lambda kind, data: None)
        self.scope, self.refresh = None, refresh
        self.data = {"trace_id": uuid4().hex, "routing": {}, "provider_calls": [], "stages": [], "errors": []}

    @contextmanager
    def activate(self):
        token = current.set(self)
        try:
            yield self
        finally:
            current.reset(token)

    def check(self):
        if monotonic() >= self.deadline:
            raise RequestTimeout("Request timed out")

    def progress(self, step, **extra):
        self.check()
        self.emit("progress", {"step": step, **extra})

    def finish(self):
        self.data["total_ms"] = round((perf_counter() - self.started) * 1000)
        calls = self.data["provider_calls"]
        self.data["cache"] = {"hits": sum(c["cache"] == "hit" for c in calls), "misses": sum(c["cache"] == "miss" for c in calls)}
        logger.info("chat_complete trace_id=%s duration_ms=%d provider_calls=%d", self.data["trace_id"], self.data["total_ms"], len(calls))
        return self.data


def cache_context():
    trace = current.get()
    return (trace.scope, trace.refresh) if trace else (None, False)


def http_status(status):
    call = active_call.get()
    if call is not None:
        call["status"] = status


def http_attempt():
    call = active_call.get()
    if call is not None:
        call["attempts"] += 1


@contextmanager
def http_call(method, url):
    trace = current.get()
    call = {"cache": "miss", "attempts": 0}
    if not trace:
        yield call
        return
    trace.check()
    parts = urlsplit(url)
    allowed_hosts = {"api.buywhere.ai", "api.travelpayouts.com", "autocomplete.travelpayouts.com", "api.ebay.com", "api.themoviedb.org", "cinemastercard.az"}
    static = {"v1", "v3", "3", "aviasales", "prices_for_dates", "places2", "products", "search", "buy", "browse", "item_summary", "item", "identity", "oauth2", "token", "movie", "discover", "genre", "list", "en", "films", "cinema", "about-cinemaplus", "robots.txt"}
    call.update(method=method, host=parts.hostname if parts.hostname in allowed_hosts else "external",
                endpoint="/" + "/".join(p if p in static else ":id" for p in parts.path.split("/") if p))
    if len(trace.data["provider_calls"]) < 100:
        trace.data["provider_calls"].append(call)
    token, started = active_call.set(call), perf_counter()
    try:
        yield call
    except Exception as exc:
        code = getattr(exc, "code", "request_failed")
        call["error"] = code if code in {"rate_limited", "network_error", "timeout", "credentials_or_permissions", "invalid_response", "upstream_error", "public_access_restricted", "public_page_unavailable", "robots_disallowed"} else "request_failed"
        raise
    finally:
        call["duration_ms"] = round((perf_counter() - started) * 1000)
        active_call.reset(token)
