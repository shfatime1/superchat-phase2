"""Allowlisted network diagnostics; never serialize exception text or trace info."""
import errno
import socket
import ssl
from time import perf_counter

import httpx

from app.diagnostics import active_call


def network_failure(exc, stage=None):
    pending, seen, chain = [exc], set(), []
    while pending and len(seen) < 24:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        chain.append(item)
        pending.extend(e for e in (item.__cause__, item.__context__) if e is not None)
        pending.extend(getattr(item, "exceptions", ()))
    if any(isinstance(e, ssl.SSLCertVerificationError) for e in chain):
        return "tls_certificate_error", False
    if any(isinstance(e, ssl.SSLError) for e in chain):
        return "tls_error", False
    dns = next((e for e in chain if isinstance(e, socket.gaierror)), None)
    if dns is not None:
        return "dns_temporary" if dns.errno == socket.EAI_AGAIN else "dns_error", dns.errno == socket.EAI_AGAIN
    if any(isinstance(e, PermissionError) or getattr(e, "errno", None) in {errno.EACCES, errno.EPERM, 10013} for e in chain):
        return "network_access_denied", False
    if isinstance(exc, httpx.ProxyError):
        return "proxy_error", False
    if isinstance(exc, httpx.ConnectTimeout):
        return "tls_timeout" if stage == "tls" else "connect_timeout", True
    for kind, reason in ((httpx.ReadTimeout, "read_timeout"), (httpx.WriteTimeout, "write_timeout"),
                         (httpx.PoolTimeout, "pool_timeout")):
        if isinstance(exc, kind):
            return reason, True
    if any(isinstance(e, ConnectionResetError) or getattr(e, "errno", None) in {errno.ECONNRESET, 10054} for e in chain):
        return "connection_reset", True
    if any(isinstance(e, ConnectionRefusedError) for e in chain):
        return "connection_refused", True
    if isinstance(exc, httpx.RemoteProtocolError):
        return "remote_protocol_error", True
    if stage == "tls":
        return "tls_error", False
    if isinstance(exc, (httpx.UnsupportedProtocol, httpx.LocalProtocolError, httpx.DecodingError)):
        return "invalid_transport_response", False
    return "connection_error", True


class Attempt:
    def __init__(self, number):
        self.started, self.phases = perf_counter(), {}
        self.data = {"attempt": number, "stage": "request", "phase_ms": {}}
        call = active_call.get()
        if call is not None:
            call.setdefault("attempt_details", []).append(self.data)

    async def trace(self, name, info):
        # Ignore info: it can contain request headers, certificates and exceptions.
        event, _, status = name.rpartition(".")
        stage = {"connect_tcp": "connect", "start_tls": "tls", "send_request_headers": "write",
                 "send_request_body": "write", "receive_response_headers": "response_headers",
                 "receive_response_body": "response_body"}.get(event.rsplit(".", 1)[-1])
        if not stage:
            return
        if status == "started":
            self.data["stage"] = stage
            self.phases[event] = perf_counter()
        elif status in {"complete", "failed"} and event in self.phases:
            self.data["phase_ms"][stage] = round((perf_counter() - self.phases.pop(event)) * 1000)

    def finish(self, **fields):
        self.data.update(duration_ms=round((perf_counter() - self.started) * 1000), **fields)
