"""Admin-only endpoints (docs/api/staff-api.md: Administration). Role checked by the `Admin` dependency."""

import datetime as dt
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from clinic.api.deps import Admin, Api
from clinic.db.models import ClinicInfo
from clinic.services.admin import Block, DoctorOut, StaffUserOut
from clinic.services.staff_ops import AppointmentOut

router = APIRouter(tags=["admin"])

TOPIC = re.compile(r"^[a-z0-9_]{1,40}$")


class DoctorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    specialty: str = Field(min_length=2, max_length=80)


class DoctorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=80)
    specialty: str | None = Field(default=None, min_length=2, max_length=80)
    active: bool | None = None


class BlockIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekday: int = Field(ge=0, le=6)
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")
    slot_minutes: int = Field(ge=5, le=120)


class ScheduleIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocks: list[BlockIO] = Field(max_length=70)


class LeaveDay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: dt.date


class LeaveIn(LeaveDay):
    reason: str = Field(min_length=1, max_length=200)
    confirm_affected: bool = False


class FaqIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(pattern=TOPIC.pattern)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    answer: str = Field(min_length=1, max_length=2000)


class FaqPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str | None = Field(default=None, pattern=TOPIC.pattern)
    aliases: list[str] | None = Field(default=None, max_length=20)
    answer: str | None = Field(default=None, min_length=1, max_length=2000)


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clinic_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=3, max_length=30)
    address: str | None = Field(default=None, min_length=3, max_length=300)
    staff_hours_text: str | None = Field(default=None, min_length=3, max_length=120)
    timezone: str | None = Field(default=None, min_length=3, max_length=64)
    emergency_number: str | None = Field(default=None, min_length=2, max_length=20)
    emergency_phrases: list[str] | None = Field(default=None, max_length=100)
    cutoff_minutes: int | None = Field(default=None, ge=0, le=10080)
    booking_window_days: int | None = Field(default=None, ge=1, le=365)
    max_upcoming_per_patient: int | None = Field(default=None, ge=1, le=20)
    max_per_doctor_per_day: int | None = Field(default=None, ge=1, le=10)
    morning_end: dt.time | None = None
    afternoon_end: dt.time | None = None

    @field_validator("emergency_phrases")
    @classmethod
    def _phrases(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [p.strip() for p in value if p.strip()]


class StaffUserIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=40)
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal["receptionist", "admin"]
    password: str = Field(min_length=12, max_length=256)


class StaffUserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["receptionist", "admin"] | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


@dataclass(frozen=True)
class Items[T]:
    items: list[T]


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True)
class FaqOut:
    id: UUID
    topic: str
    aliases: list[str]
    answer: str
    updated_at: dt.datetime


def _faq(entry: ClinicInfo) -> FaqOut:
    return FaqOut(entry.id, entry.topic, list(entry.aliases), entry.answer, entry.updated_at)


def _blocks(blocks: list[Block]) -> ScheduleIO:
    return ScheduleIO(
        blocks=[
            BlockIO(
                weekday=b.weekday,
                start=b.start.strftime("%H:%M"),
                end=b.end.strftime("%H:%M"),
                slot_minutes=b.slot_minutes,
            )
            for b in blocks
        ]
    )


@router.post("/doctors", status_code=201)
async def create_doctor(body: DoctorIn, principal: Admin, api: Api) -> DoctorOut:
    return await api.admin.create_doctor(principal, body.name, body.specialty)


@router.patch("/doctors/{doctor_id}")
async def update_doctor(doctor_id: UUID, body: DoctorPatch, principal: Admin, api: Api) -> DoctorOut:
    return await api.admin.update_doctor(principal, doctor_id, body.model_dump(exclude_unset=True))


@router.get("/doctors/{doctor_id}/schedule")
async def get_schedule(doctor_id: UUID, principal: Admin, api: Api) -> ScheduleIO:
    return _blocks(await api.admin.schedule(doctor_id))


@router.put("/doctors/{doctor_id}/schedule")
async def put_schedule(doctor_id: UUID, body: ScheduleIO, principal: Admin, api: Api) -> ScheduleIO:
    blocks = [
        Block(b.weekday, dt.time.fromisoformat(b.start), dt.time.fromisoformat(b.end), b.slot_minutes)
        for b in body.blocks
    ]
    return _blocks(await api.admin.replace_schedule(principal, doctor_id, blocks))


@router.get("/doctors/{doctor_id}/leaves")
async def list_leaves(doctor_id: UUID, principal: Admin, api: Api) -> Items[dict[str, Any]]:
    return Items(await api.admin.leaves(doctor_id))


@router.post("/doctors/{doctor_id}/leaves/preview")
async def preview_leave(
    doctor_id: UUID, body: LeaveDay, principal: Admin, api: Api
) -> dict[str, list[AppointmentOut]]:
    return {"affected": await api.admin.preview_leave(doctor_id, body.date)}


@router.post("/doctors/{doctor_id}/leaves", status_code=201)
async def create_leave(doctor_id: UUID, body: LeaveIn, principal: Admin, api: Api) -> dict[str, Any]:
    leave, cancelled = await api.admin.create_leave(
        principal, doctor_id, body.date, body.reason.strip(), body.confirm_affected
    )
    return {"leave": leave, "cancelled": cancelled}


@router.delete("/doctors/{doctor_id}/leaves/{leave_id}", status_code=204)
async def delete_leave(doctor_id: UUID, leave_id: UUID, principal: Admin, api: Api) -> Response:
    await api.admin.delete_leave(principal, doctor_id, leave_id)
    return Response(status_code=204)


@router.get("/faq")
async def list_faq(principal: Admin, api: Api) -> Items[FaqOut]:
    return Items([_faq(e) for e in await api.admin.faq()])


@router.post("/faq", status_code=201)
async def create_faq(body: FaqIn, principal: Admin, api: Api) -> FaqOut:
    return _faq(await api.admin.save_faq(principal, None, body.model_dump()))


@router.patch("/faq/{entry_id}")
async def update_faq(entry_id: UUID, body: FaqPatch, principal: Admin, api: Api) -> FaqOut:
    return _faq(await api.admin.save_faq(principal, entry_id, body.model_dump(exclude_unset=True)))


@router.delete("/faq/{entry_id}", status_code=204)
async def delete_faq(entry_id: UUID, principal: Admin, api: Api) -> Response:
    await api.admin.delete_faq(principal, entry_id)
    return Response(status_code=204)


@router.get("/settings")
async def get_settings(principal: Admin, api: Api) -> dict[str, Any]:
    return await api.admin.get_settings()


@router.patch("/settings")
async def patch_settings(body: SettingsPatch, principal: Admin, api: Api) -> dict[str, Any]:
    return await api.admin.update_settings(principal, body.model_dump(exclude_unset=True))


@router.get("/audit")
async def audit(
    principal: Admin,
    api: Api,
    start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    actor_type: Annotated[Literal["agent", "staff", "system", "patient_button"] | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    patient_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page:
    filters = {"from": start, "to": end, "actor_type": actor_type, "action": action, "patient_id": patient_id}
    items, total = await api.admin.audit(filters, page, page_size)
    return Page(items, page, page_size, total)


@router.get("/metrics/weekly")
async def weekly_metrics(
    principal: Admin, api: Api, week_start: Annotated[dt.date, Query()]
) -> dict[str, Any]:
    return await api.admin.weekly_metrics(week_start)


@router.get("/staff-users")
async def list_staff_users(principal: Admin, api: Api) -> Items[StaffUserOut]:
    return Items(await api.admin.staff_users())


@router.post("/staff-users", status_code=201)
async def create_staff_user(body: StaffUserIn, principal: Admin, api: Api) -> StaffUserOut:
    return await api.admin.create_staff_user(
        principal, body.username, body.display_name, body.role, body.password
    )


@router.patch("/staff-users/{user_id}")
async def update_staff_user(user_id: UUID, body: StaffUserPatch, principal: Admin, api: Api) -> StaffUserOut:
    return await api.admin.update_staff_user(principal, user_id, body.model_dump(exclude_unset=True))


@router.post("/staff-users/{user_id}/unlock")
async def unlock_staff_user(user_id: UUID, principal: Admin, api: Api) -> StaffUserOut:
    return await api.admin.unlock_staff_user(principal, user_id)
