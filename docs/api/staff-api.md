# Staff API contract (v1)

Source of truth for the dashboard (`apps/web`) and the FastAPI implementation (`apps/backend/src/clinic/api`). Design background: [`../architecture/api-and-auth.md`](../architecture/api-and-auth.md). Generated OpenAPI is served at `/api/v1/openapi.json` in development; if the two disagree, this document wins and the code is fixed.

## Conventions

- Base path `/api/v1`. The browser calls the **Next.js origin**; `next.config` rewrites `/api/v1/*` to `http://127.0.0.1:${API_PORT}/api/v1/*` (same origin, no CORS).
- JSON in and out, UTF-8. Timestamps are ISO 8601 **UTC** (`2030-01-09T04:00:00Z`); dates are `YYYY-MM-DD` in the clinic time zone; every appointment also carries a display label in clinic time (`"time_label": "9:30 AM"`), so the UI never converts time zones itself.
- IDs are UUID strings. Appointment references look like `APT-000123`.
- Auth: an HttpOnly session cookie `clinic_session` (SameSite=Lax, Path=/, Secure when served over HTTPS). Every request except `POST /auth/login` and the health checks needs it.
- CSRF: every `POST`, `PUT`, `PATCH`, `DELETE` must send header `X-CSRF-Token` with the value from `GET /auth/me` (or the login response). Missing or wrong → `403 FORBIDDEN` with `details.reason = "csrf"` (a role refusal has no `reason`), so the UI refreshes the token and retries only in that case.
- Idle timeout: a session ends after 60 minutes without activity (12 hours absolute). Automatic polling sends `X-Background-Refresh: 1` on its `GET`s; such requests are authenticated but do not count as activity.
- Roles: `receptionist` (R) and `admin` (A). Admin can do everything a receptionist can. Wrong role → `403 FORBIDDEN`; the UI hides admin screens, but the API is the enforcement point (E6-S1-AC4).
- Lists are paginated with `?page=1&page_size=50` (max 100) and return `{"items": [...], "page": 1, "page_size": 50, "total": 123}`: `/audit`, `/faq`, `/staff-users`. The short lookups `/doctors`, `/patients` and `/doctors/{id}/leaves` return `{ "items": [...] }` only.
- Weekdays are numbered 0 = Monday to 6 = Sunday.
- Every response has `X-Request-ID`.

### Error envelope

```json
{ "error": { "code": "SLOT_TAKEN", "message": "Human readable message", "request_id": "…", "details": { } } }
```

| HTTP | `code` values |
|---|---|
| 400 / 422 | `VALIDATION_ERROR` (`details.fields`: list of field paths) |
| 401 | `UNAUTHENTICATED` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` |
| 409 | `SLOT_TAKEN`, `SLOT_UNAVAILABLE`, `LIMIT_REACHED`, `ALREADY_CANCELLED`, `CONFLICT` |
| 423 | `ACCOUNT_LOCKED` (`details.locked_until`) |
| 429 | `RATE_LIMITED` |
| 500 | `ERROR` |

## Shared shapes

```ts
type Role = "receptionist" | "admin";
type StaffUser = { id: string; username: string; display_name: string; role: Role; active: boolean };
type PatientRef = { id: string; full_name: string; phone: string | null };          // phone null after deletion
type ReminderStatus = "pending" | "sent" | "failed" | "skipped" | null;             // null = not due yet
type Appointment = {
  id: string; reference: string; doctor_id: string; doctor_name: string;
  start: string; end: string; date: string; time_label: string;                     // clinic-time labels
  status: "booked" | "cancelled" | "completed" | "no_show";
  source: "bot" | "staff";
  patient: PatientRef;
  reminders: { "24h": ReminderStatus; "2h": ReminderStatus };
  patient_confirmed: boolean;                                                         // E4-S3-AC1
  staff_attention: { reason: "notification_failed" | "reminder_failed"; at: string } | null; // E4-S4-AC2
  can_mark_attendance: boolean;                                                       // start has passed (E6-S5)
};
type Slot = { start: string; time_label: string };
```

## Endpoints

### Auth (E6-S1)

| Method & path | Role | Request | Response |
|---|---|---|---|
| `POST /auth/login` | public, rate-limited | `{ username, password }` | `200 { user: StaffUser, csrf_token }` + cookie. Wrong credentials → `401` (same message for unknown user and wrong password). Locked → `423`. |
| `POST /auth/logout` | R | — | `204` (session revoked, cookie cleared) |
| `GET /auth/me` | R | — | `200 { user: StaffUser, csrf_token }` |

### Daily work (receptionist)

| Method & path | Request | Response | Source |
|---|---|---|---|
| `GET /schedule?date=YYYY-MM-DD` | — | `{ date, doctors: [{ doctor_id, name, specialty, appointments: Appointment[] }] }` — every active doctor, appointments of all statuses that day, ordered by start | E6-S2-AC1/AC2 |
| `GET /attention` | — | `{ tickets: [{ id, reason, created_at, patient: PatientRef }], alerts: [{ id, created_at, patient: PatientRef \| null, telegram_user_id: number \| null }], flagged: Appointment[] }` — open tickets, unacknowledged alerts, appointments with `staff_attention` | E6-S2-AC3, E5-S3-AC3, E4-S4-AC2 |
| `GET /doctors?active=true` | — | `{ items: [{ id, name, specialty, active }] }` | E6-S4 |
| `GET /availability?doctor_id=&date=` | — | `{ date, slots: Slot[] }` (staff are not bound by the bot cut-off, GAP-21) | E6-S4 |
| `GET /patients?phone=` | — | `{ items: PatientRef[] }` — exact match on normalised phone only, never a full listing | E6-S4-AC1 |
| `POST /appointments` | `{ doctor_id, start, patient: { id } \| { full_name, phone, verbal_consent: true } }` | `201 Appointment` (`source: "staff"`). `409 SLOT_TAKEN` from the same database rule as the bot (E6-S4-AC2). | E6-S4-AC1/AC2 |
| `POST /appointments/{id}/cancel` | `{ reason }` (1–200 chars) | `200 Appointment`; queues a Telegram notice when the patient has a Telegram link | E6-S4-AC3, E4-S4-AC1 |
| `POST /appointments/{id}/attendance` | `{ status: "completed" \| "no_show" }` | `200 Appointment`; `409 CONFLICT` if the start time has not passed; changing a mark later is admin only | E6-S5 |
| `POST /appointments/{id}/clear-attention` | — | `200 Appointment` | E4-S4-AC2 |
| `POST /tickets/{id}/resolve` | — | `200 { id, status: "resolved", resolved_by, resolved_at }` | E5-S4-AC2 |
| `POST /alerts/{id}/acknowledge` | — | `200 { id, acknowledged_by, acknowledged_at }` | E5-S3-AC3 |

### Administration (admin only)

| Method & path | Request | Response | Source |
|---|---|---|---|
| `POST /doctors` | `{ name, specialty }` | `201 { id, name, specialty, active }` | IMP-01 |
| `PATCH /doctors/{id}` | `{ name?, specialty?, active? }` | `200` doctor | IMP-01, E2-S1-AC2 |
| `GET /doctors/{id}/schedule` | — | `{ blocks: [{ weekday: 0-6, start: "HH:MM", end: "HH:MM", slot_minutes }] }` | E6-S3 |
| `PUT /doctors/{id}/schedule` | `{ blocks: [...] }` (replaces the weekly pattern; breaks = gaps between blocks) | `200` same shape. `422` when `end <= start`, blocks overlap on a weekday, or `slot_minutes` is outside 5–120 | E6-S3-AC1/AC2 |
| `GET /doctors/{id}/leaves` | — | `{ items: [{ id, date, reason }] }` | E6-S3 |
| `POST /doctors/{id}/leaves/preview` | `{ date }` | `{ affected: Appointment[] }` | E6-S3-AC3 |
| `POST /doctors/{id}/leaves` | `{ date, reason, confirm_affected: boolean }` | `201 { leave, cancelled: Appointment[] }`. If bookings are affected and `confirm_affected` is false → `409 CONFLICT` with `details.affected`. On confirm, affected bookings are cancelled and notices queued | E6-S3-AC3, E4-S4 |
| `DELETE /doctors/{id}/leaves/{leave_id}` | — | `204` | E6-S3 |
| `GET /faq` / `POST /faq` / `PATCH /faq/{id}` / `DELETE /faq/{id}` | `{ topic: slug, aliases: string[], answer: 1-2000 chars }` (`topic` matches `^[a-z0-9_]{1,40}$`) | entry `{ id, topic, aliases, answer, updated_at }`; list → paginated, ordered by topic. A topic another entry already uses → `409 CONFLICT` | IMP-02, E5-S1-AC3 |
| `GET /settings` / `PATCH /settings` | any subset of `clinic_name, phone, address, staff_hours_text, timezone, emergency_number, emergency_phrases, cutoff_minutes, booking_window_days, max_upcoming_per_patient, max_per_doctor_per_day, morning_end, afternoon_end` (`HH:MM`) | the full settings object. `422` for an unknown IANA time zone or `morning_end >= afternoon_end` | IMP-05 |
| `GET /audit?from=&to=&actor_type=&action=&patient_id=&page=&page_size=` | `from`/`to` are `YYYY-MM-DD` days in the clinic time zone, both inclusive | paginated `{ id, ts, actor_type, actor_id, patient_id, action, args, result, latency_ms, request_id }`, newest first | E7-S2-AC3, IMP-03 |
| `GET /metrics/weekly?week_start=YYYY-MM-DD` | — | `{ week_start, bookings_by_source: { bot, staff }, cancellations, per_doctor: [{ doctor_id, name, completed, no_show, no_show_rate }] }` — zeros, never an error, when empty; `no_show_rate = no_show / (completed + no_show)`, 0 when the denominator is 0 | E6-S6, GAP-24 |
| `GET /staff-users` / `POST /staff-users` / `PATCH /staff-users/{id}` / `POST /staff-users/{id}/unlock` | create `{ username, display_name, role, password }` (password ≥ 12 chars); patch `{ display_name?, role?, active?, password? }` | `StaffUser & { locked_until: string \| null }`; list → paginated, ordered by username. A password reset signs the user out everywhere. Deactivating or demoting your own account → `409 CONFLICT` | IMP-04 |

Every write writes an audit row with `actor_type = "staff"` and the staff user id (GAP-18).
