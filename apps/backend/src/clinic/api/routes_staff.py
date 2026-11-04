"""Receptionist endpoints (docs/api/staff-api.md: Daily work). Every route needs a staff session."""

import datetime as dt
from dataclasses import dataclass
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select

from clinic.api.deps import Api, Staff
from clinic.db.models import Doctor
from clinic.services.staff_ops import (
    AppointmentOut,
    AttentionPanelOut,
    DoctorDayOut,
    NewPatient,
    PatientRefOut,
)

router = APIRouter(tags=["daily"])


@dataclass(frozen=True)
class ScheduleOut:
    date: dt.date
    doctors: list[DoctorDayOut]


@dataclass(frozen=True)
class DoctorOut:
    id: UUID
    name: str
    specialty: str
    active: bool


@dataclass(frozen=True)
class Items[T]:
    items: list[T]


@dataclass(frozen=True)
class SlotOut:
    start: str
    time_label: str


@dataclass(frozen=True)
class AvailabilityOut:
    date: dt.date
    slots: list[SlotOut]


class PatientById(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID


class PatientNewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=60)
    phone: str = Field(min_length=3, max_length=30)
    verbal_consent: bool


class BookIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doctor_id: UUID
    start: AwareDatetime
    patient: PatientById | PatientNewIn


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=200)


class AttendanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "no_show"]


@router.get("/schedule")
async def schedule(principal: Staff, api: Api, date: Annotated[dt.date, Query()]) -> ScheduleOut:
    return ScheduleOut(date, await api.ops.schedule(date))


@dataclass(frozen=True)
class ClinicTodayOut:
    date: dt.date
    timezone: str


@router.get("/clinic/today")
async def clinic_today(principal: Staff, api: Api) -> ClinicTodayOut:
    day, timezone = await api.ops.clinic_today()
    return ClinicTodayOut(day, timezone)


@router.get("/attention")
async def attention(principal: Staff, api: Api) -> AttentionPanelOut:
    return await api.ops.attention()


@router.get("/doctors")
async def doctors(
    principal: Staff, api: Api, active: Annotated[bool | None, Query()] = None
) -> Items[DoctorOut]:
    async with api.session_factory() as session:
        query = select(Doctor).order_by(Doctor.name)
        if active is not None:
            query = query.where(Doctor.active.is_(active))
        rows = (await session.scalars(query)).all()
    return Items([DoctorOut(d.id, d.name, d.specialty, d.active) for d in rows])


@router.get("/availability")
async def availability(
    principal: Staff, api: Api, doctor_id: Annotated[UUID, Query()], date: Annotated[dt.date, Query()]
) -> AvailabilityOut:
    slots = await api.ops.free_slots(doctor_id, date)
    return AvailabilityOut(date, [SlotOut(s["start"], s["time_label"]) for s in slots])


class PhoneLookupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=3, max_length=30)


@router.post("/patients/lookup")
async def patients(body: PhoneLookupIn, principal: Staff, api: Api) -> Items[PatientRefOut]:
    """Exact match on the normalised phone. A POST body keeps the number out of URLs and their logs (L1)."""
    return Items(await api.ops.find_patients(body.phone))


@router.post("/appointments", status_code=201)
async def book(body: BookIn, principal: Staff, api: Api) -> AppointmentOut:
    if isinstance(body.patient, PatientById):
        return await api.ops.book(
            principal,
            doctor_id=body.doctor_id,
            start=body.start,
            patient_id=body.patient.id,
            new_patient=None,
        )
    new = NewPatient(body.patient.full_name, body.patient.phone, body.patient.verbal_consent)
    return await api.ops.book(
        principal, doctor_id=body.doctor_id, start=body.start, patient_id=None, new_patient=new
    )


@router.post("/appointments/{appointment_id}/cancel")
async def cancel(appointment_id: UUID, body: CancelIn, principal: Staff, api: Api) -> AppointmentOut:
    return await api.ops.cancel(principal, appointment_id, body.reason.strip())


@router.post("/appointments/{appointment_id}/attendance")
async def attendance(appointment_id: UUID, body: AttendanceIn, principal: Staff, api: Api) -> AppointmentOut:
    return await api.ops.mark_attendance(principal, appointment_id, body.status)


@router.post("/appointments/{appointment_id}/clear-attention")
async def clear_attention(appointment_id: UUID, principal: Staff, api: Api) -> AppointmentOut:
    return await api.ops.clear_attention(principal, appointment_id)


@router.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: UUID, principal: Staff, api: Api) -> dict[str, Any]:
    return await api.ops.resolve_ticket(principal, ticket_id)


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: UUID, principal: Staff, api: Api) -> dict[str, Any]:
    return await api.ops.acknowledge_alert(principal, alert_id)
