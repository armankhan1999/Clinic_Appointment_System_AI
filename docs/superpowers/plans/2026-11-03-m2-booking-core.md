# M2 Booking Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (executed inline by the plan author with TDD, as in M1). Steps use checkbox (`- [ ]`) syntax.

**Goal:** a registered patient can ask for free slots in plain language, book one through an explicit Confirm tap, and never double-book; emergency messages are answered by code before any LLM call; replies that name times are checked against tool results.

**Architecture:** pure domain modules (`domain/slots.py`, `domain/dates.py`, `domain/booking_rules.py`) feed `services/availability.py` and `services/booking.py`; the agent gains `check_availability` and `book_appointment`; write tools only stage an in-memory `PendingAction`; the Confirm callback executes the booking in one transaction that re-validates everything (MP-04). Guardrails (`agent/guardrails.py`, `agent/grounding.py`) wrap the conversation service.

**Stories:** E2-S2 (AC1–AC4), E2-S3 (AC1–AC5), E2-S4 (AC1, AC3, AC4), E2-S5 (AC1–AC3, resolver and next working day), E5-S3 (AC1–AC3; dashboard display in M5).

## Global Constraints

- All M1 constraints still apply (D-10 deterministic safety, D-16 no identity to the LLM, UTC storage, audited writes, no `type: ignore`).
- Slot length, schedules and leave come from the database; part-of-day boundaries, cut-off, booking window and limits come from `clinic_settings` (IMP-05, GAP-14).
- Booking window: today … today + `booking_window_days` inclusive, in the clinic time zone; a slot must start after now (GAP-35).
- Up to 5 slots per answer (E2-S2-AC1); next 3 dates with free slots for the same doctor, any part of day, within the window (GAP-33); up to 3 nearest free slots after SLOT_TAKEN (GAP-34).
- Relative dates are resolved by code, never by the LLM (GAP-36). Rules (GAP-15): `today`, `tomorrow`, `day after tomorrow`; `<weekday>` / `this <weekday>` = nearest on or after today; `next <weekday>` = first occurrence strictly after today; ISO `YYYY-MM-DD`; `D Month [YYYY]` / `Month D [YYYY]`; a bare day-of-month (`the 5th`) resolves to this month if not past, else next month, **except** in the last 7 days of a month, where it is `AMBIGUOUS_DATE` (E2-S5-AC2). Every reply repeats the resolved date (E2-S5-AC1).
- Limits (E2-S3-AC4): at most `max_per_doctor_per_day` booked appointments with one doctor on one day and `max_upcoming_per_patient` upcoming booked appointments; checked under `SELECT … FOR UPDATE` on the patient row.
- Pending confirmations live in memory, one per patient, expire after 10 minutes; a tap on an unknown or expired token writes nothing (GAP-17).
- Emergency check runs first on every text message, for registered and unregistered senders, mid-flow included (E5-S3-AC2); it never calls the LLM; alerts store no message text and are de-duplicated per sender for 10 minutes (IMP-06).

## Tasks

1. **Slots and dates (pure).** `domain/slots.py`: `ScheduleBlock`, `generate_slots(blocks, day, tz)`, `free_slots(...)` excluding booked overlaps, leave days, past starts and out-of-window days; `part_of_day(start_local, morning_end, afternoon_end)`; `format_time_12h`, `format_date_long`. `domain/dates.py`: `resolve_date(phrase, today) -> Resolved | Ambiguous | Unrecognised`. Tests: slot stepping incl. blocks that don't divide evenly, lunch-break gaps, booked overlap with a different slot length, leave day, now-boundary, window inclusivity, each date phrase and the month-end ambiguity rule.
2. **Availability service + `check_availability` tool.** Three queries per call (schedules, leaves, booked appointments over the window). Result codes OK / NO_SLOTS (+ next 3 dates) / INVALID_DATE / AMBIGUOUS_DATE / DOCTOR_NOT_WORKING (+ next working day) / NOT_FOUND (unknown or inactive doctor). Slots carry `slot_start` (ISO with clinic offset) and a 12-hour label. Integration tests against `clinic_test`.
3. **Booking service.** `BookingService.precheck(patient_id, doctor_id, slot_start)` (no writes) and `BookingService.book(...)` (transaction: lock patient, re-validate slot/leave/window/limits, insert, map unique or exclusion violation to `SLOT_TAKEN` with nearest free slots, audit `appointment.book`). Integration tests incl. **10 parallel bookings for one slot → exactly 1 row** (E2-S4-AC4) and limit refusals with reasons.
4. **Pending actions + `book_appointment` tool + Confirm/Change callbacks.** `agent/pending.py` (`PendingStore`, token = 12 url-safe chars, callback `v1:confirm:<token>` / `v1:change:<token>` ≤ 64 bytes). The tool returns `PENDING_CONFIRMATION` with doctor/date/time only; the conversation service renders the summary with the patient's name and Confirm/Change buttons (E2-S3-AC1, D-16). Confirm → booked + reference (E2-S3-AC2); slot gone → `SLOT_TAKEN` + nearest slots (E2-S3-AC3); `patient_id` always from the session (E2-S3-AC5).
5. **Emergency guardrail.** `agent/guardrails.py` normaliser and matcher (case, punctuation, curly/straight apostrophes, whitespace); `services/alerts.py` with 10-minute de-duplication. Conversation tests prove the LLM double is never called, unregistered and mid-registration senders are covered, and the alert row has no text.
6. **Grounding check (E2-S2-AC4).** `agent/grounding.py`: every time (`10:30 AM`, `10 am`, `14:30`) and money amount (`Rs 500`, `₹500`, `500 rupees`) in a reply must appear in a tool result from the same conversation; otherwise the reply is replaced by a safe message and the event is logged. Unit tests for extraction and matching.
7. **System prompt + live smoke + trackers.** Prompt version bump describing the new tools; live test: "Is Dr X free tomorrow morning?" → `check_availability` call with a relative date resolved by code; trackers and RTM updated.

## Self-review

Every M2 acceptance criterion maps to a task above: E2-S2-AC1/2/3 → 1, 2; E2-S2-AC4 → 6 (evaluation in M6); E2-S3-AC1..5 → 3, 4; E2-S4-AC1/AC4 → 3, AC3 → 1, 2; E2-S5-AC1..3 → 1, 2; E5-S3-AC1..3 → 5.
