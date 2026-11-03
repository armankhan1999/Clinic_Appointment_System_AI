"""Agent tools (TOOL-01..08). Arguments are Pydantic-validated; identity comes from ToolContext only."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from clinic.agent.pending import PendingAction, PendingKind
from clinic.domain.dates import Ambiguous, Resolved, resolve_date
from clinic.domain.results import ResultCode
from clinic.domain.slots import PartOfDay, format_date_long, format_time_12h
from clinic.services.availability import AvailabilityService, DayAvailability
from clinic.services.booking import BookingService
from clinic.services.doctors import DoctorService

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class AgentServices:
    doctors: DoctorService
    availability: AvailabilityService
    booking: BookingService


type Stager = Callable[[PendingKind, Mapping[str, Any]], PendingAction]


@dataclass(frozen=True)
class ToolContext:
    """Built by code from the authenticated session, never from LLM output (E2-S3-AC5)."""

    patient_id: UUID
    request_id: str
    services: AgentServices | None = None
    stage: Stager | None = None  # stages a write for the patient's Confirm tap (AGT-11)

    def require_services(self) -> AgentServices:
        if self.services is None:
            raise RuntimeError("tool context has no services")
        return self.services

    def require_stage(self) -> Stager:
        if self.stage is None:
            raise RuntimeError("tool context cannot stage confirmations")
        return self.stage


@dataclass(frozen=True)
class ToolResult:
    code: ResultCode
    data: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        return {"code": self.code.value, "data": self.data}


@dataclass(frozen=True)
class ToolSpec[A: BaseModel]:
    name: str
    description: str
    args_model: type[A]
    executor: Callable[[ToolContext, A], Awaitable[ToolResult]]


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec[Any]]) -> None:
        self._specs = {spec.name: spec for spec in specs}

    def get(self, name: str) -> ToolSpec[Any] | None:
        return self._specs.get(name)

    @property
    def specs(self) -> list[ToolSpec[Any]]:
        return list(self._specs.values())


def _simplify(node: Any, *, field_map: bool = False) -> Any:
    """Pydantic JSON schema → the plain subset function-calling APIs accept (no titles, no null unions).

    Inside a `properties` map the keys are argument names, so they are kept even when an argument is
    called `title` or `default`.
    """
    if isinstance(node, list):
        return [_simplify(item) for item in node]
    if not isinstance(node, dict):
        return node
    if field_map:
        return {name: _simplify(schema) for name, schema in node.items()}
    if "$defs" in node or "$ref" in node:
        raise NotImplementedError("nested models are not supported in tool arguments")
    result = {
        key: _simplify(value, field_map=key == "properties")
        for key, value in node.items()
        if key not in {"title", "default"}
    }
    variants = result.pop("anyOf", None)
    if variants is not None:
        non_null = [v for v in variants if v.get("type") != "null"]
        if len(non_null) != 1:
            raise NotImplementedError("only Optional[X] unions are supported in tool arguments")
        result = {**non_null[0], **result}
    return result


def tool_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema: dict[str, Any] = _simplify(model.model_json_schema())
    return schema


class ListDoctorsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specialty: str | None = Field(
        default=None,
        max_length=40,
        description="Optional specialty to filter by, for example 'dermatology'. Omit to list every doctor.",
    )


async def list_doctors(ctx: ToolContext, args: ListDoctorsArgs) -> ToolResult:
    """TOOL-01 / E2-S1: active doctors with specialty and working days; NO_MATCH when none fit."""
    doctors = await ctx.require_services().doctors.list_active(args.specialty)
    if not doctors:
        return ToolResult(ResultCode.NO_MATCH, {"doctors": []})
    return ToolResult(
        ResultCode.OK,
        {
            "doctors": [
                {
                    "doctor_id": str(doctor.id),
                    "name": doctor.name,
                    "specialty": doctor.specialty,
                    "working_days": [WEEKDAY_NAMES[day] for day in doctor.working_weekdays],
                }
                for doctor in doctors
            ]
        },
    )


LIST_DOCTORS = ToolSpec(
    name="list_doctors",
    description=(
        "List the clinic's active doctors with their specialty and working days. "
        "Use it whenever the patient asks which doctors or specialties are available."
    ),
    args_model=ListDoctorsArgs,
    executor=list_doctors,
)


class CheckAvailabilityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doctor_id: UUID = Field(description="The doctor_id returned by list_doctors.")
    date: str = Field(
        min_length=1,
        max_length=40,
        description=(
            "The day the patient asked for, exactly as they said it or as YYYY-MM-DD: for example 'today', "
            "'tomorrow', 'day after tomorrow', 'next Monday', '12 January' or 'the 5th'. Do not convert it."
        ),
    )
    part_of_day: Literal["morning", "afternoon", "evening"] | None = Field(
        default=None, description="Only when the patient asked for a part of the day."
    )


def _day(day: Any) -> dict[str, str]:
    return {"date": format_date_long(day), "date_iso": day.isoformat()}


def _availability_payload(result: DayAvailability, max_slots: int) -> dict[str, Any]:
    data: dict[str, Any] = {"doctor": result.doctor_name, **_day(result.day)}
    if result.slots:
        data["slots"] = [
            {"slot_start": slot.start.isoformat(), "time": format_time_12h(slot.start)}
            for slot in result.slots[:max_slots]
        ]
    if result.next_dates:
        data["next_dates_with_free_slots"] = [_day(day) for day in result.next_dates]
    if result.next_working_day is not None:
        data["next_working_day"] = _day(result.next_working_day)
    if result.other_parts:
        data["other_parts_of_day_with_slots"] = [part.value for part in result.other_parts]
    return data


MAX_SLOTS_SHOWN = 5  # E2-S2-AC1


async def check_availability(ctx: ToolContext, args: CheckAvailabilityArgs) -> ToolResult:
    """TOOL-02 / E2-S2: the date phrase is resolved by code in the clinic time zone (GAP-36)."""
    availability = ctx.require_services().availability
    view = await availability.settings()
    today = availability.now().astimezone(view.tz).date()
    resolution = resolve_date(args.date, today)
    if isinstance(resolution, Ambiguous):
        return ToolResult(ResultCode.AMBIGUOUS_DATE, {"ask_patient": "Which month do you mean?"})
    if not isinstance(resolution, Resolved):
        return ToolResult(
            ResultCode.INVALID_DATE,
            {"problem": "The date was not understood. Ask for a day such as 'tomorrow' or '12 January'."},
        )
    part = PartOfDay(args.part_of_day) if args.part_of_day else None
    result = await availability.day(args.doctor_id, resolution.day, part)
    if result.code is ResultCode.INVALID_DATE:
        return ToolResult(
            ResultCode.INVALID_DATE,
            {
                **_day(result.day),
                "problem": (
                    f"Appointments can be booked from today up to {view.booking_window_days} days ahead."
                ),
            },
        )
    if result.code is ResultCode.NOT_FOUND:
        return ToolResult(ResultCode.NOT_FOUND, {"problem": "No active doctor has that doctor_id."})
    return ToolResult(result.code, _availability_payload(result, MAX_SLOTS_SHOWN))


CHECK_AVAILABILITY = ToolSpec(
    name="check_availability",
    description=(
        "Find free appointment slots for one doctor on one day. Returns up to 5 slots with their slot_start "
        "values, or the next dates that have free slots. Always use it before naming any time."
    ),
    args_model=CheckAvailabilityArgs,
    executor=check_availability,
)


class BookAppointmentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doctor_id: UUID = Field(description="The doctor_id returned by list_doctors.")
    slot_start: AwareDatetime = Field(
        description="Exactly one slot_start value returned by check_availability in this conversation."
    )


LIMIT_REASONS = {
    "same_doctor_same_day": "The patient already has an appointment with this doctor on the same day.",
    "max_upcoming": "The patient already has the maximum number of upcoming appointments.",
}


async def book_appointment(ctx: ToolContext, args: BookAppointmentArgs) -> ToolResult:
    """TOOL-03 / E2-S3-AC1: checks the slot and limits, writes nothing, stages a Confirm for the patient."""
    services = ctx.require_services()
    view = await services.availability.settings()
    check = await services.booking.precheck(ctx.patient_id, args.doctor_id, args.slot_start)
    if check.code is ResultCode.NOT_FOUND:
        return ToolResult(ResultCode.NOT_FOUND, {"problem": "No active doctor has that doctor_id."})
    if check.code is ResultCode.LIMIT_REACHED and check.reason is not None:
        return ToolResult(ResultCode.LIMIT_REACHED, {"reason": LIMIT_REASONS[check.reason]})
    if check.code is not ResultCode.OK or check.slot is None:
        return ToolResult(
            ResultCode.SLOT_UNAVAILABLE,
            {"problem": "That time is not free. Call check_availability and offer only its slots."},
        )
    local_start = check.slot.start.astimezone(view.tz)
    summary = {
        "doctor": check.doctor_name,
        "date": format_date_long(local_start.date()),
        "time": format_time_12h(local_start),
    }
    ctx.require_stage()(
        "book", {"doctor_id": str(args.doctor_id), "slot_start": check.slot.start.isoformat(), **summary}
    )
    return ToolResult(
        ResultCode.PENDING_CONFIRMATION,
        {
            **summary,
            "next_step": (
                "Nothing is booked yet. The patient now sees this summary with Confirm and Change buttons. "
                "Ask them to tap Confirm. Do not say the appointment is booked."
            ),
        },
    )


BOOK_APPOINTMENT = ToolSpec(
    name="book_appointment",
    description=(
        "Prepare a booking for the patient to confirm. Use only a slot_start returned by check_availability. "
        "The booking is made only after the patient taps Confirm."
    ),
    args_model=BookAppointmentArgs,
    executor=book_appointment,
)


def build_registry() -> ToolRegistry:
    return ToolRegistry([LIST_DOCTORS, CHECK_AVAILABILITY, BOOK_APPOINTMENT])
