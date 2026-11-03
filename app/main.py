
from contextlib import asynccontextmanager
from hashlib import sha256
from secrets import token_urlsafe
from threading import RLock
from threading import Thread, BoundedSemaphore
from collections import defaultdict, deque
from queue import Queue, Empty
from time import monotonic
import asyncio
import json
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.chat import ChatResponse, ChatService
from app.config import PROJECT_ROOT, Settings
from app.fallback import ResilientRouter
from app.repositories import DataSourceError, Repositories
from app.domains.engine import DomainEngine
from app.providers.engine import ProviderDomainEngine
from app.responses import GeminiResponseFormulator
from app.routing import GeminiRouter, InvalidRouterResponse, Router, RouterUnavailable
from app.schemas import ChatRequest
from app.state import SessionNotFound, SessionState, SessionStore
from app.diagnostics import RequestTimeout, configure_logging
from app.media import GeminiMedia, MediaFailure, validate_media, IMAGE_LIMIT, AUDIO_LIMIT


def create_app(settings: Settings | None = None, router: Router | None = None) -> FastAPI:
    configure_logging()
    settings = settings or Settings.from_env()
    sessions = SessionStore()
    service = ChatService(router or GeminiRouter(settings), sessions, GeminiResponseFormulator(settings))
    owners = {}
    cached_requests, request_locks = {}, {}
    guard = RLock()
    rate_windows = defaultdict(deque)
    streaming_slots = BoundedSemaphore(8)
    media_slots = BoundedSemaphore(4)
    media = GeminiMedia(settings)

    def check_rate(request):
        now = monotonic()
        keys = [("owner", request.state.owner, settings.chat_rate_limit),
                ("ip", request.client.host if request.client else "unknown", settings.chat_rate_limit * 4)]
        with guard:
            for kind, value, limit in keys:
                window = rate_windows[(kind, value)]
                while window and window[0] <= now - 60:
                    window.popleft()
                if len(window) >= limit:
                    raise HTTPException(429, "Too many requests. Please try again shortly.", headers={"Retry-After": str(max(1, int(60 - (now - window[0])) + 1))})
            for kind, value, _ in keys:
                rate_windows[(kind, value)].append(now)
            if len(rate_windows) > 4096:
                for key in list(rate_windows):
                    if not rate_windows[key] or rate_windows[key][-1] < now - 60:
                        del rate_windows[key]

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            if settings.data_mode not in {"providers", "fixtures"}:
                raise ValueError("SUPERCHAT_DATA_MODE must be providers or fixtures")
            application.state.repositories = Repositories.from_json(settings.data_dir) if settings.data_mode == "fixtures" else Repositories.empty()
            service.engine = DomainEngine(application.state.repositories) if settings.data_mode == "fixtures" else ProviderDomainEngine(settings)
            if router is None:
                service.router = ResilientRouter(settings, application.state.repositories)
            application.state.data_ready = True
        except DataSourceError:
            application.state.data_ready = False
        yield

    application = FastAPI(title="SuperChat", lifespan=lifespan)
    application.state.sessions = sessions
    application.state.chat_service = service
    application.state.data_ready = False
    application.mount("/static", StaticFiles(directory=PROJECT_ROOT / "app" / "static"), name="static")

    @application.middleware("http")
    async def browser_identity(request: Request, call_next):
        owner = request.cookies.get("superchat_owner")
        if not owner or len(owner) != 43:
            owner = token_urlsafe(32)
        request.state.owner = owner
        response = await call_next(request)
        if request.cookies.get("superchat_owner") != owner:
            response.set_cookie("superchat_owner", owner, httponly=True, samesite="lax",
                                secure=settings.secure_cookies, max_age=60 * 60 * 24 * 30)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path not in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://www.themoviedb.org https://image.tmdb.org https://i.ebayimg.com https://cinemastercard.az https://m.media-amazon.com https://images-na.ssl-images-amazon.com https://cdn.shopify.com https://c1.neweggimages.com https://i5.walmartimages.com https://target.scene7.com; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/")
    def home():
        return FileResponse(PROJECT_ROOT / "app" / "static" / "index.html")

    @application.get("/api/client")
    def client_info(request: Request):
        return {"namespace": sha256(request.state.owner.encode()).hexdigest()[:24],
                "routing_mode": settings.routing_mode, "reference_date": settings.reference_date().isoformat(),
                "data_mode": settings.data_mode,
                "gemini_configured": bool(settings.api_key),
                "media_enabled": bool(settings.api_key),
                "routing_status": service.router.status() if isinstance(service.router, ResilientRouter) else "custom"}

    async def process_media(request, kind, session_id):
        if session_id is not None and owners.get(session_id) != request.state.owner:
            raise HTTPException(404, "Session not found")
        # Same-origin browser uploads; session cookies and existing rate limits apply.
        from urllib.parse import urlsplit
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "Cross-origin uploads are not allowed")
        check_rate(request)
        if not media_slots.acquire(blocking=False):
            raise HTTPException(429, "media_rate_limited", headers={"Retry-After": "5"})
        try:
            if kind == "image" and settings.shopping_provider not in {"auto", "buywhere"}:
                raise MediaFailure(409, "visual_requires_buywhere")
            limit = IMAGE_LIMIT if kind == "image" else AUDIO_LIMIT
            mime = request.headers.get("content-type", "").split(";", 1)[0].lower().strip()
            async def read():
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > limit:
                        raise MediaFailure(413, "media_too_large")
                    data.extend(chunk)
                return bytes(data)
            data = await asyncio.wait_for(read(), 10)
            validate_media(data, mime, kind)
            method = media.identify if kind == "image" else media.transcribe
            try:
                return await asyncio.wait_for(run_in_threadpool(method, data, mime), 25)
            except asyncio.TimeoutError:
                raise MediaFailure(504, "media_timeout") from None
        except asyncio.TimeoutError:
            raise HTTPException(408, "media_upload_timeout") from None
        except MediaFailure as exc:
            raise HTTPException(exc.status, exc.code, headers={"Retry-After": "30"} if exc.status == 429 else None) from None
        finally:
            media_slots.release()

    @application.post("/api/shopping/visual")
    async def visual_search(request: Request, session_id: UUID | None = None):
        return await process_media(request, "image", session_id)

    @application.post("/api/media/transcribe")
    async def transcribe(request: Request, session_id: UUID | None = None):
        return await process_media(request, "audio", session_id)

    @application.get("/health")
    def health():
        if not application.state.data_ready:
            raise HTTPException(503, "Data services are not initialized")
        return {"status": "ok"}

    @application.get("/api/providers")
    def provider_status():
        return {"data_mode": settings.data_mode,
            "flights": {"provider": "Aviasales / Travelpayouts", "configured": bool(settings.travelpayouts_token),
                        "price_type": "cached", "availability": False, "reservations": False},
            "shopping": {"provider": settings.shopping_provider if settings.shopping_provider in {"birmarket", "ebay"} else "buywhere",
                         "mode": settings.shopping_provider,
                         "authorized_catalog": False if settings.shopping_provider == "birmarket" else
                             bool(settings.ebay_token or settings.ebay_client_id and settings.ebay_client_secret) if settings.shopping_provider == "ebay" else True,
                         "api_key_required": settings.shopping_provider == "ebay",
                         "market": settings.buywhere_market if settings.shopping_provider in {"auto", "buywhere"} else None},
            "cinema": {"provider": "CinemaPlus Azerbaijan", "documented_public_api": False,
                       "mode": settings.cinema_provider, "public_listings": settings.cinema_provider != "tmdb",
                       "public_showtimes": settings.cinema_provider != "tmdb", "seat_availability": False,
                       "metadata_provider": "TMDB" if settings.tmdb_token else None}}

    @application.post("/api/chat", response_model=ChatResponse, response_model_exclude_none=True)
    def chat(body: ChatRequest, request: Request):
        return process_chat(body, request)

    def process_chat(body, request, emit=None):
        if not application.state.data_ready:
            raise HTTPException(503, "Data services are not initialized")
        try:
            owner = request.state.owner
            if body.session_id is not None and owners.get(body.session_id) != owner:
                raise SessionNotFound()
            if body.request_id is None:
                check_rate(request)
                result = service.chat(body.message, body.session_id, body.language, emit=emit, refresh_cache=body.refresh_cache, domain_hint=body.domain_hint)
                owners[result.session_id] = owner
                return result
            key = (owner, body.request_id)
            fingerprint = (body.message, body.session_id, body.language, body.refresh_cache, body.domain_hint)
            with guard:
                lock = request_locks.setdefault(key, RLock())
            with lock:
                if key in cached_requests:
                    previous, result = cached_requests[key]
                    if previous != fingerprint:
                        raise HTTPException(409, "Request ID was already used for another message")
                    return result
                check_rate(request)
                result = service.chat(body.message, body.session_id, body.language, emit=emit, refresh_cache=body.refresh_cache, domain_hint=body.domain_hint)
                owners[result.session_id] = owner
                cached_requests[key] = (fingerprint, result)
                return result
        except SessionNotFound:
            raise HTTPException(404, "Session not found") from None
        except RouterUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except InvalidRouterResponse:
            raise HTTPException(502, "Routing service returned an invalid result") from None
        except RequestTimeout:
            raise HTTPException(504, "The request took too long. Your saved conversation is safe; please retry.") from None

    @application.post("/api/chat/stream")
    def stream_chat(body: ChatRequest, request: Request):
        # Check ownership before starting a stream or consuming provider capacity.
        if not application.state.data_ready:
            raise HTTPException(503, "Data services are not initialized")
        if body.session_id is not None and owners.get(body.session_id) != request.state.owner:
            raise HTTPException(404, "Session not found")
        if body.request_id is None:
            raise HTTPException(422, "Streaming requires a request ID for safe retries")
        if not streaming_slots.acquire(blocking=False):
            raise HTTPException(429, "The assistant is busy. Please retry shortly.", headers={"Retry-After": "5"})
        events = Queue()
        def produce():
            try:
                result = process_chat(body, request, emit=lambda event, data: events.put((event, data)))
                events.put(("complete", result.model_dump(mode="json", exclude_none=True)))
            except HTTPException as exc:
                events.put(("error", {"status": exc.status_code,
                    "code": {429: "rate_limited", 504: "timeout", 404: "session_not_found", 409: "request_conflict"}.get(exc.status_code, "request_failed"),
                    "retry_after": int((exc.headers or {}).get("Retry-After", "0"))}))
            except Exception:
                # No exception body, stack, prompt or upstream payload reaches SSE.
                events.put(("error", {"status": 500, "code": "request_failed"}))
            finally:
                events.put(("done", {}))
                streaming_slots.release()
        Thread(target=produce, daemon=True, name="superchat-stream").start()
        def stream():
            yield 'event: progress\ndata: {"step":"starting"}\n\n'
            while True:
                try:
                    event, data = events.get(timeout=5)
                except Empty:
                    yield ": keep-alive\n\n"
                    continue
                if event == "done":
                    return
                yield "event: " + event + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"})

    @application.get("/api/session/{session_id}", response_model=SessionState,
                     response_model_exclude_none=True)
    def session(session_id: UUID, request: Request):
        try:
            if owners.get(session_id) != request.state.owner:
                raise SessionNotFound()
            return sessions.get(session_id)
        except SessionNotFound:
            raise HTTPException(404, "Session not found") from None

    return application


app = create_app()
