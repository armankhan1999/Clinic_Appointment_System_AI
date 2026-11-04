"""Staff API (FastAPI). M1 provides health, readiness and the shared request conventions."""

import asyncio
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from clinic.agent.rate_limit import RateLimiter
from clinic.api import routes_admin, routes_auth, routes_staff
from clinic.api.deps import ApiServices
from clinic.api.errors import ApiError, api_error_handler, error_response, refused_handler
from clinic.config import DbTarget, Settings, get_settings
from clinic.db.session import make_engine, make_session_factory
from clinic.observability import bind_request_id, new_request_id, safe_exception_fields
from clinic.services.admin import AdminService
from clinic.services.availability import AvailabilityService, utc_now
from clinic.services.booking import BookingService
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.staff_auth import StaffAuthService
from clinic.services.staff_ops import OperationRefusedError, StaffOpsService

log = structlog.get_logger(__name__)

type Readiness = Callable[[], Awaitable[bool]]

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
LOGIN_ATTEMPTS_PER_MINUTE = 10
READINESS_TIMEOUT_S = 5.0  # a cold TLS + SCRAM connection to the pooler took 2.7 s (2026-11-03)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}
STATUS_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    422: "VALIDATION_ERROR",
    423: "ACCOUNT_LOCKED",
    429: "RATE_LIMITED",
}


async def _http_error(_: Request, exc: Exception) -> Response:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, STATUS_CODES.get(exc.status_code, "ERROR"), message)


async def _validation_error(_: Request, exc: Exception) -> Response:
    if not isinstance(exc, RequestValidationError):
        raise exc
    # Field locations only: echoing input values could leak personal data into responses and logs.
    fields = sorted({".".join(str(part) for part in err["loc"]) for err in exc.errors()})
    return error_response(
        422, "VALIDATION_ERROR", f"Please check these fields: {', '.join(fields)}", {"fields": fields}
    )


def _probe(session_factory: async_sessionmaker[AsyncSession]) -> Readiness:
    async def probe() -> bool:
        async with session_factory() as session:
            await session.execute(text("select 1"))
        return True

    return probe


def _services(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], clock: Callable[[], datetime]
) -> ApiServices:
    clinic_settings = ClinicSettingsService(session_factory)
    booking = BookingService(session_factory, clinic_settings, clock=clock)
    availability = AvailabilityService(session_factory, clinic_settings, clock=clock)
    auth = StaffAuthService(
        session_factory, secret=settings.auth_secret.get_secret_value().encode(), clock=clock
    )
    return ApiServices(
        settings=settings,
        session_factory=session_factory,
        auth=auth,
        ops=StaffOpsService(session_factory, clinic_settings, booking, availability, clock=clock),
        admin=AdminService(session_factory, clinic_settings, auth, clock=clock),
        login_limiter=RateLimiter(max_messages=LOGIN_ATTEMPTS_PER_MINUTE),
    )


def create_app(
    settings: Settings | None = None,
    *,
    readiness: Readiness | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    settings = settings or get_settings()
    dispose: Callable[[], Awaitable[None]] | None = None
    if session_factory is None:
        engine = make_engine(DbTarget.app(settings), settings)
        session_factory = make_session_factory(engine)
        dispose = engine.dispose
    probe = readiness or _probe(session_factory)
    development = settings.env == "development"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if dispose is not None:
            await dispose()

    app = FastAPI(
        title="Clinic staff API",
        version="0.1.0",
        docs_url="/api/v1/docs" if development else None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json" if development else None,
        lifespan=lifespan,
    )
    app.state.services = _services(settings, session_factory, clock)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(OperationRefusedError, refused_handler)
    app.include_router(routes_auth.router, prefix="/api/v1")
    app.include_router(routes_staff.router, prefix="/api/v1")
    app.include_router(routes_admin.router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else new_request_id()
        started = time.perf_counter()
        with bind_request_id(request_id):
            try:
                response = await call_next(request)
            except Exception as exc:
                log.error(
                    "http_unhandled_error",
                    method=request.method,
                    path=request.url.path,
                    **safe_exception_fields(exc),
                )
                response = error_response(500, "ERROR", "Something went wrong. Please try again.")
            response.headers["X-Request-ID"] = request_id
            response.headers.update(SECURITY_HEADERS)
            # Path only: query strings can carry personal data such as a phone lookup.
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            return response

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        try:
            async with asyncio.timeout(READINESS_TIMEOUT_S):
                is_ready = await probe()
        except Exception as exc:  # any probe failure means "not ready"; logged, never echoed
            log.warning("readiness_failed", error=type(exc).__name__)
            is_ready = False
        if is_ready:
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    return app
