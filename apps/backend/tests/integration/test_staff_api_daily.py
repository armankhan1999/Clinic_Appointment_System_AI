"""Staff API daily work: E6-S1, E6-S2, E6-S4, E6-S5, E5-S4-AC2, E5-S3-AC3, E7-S2-AC3 (staff-api.md)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.config import Settings
from clinic.db.models import (
    Appointment,
    Doctor,
    EmergencyAlert,
    HandoffTicket,
    Notification,
    Patient,
    Reminder,
)

from .api_harness import add_staff, api_client, login
from .factories import add_schedule, make_appointment, make_clinic_settings, make_doctor, make_patient

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2030, 1, 7, 11, 0, tzinfo=IST)  # Monday 11:00


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=IST)


async def _clinic(session_factory: Factory) -> tuple[str, str, str]:
    """Doctor working Mon-Fri 9-11, a Telegram patient with a bot booking today 9:30 (already started)."""
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        for weekday in range(5):
            await add_schedule(session, doctor, weekday, time(9), time(11))
        patient = await make_patient(session, telegram_user_id=4242, name="Asha Rao", phone="+12025550150")
        appointment = await make_appointment(session, doctor=doctor, patient=patient, start=at(7, 9, 30))
        session.add(Reminder(appointment_id=appointment.id, type="24h", status="sent"))
        appointment.patient_confirmed_at = at(6, 20)
        await session.commit()
    await add_staff(session_factory, "riya", "receptionist")
    await add_staff(session_factory, "admin", "admin")
    return str(doctor.id), str(patient.id), str(appointment.id)


async def test_requests_without_a_session_are_unauthenticated(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        response = await client.get("/api/v1/schedule", params={"date": "2030-01-07"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_login_sets_a_protected_cookie_and_me_returns_the_role(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"username": "riya", "password": "front desk password"}
        )
        cookie = response.headers["set-cookie"].lower()
        me = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert "clinic_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert response.json()["user"]["role"] == "receptionist"
    assert me.json()["user"]["username"] == "riya"
    assert me.json()["csrf_token"] == response.json()["csrf_token"]


async def test_wrong_password_and_lockout(settings: Settings, session_factory: Factory) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        codes = [
            (
                await client.post(
                    "/api/v1/auth/login", json={"username": "riya", "password": "wrong password!"}
                )
            ).status_code
            for _ in range(5)
        ]
        locked = await client.post(
            "/api/v1/auth/login", json={"username": "riya", "password": "front desk password"}
        )
    assert codes == [401] * 5
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert "locked_until" in locked.json()["error"]["details"]


async def test_today_is_the_clinic_date_not_the_server_or_pc_date(
    settings: Settings, session_factory: Factory
) -> None:
    """At 00:30 in the clinic it is still the previous day in UTC: the dashboard must use the clinic's day."""
    await _clinic(session_factory)
    just_after_midnight = datetime(2030, 1, 7, 0, 30, tzinfo=IST)  # 2030-01-06 19:00 UTC
    async with api_client(settings, session_factory, lambda: just_after_midnight) as client:
        anonymous = await client.get("/api/v1/clinic/today")
        await login(client, "riya")
        today = await client.get("/api/v1/clinic/today")
    assert anonymous.status_code == 401
    assert today.json() == {"date": "2030-01-07", "timezone": "Asia/Kolkata"}


async def test_writes_need_the_csrf_token(settings: Settings, session_factory: Factory) -> None:
    _, _, appointment_id = await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "riya")
        refused = await client.post(f"/api/v1/appointments/{appointment_id}/clear-attention")
        accepted = await client.post(f"/api/v1/appointments/{appointment_id}/clear-attention", headers=csrf)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"
    assert refused.json()["error"]["details"] == {"reason": "csrf"}, "the UI tells a stale token from a role"
    assert accepted.status_code == 200


async def test_background_refreshes_do_not_keep_an_idle_session_alive(
    settings: Settings, session_factory: Factory
) -> None:
    """A dashboard left open polls every 30 s; only real activity may extend the 60-minute idle limit."""
    await _clinic(session_factory)
    now = [NOW]
    background = {"X-Background-Refresh": "1"}
    async with api_client(settings, session_factory, lambda: now[0]) as client:
        await login(client, "riya")
        now[0] = NOW + timedelta(minutes=50)
        polled = await client.get("/api/v1/attention", headers=background)
        now[0] = NOW + timedelta(minutes=70)
        after_polling_only = await client.get("/api/v1/attention", headers=background)
    async with api_client(settings, session_factory, lambda: now[0]) as client:
        now[0] = NOW
        await login(client, "riya")
        now[0] = NOW + timedelta(minutes=50)
        await client.get("/api/v1/attention")
        now[0] = NOW + timedelta(minutes=70)
        after_activity = await client.get("/api/v1/attention")
    assert polled.status_code == 200
    assert after_polling_only.status_code == 401
    assert after_activity.status_code == 200


async def test_receptionists_cannot_open_admin_screens(settings: Settings, session_factory: Factory) -> None:
    doctor_id, _, _ = await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        await login(client, "riya")
        for path in (
            "/api/v1/audit",
            "/api/v1/faq",
            f"/api/v1/doctors/{doctor_id}/schedule",
            "/api/v1/settings",
        ):
            response = await client.get(path)
            assert response.status_code == 403, path
            assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_schedule_shows_each_doctors_day_with_all_columns(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        await login(client, "riya")
        body = (await client.get("/api/v1/schedule", params={"date": "2030-01-07"})).json()
    [doctor] = body["doctors"]
    [row] = doctor["appointments"]
    assert doctor["name"] == "Dr. Meera Iyer"
    assert (row["time_label"], row["status"], row["source"]) == ("9:30 AM", "booked", "bot")
    assert row["patient"] == {"id": row["patient"]["id"], "full_name": "Asha Rao", "phone": "+12025550150"}
    assert row["reminders"] == {"24h": "sent", "2h": None}
    assert row["patient_confirmed"] is True
    assert row["staff_attention"] is None
    assert row["can_mark_attendance"] is True


async def test_attention_panel_lists_tickets_alerts_and_flags(
    settings: Settings, session_factory: Factory
) -> None:
    _, patient_id, appointment_id = await _clinic(session_factory)
    async with session_factory() as session:
        patient = await session.get_one(Patient, patient_id)
        session.add(HandoffTicket(patient_id=patient.id, reason="patient_requested"))
        session.add(EmergencyAlert(patient_id=patient.id, telegram_user_id=4242))
        session.add(EmergencyAlert(telegram_user_id=999))
        appointment = await session.get_one(Appointment, appointment_id)
        appointment.staff_attention_reason, appointment.staff_attention_at = "reminder_failed", NOW
        await session.commit()
    async with api_client(settings, session_factory, lambda: NOW) as client:
        await login(client, "riya")
        body = (await client.get("/api/v1/attention")).json()
    assert [t["patient"]["full_name"] for t in body["tickets"]] == ["Asha Rao"]
    assert sorted((a["patient"] or {}).get("phone", "unregistered") for a in body["alerts"]) == [
        "+12025550150",
        "unregistered",
    ]
    assert [f["staff_attention"]["reason"] for f in body["flagged"]] == ["reminder_failed"]


async def test_a_refused_booking_names_the_limit_it_hit(settings: Settings, session_factory: Factory) -> None:
    doctor_id, patient_id, _ = await _clinic(session_factory)

    def booking(day: int, hour: int) -> dict[str, object]:
        return {"doctor_id": doctor_id, "start": at(day, hour).isoformat(), "patient": {"id": patient_id}}

    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "riya")
        tuesday = await client.post("/api/v1/appointments", json=booking(8, 9), headers=csrf)
        same_day = await client.post("/api/v1/appointments", json=booking(8, 10), headers=csrf)
        for day in (9, 10):
            later = await client.post("/api/v1/appointments", json=booking(day, 9), headers=csrf)
            assert later.status_code == 201, later.text
        fourth = await client.post("/api/v1/appointments", json=booking(11, 9), headers=csrf)
    assert tuesday.status_code == 201, tuesday.text
    # Live finding 2026-11-05: staff were told to cancel a booking when the rule was one per doctor per day.
    assert (same_day.status_code, same_day.json()["error"]["code"]) == (409, "LIMIT_REACHED")
    assert same_day.json()["error"]["details"]["reason"] == "same_doctor_same_day"
    assert (fourth.status_code, fourth.json()["error"]["details"]["reason"]) == (409, "max_upcoming")


async def test_walk_in_booking_and_the_shared_double_booking_rule(
    settings: Settings, session_factory: Factory
) -> None:
    doctor_id, _, _ = await _clinic(session_factory)
    payload = {
        "doctor_id": doctor_id,
        "start": at(8, 10).isoformat(),
        "patient": {"full_name": "Ravi Kumar", "phone": "+1 202-555-0177", "verbal_consent": True},
    }
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "riya")
        slots = (
            await client.get("/api/v1/availability", params={"doctor_id": doctor_id, "date": "2030-01-08"})
        ).json()
        created = await client.post("/api/v1/appointments", json=payload, headers=csrf)
        again = await client.post(
            "/api/v1/appointments",
            json={
                **payload,
                "patient": {"full_name": "Someone Else", "phone": "+1 202-555-0178", "verbal_consent": True},
            },
            headers=csrf,
        )
        # Review L1: the phone number travels in the body, never in a URL that proxies or browsers may log.
        found = (
            await client.post("/api/v1/patients/lookup", json={"phone": "+12025550177"}, headers=csrf)
        ).json()
        old_query_route = await client.get("/api/v1/patients", params={"phone": "+12025550177"})
    assert "10:00 AM" in [s["time_label"] for s in slots["slots"]]
    assert created.status_code == 201, created.text
    assert (created.json()["source"], created.json()["patient"]["full_name"]) == ("staff", "Ravi Kumar")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "SLOT_TAKEN", "E6-S4-AC2: the same database rule as the bot"
    assert [p["full_name"] for p in found["items"]] == ["Ravi Kumar"]
    assert old_query_route.status_code == 404, "no route takes a phone number in the query string"
    async with session_factory() as session:
        walk_in = await session.scalar(select(Patient).where(Patient.phone == "+12025550177"))
    assert walk_in is not None
    assert (walk_in.consent_source, walk_in.registered_via, walk_in.telegram_user_id) == (
        "staff_verbal",
        "staff",
        None,
    )


async def test_staff_cancel_queues_a_telegram_notice_only_when_linked(
    settings: Settings, session_factory: Factory
) -> None:
    doctor_id, _, _ = await _clinic(session_factory)
    async with session_factory() as session:
        doctor = await session.get_one(Doctor, doctor_id)
        linked = await make_patient(session, telegram_user_id=5151)
        walk_in = await make_patient(session)
        first = await make_appointment(session, doctor=doctor, patient=linked, start=at(8, 9))
        second = await make_appointment(session, doctor=doctor, patient=walk_in, start=at(8, 10))
        await session.commit()
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "riya")
        missing_reason = await client.post(
            f"/api/v1/appointments/{first.id}/cancel", json={"reason": ""}, headers=csrf
        )
        for appointment in (first, second):
            response = await client.post(
                f"/api/v1/appointments/{appointment.id}/cancel",
                json={"reason": "Doctor called in sick"},
                headers=csrf,
            )
            assert response.status_code == 200
            assert response.json()["status"] == "cancelled"
    assert missing_reason.status_code == 422
    async with session_factory() as session:
        notices = (await session.scalars(select(Notification))).all()
    assert [(n.appointment_id, n.kind, n.reason) for n in notices] == [
        (first.id, "clinic_cancelled", "Doctor called in sick")
    ]


async def test_attendance_rules(settings: Settings, session_factory: Factory) -> None:
    doctor_id, _, past_id = await _clinic(session_factory)
    async with session_factory() as session:
        doctor = await session.get_one(Doctor, doctor_id)
        future = await make_appointment(
            session, doctor=doctor, patient=await make_patient(session), start=at(9, 9)
        )
        await session.commit()
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "riya")
        too_early = await client.post(
            f"/api/v1/appointments/{future.id}/attendance", json={"status": "completed"}, headers=csrf
        )
        marked = await client.post(
            f"/api/v1/appointments/{past_id}/attendance", json={"status": "completed"}, headers=csrf
        )
        correction = await client.post(
            f"/api/v1/appointments/{past_id}/attendance", json={"status": "no_show"}, headers=csrf
        )
        await client.post("/api/v1/auth/logout", headers=csrf)
        admin_csrf = await login(client, "admin")
        admin_fix = await client.post(
            f"/api/v1/appointments/{past_id}/attendance", json={"status": "no_show"}, headers=admin_csrf
        )
    assert too_early.status_code == 409, "E6-S5-AC2"
    assert marked.json()["status"] == "completed"
    assert correction.status_code == 403, "GAP-22: only an admin corrects a mark"
    assert admin_fix.json()["status"] == "no_show"


async def test_tickets_resolve_and_alerts_acknowledge_with_the_staff_member(
    settings: Settings, session_factory: Factory
) -> None:
    _, patient_id, _ = await _clinic(session_factory)
    async with session_factory() as session:
        ticket = HandoffTicket(patient_id=patient_id, reason="patient_requested")
        alert = EmergencyAlert(patient_id=patient_id, telegram_user_id=4242)
        session.add_all([ticket, alert])
        await session.commit()
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "riya")
        me = (await client.get("/api/v1/auth/me")).json()["user"]
        resolved = await client.post(f"/api/v1/tickets/{ticket.id}/resolve", headers=csrf)
        acknowledged = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=csrf)
        attention = (await client.get("/api/v1/attention")).json()
    assert (resolved.json()["status"], resolved.json()["resolved_by"]) == ("resolved", me["id"])
    assert acknowledged.json()["acknowledged_by"] == me["id"]
    assert (attention["tickets"], attention["alerts"]) == ([], [])


async def test_logout_ends_the_session(settings: Settings, session_factory: Factory) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        csrf = await login(client, "riya")
        assert (await client.post("/api/v1/auth/logout", headers=csrf)).status_code == 204
        after = await client.get("/api/v1/auth/me")
    assert after.status_code == 401


async def test_login_attempts_are_rate_limited_per_client(
    settings: Settings, session_factory: Factory
) -> None:
    await _clinic(session_factory)
    async with api_client(settings, session_factory, lambda: NOW) as client:
        codes = [
            (
                await client.post("/api/v1/auth/login", json={"username": f"ghost{i}", "password": "x" * 12})
            ).status_code
            for i in range(11)
        ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429
