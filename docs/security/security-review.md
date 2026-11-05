# Security review (2026-11-04)

Implemented controls with their evidence, mapped to the OWASP Top 10 (2021) categories, plus the residual
risks still open. Threats and trust boundaries: [`threat-model.md`](threat-model.md). Paths are relative to
`apps/backend/src/clinic` unless they start with `apps/`. Run IDs refer to
[`../tracking/test-execution-tracker.md`](../tracking/test-execution-tracker.md).

## Controls

| OWASP 2021 | Control | Where | Evidence |
|---|---|---|---|
| A01 Broken access control | Patient tools take `patient_id` from the authenticated chat session, never from model output | `agent/tools.py` `ToolContext` (built by code) | tests/unit/test_agent_loop.py `test_patient_id_comes_from_the_session_not_the_llm` (M6-FULL-01) |
| A01 | Every staff endpoint requires a session; admin screens also require the admin role (API is the enforcement point) | `api/deps.py` `current_staff`, `require_admin` | tests/integration/test_staff_api_daily.py `test_receptionists_cannot_open_admin_screens` (M5-API-01) |
| A01 | Booking changes only after the patient taps Confirm on a code-rendered summary; single-use tokens | `agent/pending.py`, `conversation/appointment_actions.py` | test_booking_flow.py, eval PI-04 (FAQ injection) |
| A01 | Separate DB roles and schemas: app role cannot reach the test schema and has no DDL; audit log is append-only (trigger + revoked UPDATE/DELETE) | migration 0001 (`audit_log_append_only`, `REVOKE … FROM app_role`) | tests/integration/test_schema.py (M6-FULL-01), `scripts/check_env.py` cross-schema check (ENV-01) |
| A02 Cryptographic failures | Database TLS verify-full when `DB_SSL_ROOT_CERT` is set; production refuses to start without it | `db/session.py` `database_ssl` (D-26) | tests/unit/test_db_tls.py (M6-FULL-01). **Open: BLK-05** (CA file not yet installed on the dev PC, so dev runs use unverified TLS and log `db_tls_unverified`) |
| A02 | Staff passwords hashed with argon2id (12+ characters); session tokens stored as SHA-256 hashes; CSRF token = HMAC of the session token, compared in constant time | `services/staff_auth.py` | tests/integration/test_staff_auth.py (M6-FULL-01) |
| A02 / A07 | Unknown-username lockout keyed by HMAC-SHA256(AUTH_SECRET, username), so the table does not reveal attempted names | migration 0003, `staff_auth.py` `_unknown_login` | test_staff_auth.py |
| A03 Injection | SQLAlchemy with bound parameters only; SQL errors never carry bound values into logs (`hide_parameters=True`) | `db/session.py` | code review; no string-built SQL outside migrations |
| A03 (prompt injection) | Tool results are data: the prompt says so, write tools only stage a confirmation, grounding check rejects times/fees not returned by code-authored tool results | `agent/prompt.py`, `agent/grounding.py` | tests/unit/test_grounding.py; eval PI-01..PI-04 |
| A04 Insecure design | Emergency phrases are matched before any model call; the model is never consulted for emergencies | `agent/guardrails.py`, `conversation/service.py` | tests/integration/test_emergency.py; eval EM-01..03 assert 0 model calls |
| A04 | Per-patient limits (3 upcoming, 1 per doctor per day) enforced under `SELECT … FOR UPDATE` on the patient row; double booking blocked by a partial unique index and an exclusion constraint | `services/booking.py`, migration 0001 | test_booking.py (10 parallel bookings → exactly 1) |
| A05 Security misconfiguration | API: `nosniff`, `no-referrer`, `default-src 'none'; frame-ancestors 'none'`, `no-store`; OpenAPI/Swagger only in development | `api/app.py` | tests/unit/test_api_health.py |
| A05 | Dashboard: CSP, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, Permissions-Policy; same-origin rewrite, no CORS | `apps/web/next.config.ts` | curl check by the frontend agent; WEB-E2E-01 |
| A05 | Session cookie `HttpOnly`, `SameSite=Lax`, `Secure` in production | `api/routes_auth.py` | test_staff_api_daily.py asserts HttpOnly and SameSite=Lax; **Secure in production is code only, not tested** |
| A07 Identification and authentication failures | Lockout after 5 failures in 15 min (also for unknown usernames, same response and same work); login rate limit 10/min per client; generic 401 message | `staff_auth.py`, `api/routes_auth.py` | test_staff_auth.py, test_staff_api_daily.py |
| A07 | Sessions end after 12 h, or 60 min without activity; dashboard polls do not count as activity (D-29); a password reset signs the user out everywhere | `staff_auth.py` `authenticate(touch=…)`, `services/admin.py` | `test_background_refreshes_do_not_keep_an_idle_session_alive`, `test_password_reset_ends_the_users_existing_sessions` (M5-API-01) |
| A08 Software and data integrity | Dependencies pinned (uv.lock, package-lock.json with exact versions); CI actions pinned by commit SHA | `apps/backend/uv.lock`, `apps/web/package.json`, `.github/workflows/ci.yml` | M1-AUDIT (pip-audit: none), `npm audit --omit=dev`: 0. GitHub Actions green on PR #1 (CI-03: backend 418 passed, web 118 passed, both audits clean) |
| A09 Logging and monitoring failures | Structured JSON logs with request IDs; redaction of chat text, names, phones and secrets; every tool call, staff write and login audited | `observability.py` `_redact`, `services/audit.py` | tests/unit/test_observability.py; START-01 log scan: 0 secret values |
| A10 SSRF | Not applicable: no server-side fetch of user-supplied URLs | — | — |
| Abuse (NFR-08) | 20 messages/min per Telegram user, then one notice and 60 s of silence; messages over 1,000 characters rejected | `agent/rate_limit.py`, `conversation/service.py` `MAX_MESSAGE_CHARS` | tests/unit/test_rate_limit.py, test_conversation_safety.py |
| Privacy (NFR-06/07) | Only name, phone, Telegram ID and appointments stored; consent before storage; `/deletemydata` anonymises; chat memory in RAM only (idle TTL); no identity sent to the model (D-16) | `services/patients.py`, `agent/memory.py`, migration 0002 | test_conversation_safety.py, test_services_patients.py |
| Secrets (NFR-03) | Secrets only in git-ignored `.env`; never printed by scripts | `.gitignore`, `scripts/check_env.py` | SEC-SCAN-01: 0 hits in history and tracked files before the first push |

## Residual risks

| ID | Risk | Status / owner action |
|---|---|---|
| BLK-05 | Dev runs use unverified database TLS until the Supabase CA certificate is installed | Arman: download the CA to `infrastructure/db/prod-ca-2021.crt`, set `DB_SSL_ROOT_CERT`, compare its SHA-256 fingerprint |
| R-CRED | The database password, Gemini key and bot token were shared in chat during setup | Arman: rotate all three; update `.env` |
| R-TESTCRED | ~~The e2e_desk dev test password appeared in a browser-tool log on 2026-11-05~~ | **Resolved (ROT-01):** rotated through the admin API, stored only in git-ignored `apps/web/.env.local`; old password refused. Later logins pass credentials through a one-shot localhost server so they never appear in tool output |
| R-LAT-01 | API and bot in India, database in eu-west-3: ~128 ms per round trip, so a staff booking takes ~6 s and the bot's 8 s budget is tight | Deploy the API/bot next to the database, or move the project to `ap-south-1` |
| WEB-L1 | ~~A phone number in the `GET /patients?phone=` URL~~ | **Resolved (D-41):** lookup is `POST /patients/lookup` with the phone in the body; the old route is gone (test asserts 404) |
| WEB-L2 | The dashboard CSP keeps `'unsafe-inline'` for scripts (Next.js inlines its page data without per-request nonces) | **Accepted (D-42)** for the single-clinic deployment: no `dangerouslySetInnerHTML` anywhere, React escapes all output, `frame-ancestors`/`X-Frame-Options` block framing, `object-src` and third-party script hosts are not allowed. A nonce CSP would force every page to render per request (today they are prerendered); revisit if the dashboard is exposed to the internet or starts rendering untrusted HTML |
| RLS | RLS is enabled with a permissive policy for the app role; isolation between patients is enforced in application code (`ToolContext`), not by row policies | Accepted for a single-clinic MVP with one app role |
| D-33 | ~~`cn@0.5.2` was pre-1.0 and two days old~~ | Resolved: replaced by `clsx` 2.1.1 + `tailwind-merge` 3.7.0 |
| HSTS | No HSTS: the demo runs over plain HTTP on a laptop (D-05) | Add HSTS and `Secure` cookies when deployed behind HTTPS (`ENV=production` already sets `Secure`) |
