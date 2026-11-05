# Staff API contract (v1)

Source of truth for the dashboard (`apps/web`) and the FastAPI implementation (`apps/backend/src/clinic/api/routes_*.py`). Design background: [`../architecture/api-and-auth.md`](../architecture/api-and-auth.md). Generated OpenAPI (`/api/v1/openapi.json`) and Swagger UI (`/api/v1/docs`) are served only when `ENV=development`; if this document and the code disagree, this document wins and the code is fixed. Every route, request model and response shape below was compared with `routes_auth.py`, `routes_staff.py`, `routes_admin.py` and the services behind them on 2026-11-05 (commit 3938155).

## Conventions

- Base path `/api/v1`. The browser calls the **Next.js origin**; `next.config.ts` rewrites `/api/v1/*` to `http://127.0.0.1:${API_PORT}/api/v1/*` (same origin, no CORS). The API listens on `127.0.0.1` only.
- JSON in and out, UTF-8. Request bodies reject unknown fields (`extra="forbid"` on every request model → `422`). Timestamps are ISO 8601 **UTC** (`2030-01-09T04:00:00Z`), with one exception: slot starts (`Slot.start` and `details.alternatives`) carry the clinic's UTC offset (`2030-01-09T09:30:00+05:30`); they name the same instant and can be sent back unchanged as `start`. Dates are `YYYY-MM-DD` in the clinic time zone; every appointment and slot also carries a display label in clinic time (`"time_label": "9:30 AM"`), so the UI never converts time zones itself. A booking `start` must include an offset.
- IDs are UUID strings. Appointment references look like `APT-000123` (at least 6 digits).
- Auth: an HttpOnly session cookie `clinic_session` (SameSite=Lax, Path=/, Max-Age 12 hours, Secure when `ENV=production`). Every request except `POST /auth/login` and the health checks (`/healthz`, `/readyz`, outside `/api/v1`) needs it; without a valid session → `401 UNAUTHENTICATED`.
- CSRF: every request other than `GET`, `HEAD` and `OPTIONS` (in this API: every `POST`, `PUT`, `PATCH`, `DELETE` except `POST /auth/login`) must send header `X-CSRF-Token` with the value from `GET /auth/me` or the login response. Missing or wrong → `403 FORBIDDEN` with `details.reason = "csrf"` (a role refusal has no `reason`), so the UI refreshes the token and retries only in that case (D-30).
- Idle timeout: a session ends after 60 minutes without activity and 12 hours after login, whichever comes first. A `GET` with `X-Background-Refresh: 1` is authenticated but does not count as activity (D-29); the dashboard sends it on any `GET` made after 60 s without user input. Activity is recorded at most once a minute.
- Roles: `receptionist` (R) and `admin` (A). Admin can do everything a receptionist can. Wrong role → `403 FORBIDDEN`; the UI hides admin screens, but the API is the enforcement point (E6-S1-AC4).
- Lists are paginated with `?page=1&page_size=50` (page ≥ 1, page_size 1–100, default 50) and return `{"items": [...], "page": 1, "page_size": 50, "total": 123}`: `/audit`, `/faq`, `/staff-users`. The short lookups `GET /doctors`, `POST /patients/lookup` and `GET /doctors/{id}/leaves` return `{ "items": [...] }` only.
- Weekdays are numbered 0 = Monday to 6 = Sunday.
- Every response has `X-Request-ID` (the incoming value when it matches `^[A-Za-z0-9-]{8,64}$`, otherwise a new one).

### Error envelope

```json
{ "error": { "code": "SLOT_TAKEN", "message": "Human readable message", "request_id": "…", "details": { } } }
```

`details` is present only when it has content.

| HTTP | `code` values |
|---|---|
| 400 / 422 | `VALIDATION_ERROR`. Request validation (422) gives `details.fields`, a list of field paths (never the submitted values); a rule checked by a service (422) may give `details.fields` or `details.weekday` |
| 401 | `UNAUTHENTICATED` |
| 403 | `FORBIDDEN` (`details.reason = "csrf"` for a CSRF failure) |
| 404 | `NOT_FOUND` (also for unknown routes) |
| 405 | `METHOD_NOT_ALLOWED` |
| 409 | `SLOT_TAKEN` (`details.alternatives` when free slots exist), `SLOT_UNAVAILABLE`, `LIMIT_REACHED` (`details.reason` on staff bookings), `ALREADY_CANCELLED`, `CONFLICT` (`details.affected` for a leave that needs confirmation) |
| 423 | `ACCOUNT_LOCKED` (`details.locked_until`) |
| 429 | `RATE_LIMITED` |
| 500 | `ERROR` (no internals; the request id is the support reference) |

## Shared shapes

```ts
type Role = "receptionist" | "admin";
type StaffUser = { id: string; username: string; display_name: string; role: Role; active: boolean };
type PatientRef = { id: string; full_name: string; phone: string | null; telegram: boolean };  // telegram: linked, so reminders and notices reach them (D-47)          // after deletion: "Deleted patient", null
type ReminderStatus = "pending" | "sent" | "failed" | "skipped" | null;             // null = no reminder row yet
type Appointment = {
  id: string; reference: string; doctor_id: string; doctor_name: string;
  start: string; end: string;                                                         // UTC
  date: string; time_label: string;                                                   // clinic-time labels
  status: "booked" | "cancelled" | "completed" | "no_show";
  source: "bot" | "staff";
  patient: PatientRef;
  reminders: { "24h": ReminderStatus; "2h": ReminderStatus };
  patient_confirmed: boolean;                                                         // E4-S3-AC1
  staff_attention: { reason: "notification_failed" | "reminder_failed"; at: string } | null; // E4-S4-AC2
  can_mark_attendance: boolean;  // start has passed and status is booked, completed or no_show (E6-S5)
};
type Slot = { start: string; time_label: string };                                  // start carries the clinic offset
```

## Endpoints

### Auth (E6-S1)

| Method & path | Role | Request | Response |
|---|---|---|---|
| `POST /auth/login` | public; 10 attempts per minute per client, then `429 RATE_LIMITED` | `{ username: 1–80 chars, password: 1–256 chars }` | `200 { user: StaffUser, csrf_token }` + cookie. Wrong credentials, unknown user or deactivated account → `401` with the same message. The 5th failure within 15 minutes locks the name for 15 minutes; while locked → `423` with `details.locked_until` (unknown names are locked the same way). |
| `POST /auth/logout` | R (needs CSRF) | — | `204` (session revoked, cookie cleared) |
| `GET /auth/me` | R | — | `200 { user: StaffUser, csrf_token }` |

### Daily work (receptionist)

| Method & path | Request | Response | Source |
|---|---|---|---|
| `GET /schedule?date=YYYY-MM-DD` | `date` required | `{ date, doctors: [{ doctor_id, name, specialty, appointments: Appointment[] }] }` — every **active** doctor ordered by name, with that day's appointments of all statuses ordered by start | E6-S2-AC1/AC2 |
| `GET /clinic/today` | — | `{ date: "YYYY-MM-DD", timezone }` (IANA name) — today in the clinic's time zone; the dashboard uses it for Today, booking dates, leave days and the metrics week instead of the PC's clock (it falls back to the PC's date only until the first answer arrives) | review L4, D-40 |
| `GET /attention` | — | `{ tickets: [{ id, reason, created_at, patient: PatientRef }], alerts: [{ id, created_at, patient: PatientRef \| null, telegram_user_id: number \| null }], flagged: Appointment[] }` — open tickets and unacknowledged alerts, oldest first; every appointment with `staff_attention` set, by start. `telegram_user_id` is filled only when the sender has no patient record | E6-S2-AC3, E5-S3-AC3, E4-S4-AC2 |
| `GET /doctors?active=true` | `active` optional; omitted → all doctors | `{ items: [{ id, name, specialty, active }] }`, ordered by name | E6-S4 |
| `GET /availability?doctor_id=&date=` | both required | `{ date, slots: Slot[] }` — the bot's slot computation (schedule − leave − booked − past starts, inside the booking window). A date outside the window gives `slots: []`. Unknown or inactive doctor → `404`. Per-patient limits are checked only when booking | E6-S4 |
| `POST /patients/lookup` | `{ phone: 3–30 chars }` | `{ items: PatientRef[] }` — exact match on the normalised phone (numbers without a country code are read as Indian, region `IN`), excluding deleted patients; never a full listing. Unparseable number → `422`. A POST body keeps the number out of URLs and any log that records them; `GET /patients?phone=` no longer exists (`404`) (review L1, D-41) | E6-S4-AC1 |
| `POST /appointments` | `{ doctor_id, start, patient: { id } \| { full_name: 1–60 chars, phone: 3–30 chars, verbal_consent: true } }` | `201 Appointment` (`source: "staff"`), through the same booking rules as the bot: a grid slot inside the booking window, not in the past, and the per-patient limits. `409 SLOT_TAKEN` from the same database rule as the bot (E6-S4-AC2), with `details.alternatives` (up to 3 nearest free starts); `409 SLOT_UNAVAILABLE` for a time that is not a free slot; `409 LIMIT_REACHED` with `details.reason` = `same_doctor_same_day` (the patient already has a booking with this doctor that day) or `max_upcoming` (the patient holds the maximum number of upcoming bookings), so the dashboard can say which rule applies; `404` for an unknown or inactive doctor or an unknown or deleted patient. New patient: `verbal_consent` must be `true`, the name 2–60 characters of letters, spaces, hyphens, apostrophes or dots (no digits), and the phone a valid number, else `422`; a phone that already belongs to a patient → `409 CONFLICT` (look them up instead) | E6-S4-AC1/AC2, GAP-10 |
| `POST /appointments/{id}/cancel` | `{ reason }` (1–200 chars) | `200 Appointment`; queues a Telegram notice when the patient has a Telegram link. Not bound by the bot's cut-off (GAP-21). Already cancelled → `409 ALREADY_CANCELLED`; completed or no-show → `409 CONFLICT` | E6-S4-AC3, E4-S4-AC1 |
| `POST /appointments/{id}/attendance` | `{ status: "completed" \| "no_show" }` | `200 Appointment`. Before the start time → `409 CONFLICT`; a cancelled appointment → `409 CONFLICT`; a receptionist changing an existing mark → `403 FORBIDDEN` (only an admin can switch completed ↔ no_show, GAP-22) | E6-S5 |
| `POST /appointments/{id}/clear-attention` | — | `200 Appointment` (the flag is removed) | E4-S4-AC2 |
| `POST /tickets/{id}/resolve` | — | `200 { id, status: "resolved", resolved_by, resolved_at }`; resolving an already resolved ticket returns it unchanged | E5-S4-AC2 |
| `POST /alerts/{id}/acknowledge` | — | `200 { id, acknowledged_by, acknowledged_at }`; repeating it returns the first acknowledgement | E5-S3-AC3 |

Unknown appointment, ticket or alert ids → `404 NOT_FOUND`.

### Administration (admin only)

| Method & path | Request | Response | Source |
|---|---|---|---|
| `POST /doctors` | `{ name, specialty }` (2–80 chars each) | `201 { id, name, specialty, active }` | IMP-01 |
| `PATCH /doctors/{id}` | `{ name?, specialty?, active? }` | `200` doctor; unknown id → `404` | IMP-01, E2-S1-AC2 |
| `GET /doctors/{id}/schedule` | — | `{ blocks: [{ weekday: 0-6, start: "HH:MM", end: "HH:MM", slot_minutes }] }`, ordered by weekday and start; unknown doctor → `404` | E6-S3 |
| `PUT /doctors/{id}/schedule` | `{ blocks: [...] }` (at most 70; replaces the whole weekly pattern; breaks = gaps between blocks) | `200` same shape. `422` when a time is not `HH:MM`, `end <= start`, blocks overlap on a weekday, or `slot_minutes` is outside 5–120 | E6-S3-AC1/AC2 |
| `GET /doctors/{id}/leaves` | — | `{ items: [{ id, date, reason }] }`, ordered by date | E6-S3 |
| `POST /doctors/{id}/leaves/preview` | `{ date }` | `{ affected: Appointment[] }` — the doctor's booked appointments that day | E6-S3-AC3 |
| `POST /doctors/{id}/leaves` | `{ date, reason: 1–200 chars, confirm_affected?: boolean = false }` | `201 { leave: { id, date, reason }, cancelled: Appointment[] }`. If bookings are affected and `confirm_affected` is false → `409 CONFLICT` with `details.affected` (Appointment list). Leave already recorded that day → `409 CONFLICT`. Unknown doctor → `404`. On confirm, affected bookings are cancelled and notices queued for patients with a Telegram link | E6-S3-AC3, E4-S4 |
| `DELETE /doctors/{id}/leaves/{leave_id}` | — | `204`; unknown leave → `404`. Bookings cancelled by that leave are not restored | E6-S3 |
| `GET /faq` / `POST /faq` / `PATCH /faq/{id}` / `DELETE /faq/{id}` | `{ topic, aliases: string[] (at most 20, default []), answer: 1–2000 chars }`; `topic` matches `^[a-z0-9_]{1,40}$`; PATCH takes any subset | entry `{ id, topic, aliases, answer, updated_at }`; list → paginated, ordered by topic. A topic another entry already uses → `409 CONFLICT`; unknown id → `404`; `DELETE` → `204` | IMP-02, E5-S1-AC3 |
| `GET /settings` / `PATCH /settings` | any subset of `clinic_name` (2–120), `phone` (3–30), `address` (3–300), `staff_hours_text` (3–120), `timezone`, `emergency_number` (2–20), `emergency_phrases` (at most 100; blanks dropped), `cutoff_minutes` (0–10080), `booking_window_days` (1–365), `max_upcoming_per_patient` (1–20), `max_per_doctor_per_day` (1–10), `morning_end`, `afternoon_end` (`HH:MM`) | the full settings object with those 13 fields. `422` for an unknown IANA time zone or `morning_end >= afternoon_end`. The bot picks up a change within 30 s (settings cache) | IMP-05 |
| `GET /audit?from=&to=&actor_type=&action=&patient_id=&page=&page_size=` | `from`/`to` are `YYYY-MM-DD` days in the clinic time zone, both inclusive; `actor_type` is one of `agent`, `staff`, `system`, `patient_button`; `action` (≤ 60 chars) matches exactly | paginated `{ id, ts, actor_type, actor_id, patient_id, action, args, result, latency_ms, request_id }`, newest first | E7-S2-AC3, IMP-03 |
| `GET /metrics/weekly?week_start=YYYY-MM-DD` | `week_start` required | `{ week_start, bookings_by_source: { bot, staff }, cancellations, per_doctor: [{ doctor_id, name, completed, no_show, no_show_rate }] }` for appointments starting in the 7 days from `week_start` (clinic time); `per_doctor` lists every doctor, active or not. Zeros, never an error, when empty; `no_show_rate = no_show / (completed + no_show)` rounded to 4 decimals, 0 when the denominator is 0 | E6-S6, GAP-24 |
| `GET /staff-users` / `POST /staff-users` / `PATCH /staff-users/{id}` / `POST /staff-users/{id}/unlock` | create `{ username, display_name, role, password }`: username 3–40 characters of `a-z 0-9 . _ -` (stored lower-case), display name 1–80, password 12–256; patch `{ display_name?, role?, active?, password? }` | `StaffUser & { locked_until: string \| null }` (`201` on create); list → paginated, ordered by username. A weak password or invalid username → `422`. A password reset ends all of that user's sessions; deactivation and role changes apply on their next request. Deactivating or demoting your own account → `409 CONFLICT`. Unknown id → `404`. Unlock clears the lockout and the failure count; a username that is already taken (ignoring case) → `409 CONFLICT` | IMP-04 |

Every write adds an audit row with `actor_type = "staff"` and the staff user id, in the same transaction as the change (GAP-18).

Known gaps in the implementation (not verified by a test, found by reading the code):
