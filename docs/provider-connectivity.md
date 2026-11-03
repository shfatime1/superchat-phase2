# Provider connectivity and latency

The reported Render trace (`robots.txt`, 3 attempts, 26345 ms, `network_error`)
identifies the failed operation, not its underlying cause. The old Cinema transport
collapsed every HTTPX request exception into `network_error` and allowed three
8-second attempts plus backoff. DNS failure, TLS failure, connect timeout and read
timeout could all produce that same error. Gemini had already routed successfully.
Do not infer a Render firewall, IP block or certificate problem from that trace alone.

Both JSON and public Cinema requests now use the same bounded GET transport:

| Environment setting | Default | Meaning |
| --- | --- | --- |
| `PROVIDER_CONNECT_TIMEOUT_SECONDS` | 3 | Connect/TLS timeout per operation, capped by the configured HTTP timeout |
| `PROVIDER_TIMEOUT_SECONDS` | 8 | Read timeout; write/pool limits are capped at 3/1 seconds |
| `PROVIDER_REQUEST_BUDGET_SECONDS` | 12 | Total wall time for a fetch, including body reads, retries and crawl queue waits |
| `PROVIDER_DOMAIN_BUDGET_SECONDS` | 20 | Total time for one domain, including multi-page Cinema discovery |

Mixed requests also divide remaining time between domains and reserve five seconds
for final response work. Provider timeouts return a domain-specific error rather
than aborting the other domains. Failed selections are cleared within that domain;
search parameters and other domains remain intact. Existing successful caches and
request replay behavior remain unchanged.
The per-domain event loop closes without waiting for a cancelled native DNS worker;
otherwise `asyncio.run`'s executor shutdown can delay the response beyond its
timeout. Invalid-payload cache invalidation is limited to the failing provider host
and conversation, so Shopping errors cannot flush flight caches.

Retries apply to transient network failures, 408 and selected 5xx responses, within
the total budget. Permanent DNS failures, TLS/certificate failures, proxy failures,
401/403 and redirects are not retried or bypassed. 429 retains host-specific
`Retry-After` handling. Every Cinema attempt reserves the shared crawl slot; public
URL allowlisting, robots policy, crawl delays, TLS verification and configured
environment proxies remain enforced. HTTP 200 HTML challenges on `robots.txt` fail
closed. No private routes, IP pinning, proxy substitution or disabled TLS were added.

The Debugger's `provider_calls` now includes `attempt_details` with safe stage,
phase durations, reason, retryability, retry delay and HTTP status. Stages identify
connection, TLS, request write, response headers and response body. `connect` time
includes DNS and TCP; a connect timeout alone cannot distinguish those two. A
nested resolver exception produces `dns_error` or `dns_temporary`. Other reasons
include `tls_certificate_error`, `tls_timeout`, `connect_timeout`, `read_timeout`,
`connection_reset`, `proxy_error` and `request_budget_exhausted`. Logs include the
trace ID and the same allowlisted failure labels. No raw exception strings, trace
event payloads, headers, URLs with queries, IPs or response bodies are logged.

Run the following from the project directory in Render Shell to check the actual
Render egress path (running it locally tests only local connectivity):

```sh
python scripts/diagnose_connectivity.py
# Optional: one additional bounded sample for an intermittent problem
python scripts/diagnose_connectivity.py --provider cinema --samples 2
```

The tool performs a separate three-second DNS probe, then uses the production
adapters with normal robots/TLS checks. It prints address-family presence, timings,
result counts and sanitized Debugger records. It never prints API keys, DNS IPs,
product query strings or response bodies. It does not deploy or change settings.
The tool uses the configured provider; it does not substitute another marketplace.
Only booleans indicate whether CA/proxy environment overrides exist. Missing CA
files and invalid transport configuration become sanitized provider errors instead
of uncaught failures that abort the chat.

For a verified 401/403 or certificate failure, correct credentials/certificate
configuration or contact the provider. If the provider confirms that Render egress
addresses need authorization, use the service's outbound ranges from the dashboard
and request permission; do not evade restrictions. See the official
[Render outbound IP documentation](https://render.com/docs/outbound-ip-addresses).
HTTPX's official [timeout](https://www.python-httpx.org/advanced/timeouts/) and
[trace-extension](https://www.python-httpx.org/advanced/extensions/) documentation
describe the phase limits and events used here.
