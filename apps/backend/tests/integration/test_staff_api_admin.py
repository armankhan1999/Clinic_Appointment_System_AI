"""Staff API administration: IMP-01..05, E6-S3, E6-S6, E7-S2-AC3, E5-S1-AC3, E4-S4 (docs/api/staff-api.md)."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.config import Settings
from clinic.db.models import Appointment, Doctor, Notification
from clinic.services.doctors import DoctorService

from .api_harness import add_staff, api_client, login
from .factories import add_schedule, make_appointment, make_clinic_settings, make_doctor, make_patient

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2030, 1, 14, 8, 0, tzinfo=IST)  # Monday


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=IST)


async def _clinic(session_factory: Factory) -> Doctor:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        await add_schedule(session, doctor, 2, time(9), time(11))  # Wednesday
        await session.commit()
    await add_staff(session_factory, "admin", "admin")
    await add_staff(session_factory, "riya", "receptionist")
    return doctor


async def test_doctors_can_be_added_edited_and_deactivated(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "admin")
        created = await client.post(
            "/api/v1/doctors", json={"name": "Dr. Kavya Rao", "specialty": "Dermatologist"}, headers=csrf
        )
        doctor_id = created.json()["id"]
        renamed = await client.patch(
            f"/api/v1/doctors/{doctor_id}", json={"specialty": "Skin specialist"}, headers=csrf
        )
        await client.patch(f"/api/v1/doctors/{doctor_id}", json={"active": False}, headers=csrf)
    assert created.status_code == 201
    assert renamed.json()["specialty"] == "Skin specialist"
    names = [d.name for d in await DoctorService(session_factory).list_active()]
    assert "Dr. Kavya Rao" not in names, "E2-S1-AC2: inactive doctors disappear from the bot"


async def test_weekly_schedule_is_replaced_and_validated(
    settings: Settings, session_factory: Factory
) -> None:
    doctor = await _clinic(session_factory)
    good = {
        "blocks": [
            {"weekday": 0, "start": "09:00", "end": "13:00", "slot_minutes": 20},
            {"weekday": 0, "start": "14:00", "end": "17:00", "slot_minutes": 20},
        ]
    }
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "admin")
        saved = await client.put(f"/api/v1/doctors/{doctor.id}/schedule", json=good, headers=csrf)
        read = await client.get(f"/api/v1/doctors/{doctor.id}/schedule")
        backwards = await client.put(
            f"/api/v1/doctors/{doctor.id}/schedule",
            json={"blocks": [{"weekday": 1, "start": "13:00", "end": "13:00", "slot_minutes": 15}]},
            headers=csrf,
        )
        overlapping = await client.put(
            f"/api/v1/doctors/{doctor.id}/schedule",
            json={
                "blocks": [
                    {"weekday": 1, "start": "09:00", "end": "12:00", "slot_minutes": 15},
                    {"weekday": 1, "start": "11:00", "end": "13:00", "slot_minutes": 15},
                ]
            },
            headers=csrf,
        )
        slots = await client.get(
            "/api/v1/availability", params={"doctor_id": str(doctor.id), "date": "2030-01-21"}
        )
    assert saved.status_code == 200
    assert read.json()["blocks"] == good["blocks"]
    assert backwards.status_code == 422, "E6-S3-AC2: end must be after start"
    assert backwards.json()["error"]["code"] == "VALIDATION_ERROR"
    assert overlapping.status_code == 422
    labels = [s["time_label"] for s in slots.json()["slots"]]
    assert labels[:3] == ["9:00 AM", "9:20 AM", "9:40 AM"], (
        "E6-S3-AC1: the bot offers slots on the new pattern"
    )


async def test_leave_lists_affected_bookings_and_needs_confirmation(
    settings: Settings, session_factory: Factory
) -> None:
    doctor = await _clinic(session_factory)
    async with session_factory() as session:
        linked = await make_patient(session, telegram_user_id=4242)
        walk_in = await make_patient(session)
        first = await make_appointment(session, doctor=doctor, patient=linked, start=at(16, 9))
        second = await make_appointment(session, doctor=doctor, patient=walk_in, start=at(16, 10))
        await session.commit()
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "admin")
        preview = await client.post(
            f"/api/v1/doctors/{doctor.id}/leaves/preview", json={"date": "2030-01-16"}, headers=csrf
        )
        unconfirmed = await client.post(
            f"/api/v1/doctors/{doctor.id}/leaves",
            json={"date": "2030-01-16", "reason": "Conference", "confirm_affected": False},
            headers=csrf,
        )
        confirmed = await client.post(
            f"/api/v1/doctors/{doctor.id}/leaves",
            json={"date": "2030-01-16", "reason": "Conference", "confirm_affected": True},
            headers=csrf,
        )
        leaves = (await client.get(f"/api/v1/doctors/{doctor.id}/leaves")).json()["items"]
    assert sorted(a["reference"] for a in preview.json()["affected"]) == sorted([first.ref, second.ref])
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["error"]["details"]["affected"] == preview.json()["affected"]
    assert confirmed.status_code == 201
    assert sorted(a["status"] for a in confirmed.json()["cancelled"]) == ["cancelled", "cancelled"]
    assert [(leave["date"], leave["reason"]) for leave in leaves] == [("2030-01-16", "Conference")]
    async with session_factory() as session:
        notices = (await session.scalars(select(Notification))).all()
        statuses = {a.id: a.status for a in (await session.scalars(select(Appointment))).all()}
    assert [(n.appointment_id, n.kind) for n in notices] == [(first.id, "doctor_leave")], (
        "E4-S4: only linked patients"
    )
    assert statuses == {first.id: "cancelled", second.id: "cancelled"}


async def test_faq_entries_are_managed_and_validated(settings: Settings, session_factory: Factory) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "admin")
        created = await client.post(
            "/api/v1/faq",
            json={"topic": "parking", "aliases": ["car"], "answer": "Basement parking."},
            headers=csrf,
        )
        entry_id = created.json()["id"]
        updated = await client.patch(
            f"/api/v1/faq/{entry_id}", json={"answer": "Level 2 parking."}, headers=csrf
        )
        bad_topic = await client.post(
            "/api/v1/faq", json={"topic": "Bad Topic!", "aliases": [], "answer": "x"}, headers=csrf
        )
        duplicate = await client.post(
            "/api/v1/faq", json={"topic": "parking", "aliases": [], "answer": "Again."}, headers=csrf
        )
        other = await client.post(
            "/api/v1/faq", json={"topic": "wifi", "aliases": [], "answer": "Ask reception."}, headers=csrf
        )
        renamed_onto = await client.patch(
            f"/api/v1/faq/{other.json()['id']}", json={"topic": "parking"}, headers=csrf
        )
        await client.delete(f"/api/v1/faq/{other.json()['id']}", headers=csrf)
        listed = (await client.get("/api/v1/faq")).json()["items"]
        deleted = await client.delete(f"/api/v1/faq/{entry_id}", headers=csrf)
    assert created.status_code == 201
    assert updated.json()["answer"] == "Level 2 parking."
    assert bad_topic.status_code == 422
    assert (duplicate.status_code, duplicate.json()["error"]["code"]) == (409, "CONFLICT")
    assert renamed_onto.status_code == 409
    assert [e["topic"] for e in listed] == ["parking"]
    assert deleted.status_code == 204


async def test_settings_can_be_read_and_changed_with_validation(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "admin")
        current = (await client.get("/api/v1/settings")).json()
        changed = await client.patch(
            "/api/v1/settings", json={"cutoff_minutes": 180, "emergency_number": "108"}, headers=csrf
        )
        bad_zone = await client.patch("/api/v1/settings", json={"timezone": "Mars/Base"}, headers=csrf)
        bad_parts = await client.patch("/api/v1/settings", json={"morning_end": "18:00"}, headers=csrf)
    assert current["clinic_name"] == "Demo Family Clinic"
    assert (changed.json()["cutoff_minutes"], changed.json()["emergency_number"]) == (180, "108")
    assert bad_zone.status_code == 422
    assert bad_parts.status_code == 422, "morning must end before the afternoon ends"


async def test_audit_log_is_paginated_and_filtered_for_admins(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        await login(client, "admin")
        page = (await client.get("/api/v1/audit", params={"action": "staff.login", "page_size": 1})).json()
    assert page["page_size"] == 1
    assert page["total"] >= 1
    assert [row["action"] for row in page["items"]] == ["staff.login"]
    fields = "id ts actor_type actor_id patient_id action args result latency_ms request_id"
    assert set(page["items"][0]) == set(fields.split())


async def test_weekly_metrics_count_by_source_and_rate_no_shows(
    settings: Settings, session_factory: Factory
) -> None:
    doctor = await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        await login(client, "admin")
        empty = (await client.get("/api/v1/metrics/weekly", params={"week_start": "2030-01-07"})).json()
    assert empty["bookings_by_source"] == {"bot": 0, "staff": 0}
    assert empty["per_doctor"][0]["no_show_rate"] == 0, "E6-S6-AC2: zeros, never an error"
    async with session_factory() as session:
        patient = await make_patient(session)
        for day, status in ((7, "completed"), (8, "completed"), (9, "no_show"), (10, "completed")):
            appointment = await make_appointment(
                session, doctor=doctor, patient=patient, start=at(day, 9), status="booked"
            )
            appointment.status = status
            appointment.created_at = at(day - 1, 12)
        await session.commit()
    async with api_client(settings, session_factory, lambda: NOW) as client:
        await login(client, "admin")
        week = (await client.get("/api/v1/metrics/weekly", params={"week_start": "2030-01-07"})).json()
    [row] = week["per_doctor"]
    assert (row["completed"], row["no_show"], row["no_show_rate"]) == (3, 1, 0.25)
    assert week["bookings_by_source"]["bot"] == 4


async def test_staff_users_are_provisioned_and_unlocked_by_admins(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "admin")
        weak = await client.post(
            "/api/v1/staff-users",
            json={"username": "neha", "display_name": "Neha", "role": "receptionist", "password": "short"},
            headers=csrf,
        )
        created = await client.post(
            "/api/v1/staff-users",
            json={
                "username": "neha",
                "display_name": "Neha",
                "role": "receptionist",
                "password": "a long enough pass",
            },
            headers=csrf,
        )
        for _ in range(5):
            await client.post("/api/v1/auth/login", json={"username": "riya", "password": "wrong password!"})
        users = (await client.get("/api/v1/staff-users")).json()["items"]
        riya = next(u for u in users if u["username"] == "riya")
        unlocked = await client.post(f"/api/v1/staff-users/{riya['id']}/unlock", headers=csrf)
        relogin = await client.post(
            "/api/v1/auth/login", json={"username": "riya", "password": "front desk password"}
        )
    assert weak.status_code == 422
    assert created.status_code == 201
    assert created.json()["role"] == "receptionist"
    assert "password" not in created.text.lower()
    assert unlocked.status_code == 200
    assert relogin.status_code == 200


async def test_password_reset_ends_the_users_existing_sessions(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with (
        api_client(settings, session_factory, lambda: NOW) as admin,
        api_client(settings, session_factory, lambda: NOW) as front_desk,
    ):
        csrf = await login(admin, "admin")
        await login(front_desk, "riya")
        before = await front_desk.get("/api/v1/auth/me")
        users = (await admin.get("/api/v1/staff-users")).json()["items"]
        riya = next(u for u in users if u["username"] == "riya")
        reset = await admin.patch(
            f"/api/v1/staff-users/{riya['id']}", json={"password": "a brand new passphrase"}, headers=csrf
        )
        after = await front_desk.get("/api/v1/auth/me")
        admin_still_in = await admin.get("/api/v1/auth/me")
    assert (before.status_code, reset.status_code) == (200, 200)
    assert after.status_code == 401, "a reset password must sign out sessions opened with the old one"
    assert admin_still_in.status_code == 200
