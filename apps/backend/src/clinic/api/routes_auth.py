"""`/api/v1/auth/*` (E6-S1): login with lockout and per-client throttling, logout, current user."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from clinic.api.deps import SESSION_COOKIE, Api, Staff, client_key
from clinic.api.errors import ApiError
from clinic.domain.results import ResultCode
from clinic.services.staff_auth import SESSION_ABSOLUTE, StaffPrincipal, csrf_token_for

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


@dataclass(frozen=True)
class StaffUserOut:
    id: UUID
    username: str
    display_name: str
    role: str
    active: bool


@dataclass(frozen=True)
class SessionOut:
    user: StaffUserOut
    csrf_token: str


def _user(principal: StaffPrincipal) -> StaffUserOut:
    return StaffUserOut(principal.user_id, principal.username, principal.display_name, principal.role, True)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, api: Api) -> SessionOut:
    if api.login_limiter.check(client_key(request)) != "ok":
        raise ApiError(429, ResultCode.RATE_LIMITED, "Too many sign-in attempts. Please wait a minute.")
    result = await api.auth.login(body.username, body.password)
    if result.code is ResultCode.ACCOUNT_LOCKED and result.locked_until is not None:
        raise ApiError(
            423,
            ResultCode.ACCOUNT_LOCKED,
            "This account is locked after too many failed attempts. Please try again later.",
            {"locked_until": result.locked_until.isoformat()},
        )
    if result.code is not ResultCode.OK or result.principal is None or result.session_token is None:
        raise ApiError(401, ResultCode.UNAUTHENTICATED, "Wrong username or password.")
    response.set_cookie(
        SESSION_COOKIE,
        result.session_token,
        max_age=int(SESSION_ABSOLUTE.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=api.settings.env == "production",
        path="/",
    )
    return SessionOut(_user(result.principal), csrf_token_for(result.session_token))


@router.post("/logout", status_code=204)
async def logout(response: Response, principal: Staff, api: Api) -> None:
    await api.auth.logout(principal.session_id)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(request: Request, principal: Staff) -> SessionOut:
    return SessionOut(_user(principal), csrf_token_for(request.cookies.get(SESSION_COOKIE, "")))
