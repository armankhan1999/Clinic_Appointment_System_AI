# Threat Model

Method: STRIDE per trust boundary, plus LLM-specific threats (OWASP Top 10 for LLM Applications categories, named descriptively). Scope: the architecture in `docs/architecture/`. Data is synthetic (A4); the model assumes real patient data might one day be used, so controls are designed for that.

## Assets

| Asset | Sensitivity |
|---|---|
| Patient identity (name, phone, Telegram ID) | Personal data (DPDP Act 2023 in India) |
| Appointments (who sees which doctor, when) | Personal data; doctor specialty can imply health information |
| Staff credentials and sessions | High |
| Telegram bot token, Gemini API key, DB credentials | Critical: full impersonation or data access |
| Audit log | Integrity-critical (BO-5) |
| Approved FAQ content | Integrity (patients rely on it) |

## Trust boundaries

1. Patient ↔ Telegram ↔ bot (untrusted text, contacts and button callbacks)
2. Bot ↔ Gemini (LLM output is untrusted; prompts leave our boundary)
3. Browser ↔ Next.js ↔ API (untrusted staff input; session cookies)
4. Services ↔ Supabase Postgres (network, credentials)
5. Developer ↔ repository and CI (secrets, supply chain)

## Threats and controls

| ID | Threat | STRIDE / LLM | Control | Verified by |
|---|---|---|---|---|
| T-01 | Patient makes the agent read or change another patient's booking ("show APT-000045") | Info disclosure / Elevation; prompt injection | `patient_id` comes only from the Telegram session (AGT-13); every query scoped by it; foreign refs → `NOT_FOUND` | E3-S1-AC3, E7-S4-AC1, eval category "Prompt injection" |
| T-02 | Injection makes the agent write without consent | Tampering; excessive agency | Write tools only create a PendingAction; the write happens on a button tap handled by code, not the LLM | E2-S3-AC1, E7-S4-AC3 |
| T-03 | Injection via FAQ content ("ignore rules…") | Indirect prompt injection | FAQ returned as quoted data field; prompt rule; writes still gated | E7-S4-AC3 |
| T-04 | Agent invents slots, fees or doctors | Misinformation | Slots and doctors only from tools; grounding check on replies; slot buttons rendered from tool results | E2-S1-AC3, E2-S2-AC4, EVAL-07 |
| T-05 | Agent gives medical advice | Patient harm | Prompt rule + refusal tests; emergency keyword filter before the LLM | E5-S2, E5-S3, EVAL-04/05 |
| T-06 | Forged callback data (tapping Confirm for another user's action) | Spoofing / Tampering | Callback tokens are random, stored per Telegram user, single use and short-lived; the server looks up (user, token); patient ID never comes from callback data | Unit + integration tests |
| T-07 | Someone registers another person's phone | Spoofing | Accept only a contact whose `user_id` equals the sender (E1-S2-AC2); phone already linked → reject + handoff (E1-S2-AC4) | E1-S2 tests |
| T-08 | Message flooding or LLM cost abuse | DoS / unbounded consumption | 20 msg/min, 1,000-char limit, ≤ 5 tool calls per message, max 3 upcoming bookings | E7-S3, E7-S4-AC2 |
| T-09 | Staff password brute force | Spoofing | argon2id; 5-in-15-min lockout; per-IP login rate limit; generic errors | E6-S1-AC2/AC3 |
| T-10 | Session theft / CSRF on the dashboard | Spoofing / Tampering | HttpOnly + Secure + SameSite cookie; hashed server-side sessions; CSRF double-submit; CSP; same-origin API | Integration + E2E tests |
| T-11 | Receptionist reaches admin functions | Elevation | Role dependency on every admin route; matrix test over all routes | E6-S1-AC4, E7-S2-AC3 |
| T-12 | SQL injection | Tampering | SQLAlchemy parameterised queries only; no string-built SQL | Code review, tests with hostile input |
| T-13 | XSS on the dashboard via patient names or FAQ | Tampering | React escaping; no `dangerouslySetInnerHTML`; CSP; server-side validation of names | Tests |
| T-14 | Audit log tampering | Repudiation | App role has INSERT/SELECT only; trigger blocks UPDATE/DELETE | Integration test |
| T-15 | Secrets leaked in repo, logs or LLM prompts | Info disclosure | `.env` git-ignored; secret scan in CI; logs exclude phone/name/message text; prompts carry no patient identity (D-16) | CI scan, log tests |
| T-16 | Public exposure of tables through the Supabase Data API | Info disclosure | Schema `clinic` not exposed; RLS enabled with app-role-only policies | Integration test with anon key |
| T-17 | Patient data sent to the LLM provider: the Gemini free tier allows human review and product improvement and forbids personal data (ai.google.dev/gemini-api/terms, verified 2026-11-02) | Info disclosure / privacy | No patient name, phone or Telegram ID in prompts or tool results (D-16); registration never uses the LLM; welcome notice warns against sharing health details; free tier only with synthetic data (A4); a real pilot needs the paid tier | Unit test asserting that LLM payloads hold no PII; privacy assessment |
| T-18 | Vulnerable dependencies | Supply chain | Pinned lockfiles; `pip-audit`, `npm audit` in CI | CI |
| T-19 | Double booking via race | Tampering / integrity | Partial unique index + exclusion constraint + transaction | E2-S4-AC1/AC4 |
| T-20 | Emergency message missed by the keyword list | Safety | Documented limitation (source E5-S3 note); configurable list; LLM classifier is future scope | Eval EVAL-05 |

## Residual risks (accepted for MVP, documented)

- Keyword-based emergency detection misses some phrasings (source note, E5-S3).
- In-memory conversation state is lost on restart (by design, NFR-07): pending confirmations expire.
- Reminder sending is at-least-once if the process crashes between Telegram accepting a message and the DB update. The window is milliseconds, and the restart test covers normal restarts.
- On the free tier, whatever a tester types is sent to Google under unpaid-service terms, even though our code adds no identity. Acceptable only with synthetic personas; this is stated in the README and the welcome notice.

## Update 2026-11-03: database TLS verification (T-DB-TLS)

Finding (automated security review of commit f4f95c8): `ssl="require"` encrypts but does not verify the server, so an on-path attacker could impersonate the pooler. Control: `clinic.db.session.database_ssl` uses verify-full (CA + hostname, TLS ≥ 1.2) when `DB_SSL_ROOT_CERT` is set, and **refuses to start in production without it**. Verified 2026-11-03 against `aws-1-eu-west-3.pooler.supabase.com`: the pooler presents `*.pooler.supabase.com` signed by *Supabase Intermediate 2021 CA* → *Supabase Root 2021 CA* (server-presented root SHA-256 `80:70:25:AD:50:D4:ED:21:9D:2C:9C:7D:29:9C:00:4F:82:4E:B0:0C:F7:F6:5A:FE:F6:07:D0:7B:72:E6:CA:FA`); verification succeeds with that root and fails with an unrelated CA. Residual: dev/test fall back to `require` (with a warning) until the official `prod-ca-2021.crt` is downloaded from the dashboard and its fingerprint compared.
