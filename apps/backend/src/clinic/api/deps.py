"""Request dependencies: the staff principal (session cookie + CSRF on writes) and role checks (E6-S1-AC4)."""

import ipaddress
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.rate_limit import RateLimiter
from clinic.api.errors import ApiError
from clinic.config import Settings
from clinic.services.admin import AdminService
from clinic.services.staff_auth import StaffAuthService, StaffPrincipal, csrf_matches
from clinic.services.staff_ops import StaffOpsService

SESSION_COOKIE = "clinic_session"
CSRF_HEADER = "X-CSRF-Token"
BACKGROUND_HEADER = "X-Background-Refresh"  # set by the dashboard on automatic polls
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class ApiServices:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    auth: StaffAuthService
    ops: StaffOpsService
    admin: AdminService
    login_limiter: RateLimiter


def services(request: Request) -> ApiServices:
    api_services: ApiServices = request.app.state.services
    return api_services


def client_key(request: Request) -> str:
    """The browser's address: the Next.js rewrite on loopback appends it to X-Forwarded-For."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For", "")
    try:
        from_proxy = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        from_proxy = False
    if from_proxy and forwarded:
        return forwarded.split(",")[-1].strip()
    return peer


async def current_staff(request: Request, api: Annotated[ApiServices, Depends(services)]) -> StaffPrincipal:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Please sign in.")
    # Polling is not activity: otherwise a screen left open never reaches the idle limit.
    background = request.method in SAFE_METHODS and request.headers.get(BACKGROUND_HEADER) == "1"
    principal = await api.auth.authenticate(token, touch=not background)
    if principal is None:
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    if request.method not in SAFE_METHODS and not csrf_matches(token, request.headers.get(CSRF_HEADER)):
        raise ApiError(
            403,
            "FORBIDDEN",
            "This request is missing a valid security token. Please reload the page.",
            {"reason": "csrf"},
        )
    return principal


async def require_admin(principal: Annotated[StaffPrincipal, Depends(current_staff)]) -> StaffPrincipal:
    if principal.role != "admin":
        raise HTTPException(403, "Only an admin can do this.")
    return principal


Api = Annotated[ApiServices, Depends(services)]
Staff = Annotated[StaffPrincipal, Depends(current_staff)]
Admin = Annotated[StaffPrincipal, Depends(require_admin)]
