# API Architecture and Staff Authentication

The FastAPI service exposes `/api/v1` to the staff dashboard only. Patients never call the API: they use Telegram, and the bot process calls the same Python service layer in-process. The service layer, not the transport, is therefore where every business and authorization rule lives (BRD §3.8: bot and dashboard share one booking service).

## Conventions

- Versioned under `/api/v1`; JSON; OpenAPI at `/api/v1/openapi.json`. Swagger UI is enabled only when `ENV=development`.
- Error envelope everywhere: `{"error": {"code": "SLOT_TAKEN", "message": "human readable", "request_id": "…", "details": {…}}}`. No stack traces or internals reach clients.
- Domain result codes double as API error codes (`SLOT_TAKEN`, `WITHIN_CUTOFF`, `LIMIT_REACHED`, `INVALID_DATE`, `NOT_FOUND`, `VALIDATION_ERROR`, `FORBIDDEN`, `UNAUTHENTICATED`, `ACCOUNT_LOCKED`, `RATE_LIMITED`).
- List endpoints: cursor or `page`/`page_size` (max 100), with explicit sort and filter parameters.
- Every request gets an `X-Request-ID` (accepted if well-formed, else generated). It is bound into the structured logs and audit rows (IMP-11).
- Health: `GET /healthz` (process up) and `GET /readyz` (database reachable). Neither requires auth or exposes detail.

## Endpoint catalogue

R = receptionist, A = admin (admin inherits receptionist). Every endpoint except login and health requires a session.

| Method & path | Role | Purpose | Source |
|---|---|---|---|
| POST `/auth/login` | public (rate-limited) | Username + password → session cookie; lockout rule | E6-S1-AC1/AC3 |
| POST `/auth/logout` | R | Revoke session | E6-S1 |
| GET `/auth/me` | R | Current user, role, CSRF token | E6-S1-AC1 |
| GET `/schedule?date=` | R | Per-doctor appointments: time, patient name, phone, status, source, reminder status, patient-confirmed, staff-attention flag | E6-S2-AC1/AC2 |
| GET `/attention` | R | Open handoff tickets + unacknowledged emergency alerts + flagged appointments | E6-S2-AC3, E4-S4-AC2 |
| GET `/availability?doctor_id=&date=` | R | Free slots (same service as the bot tool) | E6-S4 |
| GET `/patients?phone=` | R | Exact-phone lookup for walk-ins (no listing of all patients) | E6-S4-AC1 |
| POST `/appointments` | R | Staff booking `{doctor_id, start_time, patient: {id} \| {full_name, phone, verbal_consent: true}}` → `source=staff` | E6-S4-AC1/AC2 |
| POST `/appointments/{id}/cancel` | R | `{reason}`; enqueues patient notification when a Telegram link exists | E6-S4-AC3, E4-S4-AC1 |
| POST `/appointments/{id}/attendance` | R | `{status: completed \| no_show}`; only when start time has passed | E6-S5 |
| POST `/appointments/{id}/clear-attention` | R | Staff called the patient | E4-S4-AC2 |
| POST `/tickets/{id}/resolve` | R | Saves status, resolver and time | E5-S4-AC2 |
| POST `/alerts/{id}/acknowledge` | R | | E5-S3-AC3 |
| GET/POST/PATCH `/doctors` | A | Manage doctors and active flag | IMP-01 |
| GET/PUT `/doctors/{id}/schedule` | A | Replace weekly pattern (rows incl. breaks); validation | E6-S3-AC1/AC2 |
| POST `/doctors/{id}/leaves/preview` | A | Lists booked appointments the leave would affect | E6-S3-AC3 |
| POST `/doctors/{id}/leaves` | A | `{date, reason, confirm_affected: true}` → cancels affected, enqueues notices | E6-S3-AC3, E4-S4 |
| DELETE `/doctors/{id}/leaves/{leave_id}` | A | | E6-S3 |
| GET/POST/PATCH/DELETE `/faq` | A | Approved clinic info | IMP-02, E5-S1-AC3 |
| GET/PATCH `/settings` | A | Clinic settings | IMP-05 |
| GET `/audit?from=&to=&actor_type=&action=&patient_id=` | A | Paginated, read-only | E7-S2-AC3, IMP-03 |
| GET `/metrics/weekly?week_start=` | A | Bookings by source, cancellations, no-show rate per doctor; zeros when empty | E6-S6 |
| GET/POST/PATCH `/staff-users`, POST `/staff-users/{id}/unlock` | A | Provisioning and unlock | IMP-04 |

Every write endpoint writes an audit row with `actor_type=staff` (REC for GAP-18).

## Staff authentication flow (D-08)

```mermaid
sequenceDiagram
    participant U as Browser
    participant N as Next.js (same origin)
    participant A as FastAPI
    participant DB as Postgres
    U->>N: POST /api/v1/auth/login {username, password}
    N->>A: proxied unchanged (rewrite)
    A->>DB: SELECT staff_user FOR UPDATE
    alt locked_until > now
        A-->>U: 423 ACCOUNT_LOCKED
    else verify argon2 hash
        A->>DB: success: reset counters, INSERT session(token_hash), audit
        A-->>U: 200 + Set-Cookie session (HttpOnly, Secure, SameSite=Lax, Path=/)
    else wrong password
        A->>DB: failed_attempts++ (window from first_failed_at); lock 15 min at 5th failure in 15 min, audit
        A-->>U: 401 generic "invalid credentials"
    end
    U->>N: later requests carry cookie + X-CSRF-Token on writes
    N->>A: proxied
    A->>DB: look up session by SHA-256(token); check expiry, revocation, user active, role
```

- Passwords use **argon2id** (NFR-04). The same generic error is returned for unknown users and wrong passwords. Hashing runs for unknown users too (equal timing), so usernames cannot be enumerated.
- Lockout: after 5 failures within 15 minutes the account is locked for 15 minutes (E6-S1-AC3). Per-IP login rate limiting runs on top.
- Session: opaque random token in an HttpOnly cookie, stored hashed server-side; 12-hour absolute expiry (one clinic day) and 60-minute idle timeout, both set in `.env`; a new token is issued at every login.
- CSRF: SameSite=Lax cookie plus a double-submit token required on every state-changing request.
- The browser talks only to the Next.js origin, which rewrites `/api/v1/*` to FastAPI. No CORS is needed, and the API port is not exposed to the browser.
- Authorization is enforced **in FastAPI dependencies** (`require_role("admin")`). The dashboard also hides admin screens, but the UI is never the enforcement point (E6-S1-AC4, E7-S2-AC3).
- Security headers: CSP, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`, HSTS when served over HTTPS.
