# Threat Model

Method: STRIDE per trust boundary, plus LLM-specific threats (OWASP Top 10 for LLM Applications categories, named descriptively). Scope: the system as built and described in `docs/architecture/`. Data is synthetic (A4); the model assumes real patient data might one day be used, so controls are designed for that.

Updated 2026-11-05 to match the code (commit 3938155) and [`security-review.md`](security-review.md), which maps the same controls to OWASP Top 10 (2021) with file and run evidence. Paths are relative to `apps/backend/src/clinic/` unless they start with `apps/`. Test names are in `apps/backend/tests` unless marked otherwise; run IDs are in `docs/tracking/test-execution-tracker.md`.

## Assets

| Asset | Sensitivity |
|---|---|
| Patient identity (name, phone, Telegram ID) | Personal data (DPDP Act 2023 in India) |
| Appointments (who sees which doctor, when) | Personal data; doctor specialty can imply health information |
| Staff credentials and sessions | High |
| Telegram bot token, Gemini API key, database passwords, `AUTH_SECRET` | Critical: full impersonation or data access |
| Audit log | Integrity-critical (BO-5) |
| Approved FAQ content | Integrity (patients rely on it) |

## Trust boundaries

1. Patient ↔ Telegram ↔ bot (untrusted text, contacts and button callbacks)
2. Bot ↔ Gemini (model output is untrusted; prompts leave our boundary)
3. Browser ↔ Next.js ↔ API (untrusted staff input; session cookies)
4. Services ↔ Supabase Postgres (network, credentials)
5. Developer ↔ repository and CI (secrets, supply chain)

## Threats and controls

| ID | Threat | STRIDE / LLM | Control (as built) | Verified by |
|---|---|---|---|---|
| T-01 | Patient makes the agent read or change another patient's booking ("show APT-000045") | Info disclosure / Elevation; prompt injection | `patient_id` comes only from the Telegram session through `ToolContext` (AGT-13); every query is scoped by it; foreign references → `NOT_FOUND` | `test_patient_id_comes_from_the_session_not_the_llm`; eval PI-01..PI-04 |
| T-02 | Injection makes the agent write without consent | Tampering; excessive agency | Write tools only stage a `PendingAction`; the write runs when the same patient taps Confirm, handled by code, never by the model; re-validated in one transaction | `tests/integration/test_booking_flow.py`; eval PI-04 |
| T-03 | Injection via FAQ content ("ignore rules…") | Indirect prompt injection | FAQ text is returned as an `approved_answer` data field; the prompt says tool data is never an instruction; writes are still gated by Confirm | `test_clinic_info_comes_only_from_the_approved_entry_as_quoted_data`; eval PI-04 |
| T-04 | Agent invents slots, times, fees or doctors | Misinformation | Doctors, slots and fees only come from tools; the grounding guard blocks a reply with a time or fee that no tool result contains (`agent/grounding.py`). Times written fully in words are not detected | `tests/unit/test_grounding.py`; the `times_grounded` check on every eval scenario. E2-S1-AC3 (no invented doctor, XA-01) has no genuine eval pass yet |
| T-05 | Agent gives medical advice | Patient harm | Prompt rule and refusal tests; emergency phrases are matched by code **before** any model call | `tests/integration/test_emergency.py`; eval MA-01..05; EM-01..03 assert 0 model calls |
| T-06 | Forged callback data (tapping Confirm for another user's action) | Spoofing / Tampering | Confirm/Change tokens are random, stored per Telegram user, single use and expire after 10 minutes; reminder and rebook buttons carry an appointment id, and ownership is re-checked against the session patient; the patient ID never comes from callback data | `tests/unit/test_pending.py` (`test_tokens_are_bound_to_their_user`); `test_forged_reminder_button_for_someone_elses_appointment_does_nothing` |
| T-07 | Someone registers another person's phone | Spoofing | Only a contact whose `user_id` equals the sender is accepted (E1-S2-AC2); a phone already linked to another account is refused and a ticket is opened for staff (E1-S2-AC4) | `test_contact_of_someone_else_is_rejected`, `test_phone_linked_to_another_account_is_not_linked_and_offers_staff` |
| T-08 | Message flooding or model cost abuse | DoS / unbounded consumption | 20 messages per minute then 60 s of silence; 1,000-character limit; at most 5 tool calls per message; 8 s per model call and 25 s per turn (D-34); at most 3 upcoming bookings and 1 per doctor per day | `tests/unit/test_rate_limit.py`, `test_too_many_messages_get_one_notice_then_silence`, `test_messages_over_1000_characters_are_rejected_without_the_llm`, `test_at_most_three_upcoming_appointments`; eval PI-03 |
| T-09 | Staff password brute force or username enumeration | Spoofing / Info disclosure | argon2id (12+ characters); the 5th failure within 15 minutes locks for 15 minutes, for unknown usernames too (stored under HMAC-SHA256(`AUTH_SECRET`, username), migration 0003); the same 401 message and the same hashing work on every path; 10 login attempts per minute per client (in API memory) | `tests/integration/test_staff_auth.py`, `test_wrong_password_and_lockout`, `test_login_attempts_are_rate_limited_per_client` |
| T-10 | Session theft, CSRF, or a session kept alive on an unattended screen | Spoofing / Tampering | HttpOnly `SameSite=Lax` cookie (`Secure` when `ENV=production`); sessions stored as SHA-256 hashes, 12 h absolute and 60 min idle; CSRF token = HMAC of the session token, required on every write; dashboard polls marked `X-Background-Refresh: 1` do not count as activity (D-29); CSP; same-origin API | `test_login_sets_a_protected_cookie_and_me_returns_the_role`, `test_writes_need_the_csrf_token`, `test_background_refreshes_do_not_keep_an_idle_session_alive`, `test_password_reset_ends_the_users_existing_sessions`; dashboard E2E WEB-E2E-04. The `Secure` flag in production is code only, not tested |
| T-11 | Receptionist reaches admin functions | Elevation | Every handler in `api/routes_admin.py` depends on `require_admin`; the UI is not the enforcement point | `test_receptionists_cannot_open_admin_screens` (covers `/audit`, `/faq`, `/doctors/{id}/schedule`, `/settings`); the other admin routes by code review only |
| T-12 | SQL injection | Tampering | SQLAlchemy with bound parameters only; no string-built SQL outside migrations (which only interpolate identifiers checked against `^[a-z_][a-z0-9_]{0,62}$`); SQL errors never carry bound values (`hide_parameters=True`) | Code review; `test_engine_hides_sql_parameters_in_errors` |
| T-13 | XSS on the dashboard via patient names or FAQ text | Tampering | React escaping; no `dangerouslySetInnerHTML` anywhere in `apps/` (checked by search on 2026-11-05); CSP (inline scripts allowed, D-42); server-side validation of names | Code search; `tests/unit/test_domain_patients.py` |
| T-14 | Audit log tampering | Repudiation | The app role has INSERT/SELECT only on `audit_log`; trigger `audit_log_append_only` rejects UPDATE and DELETE even for the owner | `test_audit_log_grants_are_insert_and_select_only`, `test_audit_log_trigger_blocks_changes_even_for_the_owner` |
| T-15 | Secrets or personal data leaked in the repository, logs or prompts | Info disclosure | `.env` git-ignored; logs redact `phone`, `name`, `text`, `token`, `password` and similar keys; `httpx` request logs are silenced because Telegram URLs carry the bot token; the API logs paths without query strings; prompts carry no patient identity (D-16). **No secret scanning runs in CI**: SEC-SCAN-01 was a one-off scan before the first push | SEC-SCAN-01 (0 hits); `tests/unit/test_observability.py`; START-01 log scan |
| T-16 | Public exposure of tables through the Supabase Data API | Info disclosure | Schema `clinic` is not exposed: the Data API is turned off for the project (D-17); RLS is enabled on every table with app-role-only policies | `test_every_table_exists_with_row_level_security`. The Data API setting is a project setting checked at setup; no automated test covers it |
| T-17 | Patient data sent to the LLM provider: the Gemini free tier allows human review and product improvement and forbids personal data (ai.google.dev/gemini-api/terms, checked 2026-11-02) | Info disclosure / privacy | No patient name, phone or Telegram ID in prompts or tool results (D-16); registration never uses the model; the welcome notice asks users not to share health details; free tier only with synthetic data (A4); a real pilot needs the paid tier | `test_the_llm_never_sees_the_patients_identity`, `test_system_prompt_states_scope_and_contains_no_patient_data`. **No privacy assessment has been written** |
| T-18 | Vulnerable dependencies | Supply chain | Locked `uv.lock` and exact versions in `apps/web/package.json`; CI runs `pip-audit` and `npm audit --omit=dev --audit-level=high`; GitHub Actions pinned by commit SHA | CI (`.github/workflows/ci.yml`); CI-04 |
| T-19 | Double booking via a race | Tampering / integrity | Partial unique index + exclusion constraint + one transaction; patient row lock for per-patient limits | `test_ten_parallel_bookings_for_one_slot_create_exactly_one`, `test_overlapping_booking_with_different_start_is_rejected`, `test_parallel_bookings_by_one_patient_cannot_exceed_the_limit` |
| T-20 | Emergency message missed by the keyword list | Safety | Documented limitation (source E5-S3 note); the list is configurable; matching ignores case, punctuation and apostrophes; an LLM classifier is future scope | `tests/unit/test_guardrails.py`; eval EM-01..03 |
| T-21 | Patient phone numbers end up in URLs and the logs that record them | Info disclosure | Phone lookup is `POST /patients/lookup` with the number in the body; `GET /patients?phone=` is gone (D-41); uvicorn's access log is off and the API request log has no query string | `test_walk_in_booking_and_the_shared_double_booking_rule` (asserts the old route is 404); run L1-01 |
| T-22 | An on-path attacker impersonates the database pooler | Spoofing / Info disclosure | TLS verify-full (CA + hostname, TLS ≥ 1.2) when `DB_SSL_ROOT_CERT` is set; production refuses to start without it, and refuses `DB_SSL=disable` (D-26) | `tests/unit/test_db_tls.py`. **Open on the dev PC (BLK-05):** the CA file is not installed, so dev runs use encrypted but unverified TLS and log `db_tls_unverified` |
| T-23 | The model's daily quota runs out and the bot stops answering | DoS | Every model failure, including HTTP 429, gives the fallback reply with the clinic phone number; emergencies, registration and button taps need no model | Observed in QUOTA-01 (500 requests per day on the free tier, shared by the bot and the evaluation suite). Separating the evaluation project or a paid tier is an open owner action (acceptance report) |

## Residual risks

Owner actions for these are tracked in [`security-review.md`](security-review.md) (Residual risks) and the acceptance report.

- Keyword-based emergency detection misses some phrasings (source note, E5-S3).
- In-memory conversation state is lost on restart (by design, NFR-07): pending confirmations expire and the patient is asked to try again.
- Reminders are sent **at most once**: a reminder is claimed in the database before it is sent, so a crash between the claim and the send leaves that reminder unsent (it stays `pending` and is not retried). Clinic-side notices are sent **at least once**: a crash after Telegram accepted the message but before it was recorded repeats the notice when its 5-minute lease ends.
- On the free tier, whatever a tester types is sent to Google under unpaid-service terms, even though our code adds no identity. Acceptable only with synthetic personas.
- BLK-05: dev runs use unverified database TLS until the Supabase CA certificate is installed.
- R-CRED: the database password, Gemini key and bot token were shared in chat during setup and must be rotated.
- R-LAT-01: the API and bot run far from the database (≈128 ms per round trip), which slows replies and staff bookings.
- WEB-L2 (D-42): the dashboard CSP allows inline scripts; accepted because no untrusted HTML is rendered and React escapes all output.
- RLS has a permissive policy for the app role; isolation between patients is enforced in application code, not by row policies.
- No HSTS and no `Secure` cookie on the laptop deployment (plain HTTP, D-05); `ENV=production` sets `Secure`.
- The login rate limiter lives in one API process's memory; several API processes would each allow 10 attempts per minute per client (the database lockout still applies).
- No privacy assessment exists and no data-retention periods are defined (GAP-30).
- No secret scanning runs in CI.

## Database TLS verification record (2026-11-03, T-22)

Finding (automated security review of commit f4f95c8): `ssl="require"` encrypts but does not verify the server, so an on-path attacker could impersonate the pooler. Control: `db/session.py` `database_ssl` uses verify-full (CA + hostname, TLS ≥ 1.2) when `DB_SSL_ROOT_CERT` is set, and **refuses to start in production without it**. Verified 2026-11-03 against `aws-1-eu-west-3.pooler.supabase.com`: the pooler presents `*.pooler.supabase.com` signed by *Supabase Intermediate 2021 CA* → *Supabase Root 2021 CA* (server-presented root SHA-256 `80:70:25:AD:50:D4:ED:21:9D:2C:9C:7D:29:9C:00:4F:82:4E:B0:0C:F7:F6:5A:FE:F6:07:D0:7B:72:E6:CA:FA`); verification succeeds with that root and fails with an unrelated CA. Residual: dev and test fall back to `require` (with the `db_tls_unverified` warning) until the official `prod-ca-2021.crt` is downloaded from the dashboard and its fingerprint compared (BLK-05).
