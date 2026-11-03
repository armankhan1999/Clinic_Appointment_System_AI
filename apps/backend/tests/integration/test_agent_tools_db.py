"""list_doctors against the database (E2-S1-AC1..AC3) and the audit sink (E7-S2-AC1)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.loop import AuditEntry, db_audit_writer
from clinic.agent.tools import ListDoctorsArgs, ToolContext, list_doctors
from clinic.db.models import AuditLog
from clinic.domain.results import ResultCode

from .factories import agent_services, make_doctor

Factory = async_sessionmaker[AsyncSession]


def _ctx(session_factory: Factory) -> ToolContext:
    services = agent_services(session_factory)
    return ToolContext(uuid.uuid4(), "req-tool", services)


async def test_list_doctors_returns_active_doctors_only(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_doctor(session, name="Dr. Skin", specialty="Dermatologist")
        await make_doctor(session, name="Dr. Gone", specialty="Dermatologist", active=False)
        await session.commit()
    result = await list_doctors(_ctx(session_factory), ListDoctorsArgs())
    assert result.code == ResultCode.OK
    assert [d["name"] for d in result.data["doctors"]] == ["Dr. Skin"]
    assert set(result.data["doctors"][0]) == {"doctor_id", "name", "specialty", "working_days"}


async def test_unknown_specialty_is_no_match(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_doctor(session, name="Dr. Skin", specialty="Dermatologist")
        await session.commit()
    result = await list_doctors(_ctx(session_factory), ListDoctorsArgs(specialty="neurology"))
    assert result.code == ResultCode.NO_MATCH
    assert result.data == {"doctors": []}


async def test_db_audit_writer_persists_the_entry(session_factory: Factory) -> None:
    patient_id = uuid.uuid4()
    entry = AuditEntry("gemini-x", "list_doctors", {"specialty": "derma"}, "OK", patient_id, 12, "req-9")
    await db_audit_writer(session_factory)(entry)
    async with session_factory() as session:
        row = await session.scalar(select(AuditLog))
    assert row is not None
    assert (row.actor_type, row.actor_id, row.action, row.result) == (
        "agent",
        "gemini-x",
        "list_doctors",
        "OK",
    )
    assert (row.args_json, row.patient_id, row.latency_ms, row.request_id) == (
        {"specialty": "derma"},
        patient_id,
        12,
        "req-9",
    )
