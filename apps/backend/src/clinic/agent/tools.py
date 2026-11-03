"""Agent tools (TOOL-01..08). Arguments are Pydantic-validated; identity comes from ToolContext only."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from clinic.domain.results import ResultCode
from clinic.services.doctors import DoctorService

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class AgentServices:
    doctors: DoctorService


@dataclass(frozen=True)
class ToolContext:
    """Built by code from the authenticated session, never from LLM output (E2-S3-AC5)."""

    patient_id: UUID
    request_id: str
    services: AgentServices | None = None

    def require_services(self) -> AgentServices:
        if self.services is None:
            raise RuntimeError("tool context has no services")
        return self.services


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


def _simplify(node: Any) -> Any:
    """Pydantic JSON schema → the plain subset function-calling APIs accept (no titles, no null unions)."""
    if isinstance(node, list):
        return [_simplify(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "$defs" in node or "$ref" in node:
        raise NotImplementedError("nested models are not supported in tool arguments")
    result = {key: _simplify(value) for key, value in node.items() if key not in {"title", "default"}}
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


def build_registry() -> ToolRegistry:
    return ToolRegistry([LIST_DOCTORS])
