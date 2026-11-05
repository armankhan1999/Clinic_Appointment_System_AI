# Acceptance report (2026-11-04)

Status of the Clinic Appointment Booking Agent against the PRD (`docs/requirements/source/brd-prd-backlog.md`),
with every figure taken from a recorded run in [`../tracking/test-execution-tracker.md`](../tracking/test-execution-tracker.md).
Story and AC detail: [`../tracking/user-story-tracker.md`](../tracking/user-story-tracker.md) and
[`../tracking/requirement-traceability-matrix.md`](../tracking/requirement-traceability-matrix.md).

## What exists

| Part | Where | Notes |
|---|---|---|
| Telegram bot + Gemini tool-calling agent | `apps/backend/src/clinic/{bot,conversation,agent}` | Consent-first registration, booking/reschedule/cancel with Confirm taps, FAQ, handoff, emergency filter before the model, grounding guard |
| Booking service and database | `apps/backend/src/clinic/{services,db}`, `apps/backend/migrations` | Postgres (Supabase), double booking blocked by constraints, per-patient limits under row locks, append-only audit log |
| Reminders and notices | `services/reminders.py`, `services/notifications.py`, PTB job queue | 24 h and 2 h reminders, claimed once; outbox with retries and staff flag |
| Staff API | `apps/backend/src/clinic/api`, contract `docs/api/staff-api.md` | Session cookie + CSRF, roles, lockout, audit, pagination |
| Staff dashboard | `apps/web` (Next.js 16) | Today, booking, admin screens (doctors, schedules, leave, FAQ, settings, audit, metrics, staff accounts) |
| Evaluation suite | `apps/backend/tests/integration/test_agent_eval.py` | 35 scenarios of PRD §3.9; reports in `apps/backend/reports/`, copies in this folder |
| Packaging and CI | `scripts/start.ps1`, `scripts/stop.ps1`, `.github/workflows/ci.yml` | One-command start; CI for backend and dashboard |

## Verification summary

| Run | Result |
|---|---|
| M6-FULL-01 backend unit + integration (before the afternoon fixes) | 402 passed, 0 failed |
| GAPS-01 + follow-up (afternoon fixes) | 78 + 16 passed after one test-data fix |
| WEB-UNIT-02 dashboard lint, types, unit/component | 116 passed; lint and tsc clean |
| WEB-E2E-02 dashboard on the live stack | 18 passed, clean console and network on every test |
| START-01 / START-02 one-command start | 23.5 s (cached build), 24.0 s (fresh build) |
| FRESH-01 README steps from a clean clone (no credentials) | install, 220 + 116 tests, build: all pass |
| SEC-SCAN-01 secrets in history and tracked files | 0 hits |
| CI-01 first GitHub Actions run | **failed** (4 TLS unit tests saw the job's `DB_SSL`); fixed and reproduced locally, not yet re-run on GitHub |
| M6-FULL-02 final backend regression | 414 passed, 0 failed (37 eval/live tests deselected by design) |
| M6-FULL-03 after D-33/D-34 | 418 passed, 0 failed |
| CI-02 GitHub Actions on PR #1 | green: backend 414 passed, web 116 passed, audits clean |

## Agent evaluation against PRD §3.9 (E7-S5-AC3)

Two full runs of the same 35 scenarios, same model (`gemini-3.5-flash-lite`, free tier), same prompt
(2026-11-04.3), same pinned clock, on this PC with the database in `eu-west-3`:

| Category (§3.9 target) | Diagnostic budget 45 s ([report](eval-2026-11-04-diagnostic-budget.md)) | Production budget 8 s ([report](eval-2026-11-04-production-budget.md)) |
|---|---|---|
| Booking happy paths (≥ 90%) | 8/8 met | 0/8 not met |
| Reschedule and cancel (≥ 90%) | 6/6 met | 1/6 not met |
| Edge cases: no slots, past date, cut-off (≥ 90%) | 6/6 met | **0/6 not met** (corrected; see below) |
| Medical-advice requests (100% refused) | 5/5 met | 5/5 met |
| Emergency messages (100%, no model call) | 3/3 met (0 model calls) | 3/3 met (0 model calls) |
| Prompt injection / other patients' data (100% blocked) | 4/4 met | 4/4 met |
| Questions not in the FAQ (100% no invented answer) | 3/3 met | 1/3 not met |
| Task success rate | 100% | 40% (corrected from 57%) |
| Correct-tool rate | 100% | 54% |
| Average tool calls per task | 1.74 | 0.71 |
| p95 reply time | 23.3 s | 10.5 s |
| Median turn with model calls | 8.4 s (model 5.5 s, everything else 3.9 s) | 9.6 s (model 5.7 s) |

**Correction (2026-11-04 evening).** The first version of this report credited the production-budget runs
with 6/6 edge cases. Those six "passes" in AEV-PROD-01 (and ED-01, ED-05 in AEV-PROD-02) were fallback
replies: the checks "nothing booked" and "existing booking unchanged" are trivially true when the agent never
answers. The suite now fails any scenario whose reply is a fallback (`answered` check, D-36), and the figures
above are recounted from the saved reports: AEV-PROD-01 14/35, AEV-PROD-02 19/35. The diagnostic run
AEV-DIAG-03 had no fallback passes (35/35 stands), and the medical, emergency and injection results stand in
every run.

**Gap explanation.** Every one of the production-budget failures (and the six corrected edge passes) is the same event: the whole turn
(model calls + tool queries + audit writes) exceeded the 8 s budget and the patient received the fallback
message with the clinic phone number. No failure was a wrong answer, a wrong tool, a safety miss or a data
leak; with time to finish, the same scenarios pass 35/35. The time goes to two places:

1. **Model latency (R-GEM-02):** the free-tier model alone takes a median 5.5–5.7 s per turn, already above
   NFR-01's 5 s.
2. **Database distance (R-LAT-01):** ~128 ms per round trip from this PC to `eu-west-3` adds a median
   3.9 s per turn (DB-LAT-01).

The 8 s figure is a design choice (`docs/architecture/agent-design.md`), made to satisfy E1-S1-AC3
("fallback within 10 s when the provider is unreachable"); the PRD itself does not cap a working multi-step
turn at 8 s. Options, for the owner to decide:

| Option | Effect | Trade-off |
|---|---|---|
| A. Keep 8 s per model call (E1-S1-AC3 still holds) but allow a longer whole-turn budget (for example 25 s) and show Telegram's "typing…" status | Task success as in the diagnostic run on this PC | Slow turns stay slow; NFR-01 still not met |
| B. Run the API/bot next to the database (or move the project to `ap-south-1`) | Removes most of the 3.9 s non-model time | Infrastructure change |
| C. Paid or faster model tier | Lowers the 5.5 s model time; needed for NFR-01 | Cost |

Repeat runs: each run used `EVAL_RUNS=1`; run-to-run variance is not yet measured (§3.9 asks for N runs).

### Option A implemented (D-34) and re-measured

Arman chose option A. Each model call stays capped at 8 s (E1-S1-AC3 unchanged); a whole turn may now use 25 s
while the model keeps answering, and Telegram shows "typing…". Re-run at the new production settings
([report](eval-2026-11-04-production-split-budget.md), run AEV-PROD-02, 2026-11-04 afternoon):

| Category | AEV-PROD-01 (8 s per turn) | AEV-PROD-02 (8 s per call, 25 s per turn) |
|---|---|---|
| Booking happy paths | 0/8 | 2/8 |
| Reschedule and cancel | 1/6 | 1/6 |
| Edge cases (corrected) | 0/6 | 4/6 |
| Medical advice | 5/5 | 5/5 |
| Emergencies | 3/3 | 3/3 |
| Prompt injection | 4/4 | 4/4 |
| Not in the FAQ | 1/3 | 0/3 |
| Total (corrected) | 14/35 | 19/35 |
| Failures caused by the turn budget | 15 | **0** |
| Failures caused by one model call taking more than 8 s | 0 | **14** |
| Median model time per turn | 5.7 s | 8.0 s (max 18.9 s) |

The change removed every turn-budget failure, as intended. In this run the free-tier model itself had slowed
down (median 8.0 s per turn against 5.5–5.7 s in the morning runs), so single calls crossed the 8 s per-call
cap, which exists to keep the "fallback within 10 s when the model is unreachable" guarantee. Raising that cap
would break E1-S1-AC3; the remaining lever is model latency itself (option C: a faster or paid tier), and
option B for the 3.9 s of database time. Turns in passing scenarios took a median 7.4 s (max 22 s).

### Final production run (AEV-PROD-06, 2026-11-05 evening)

38 scenarios (35 from §3.9 plus XA-01..03), production budgets (8 s per model call, 25 s per turn), after D-50 (retry 5xx once) and D-51 (staged summary shown on model failure); one run to stay inside the free-tier quota ([report](eval-2026-11-05-production-final.md)).

| Category (target) | Result | Met |
|---|---|---|
| Booking happy paths (≥ 90%) | 4/8 | no |
| Reschedule and cancel (≥ 90%) | 5/6 | no |
| Edge cases (≥ 90%) | 6/6 | yes |
| Medical-advice requests (100%) | 5/5 | yes |
| Emergency messages (100%) | 3/3 | yes |
| Prompt injection / other patients' data (100%) | 4/4 | yes |
| Questions not in the FAQ (100%) | 3/3 | yes |
| Additional checks XA-01..03 | 1/3 | no |

Task success 82% (31/38), correct-tool rate 87%, p95 reply 20.3 s. **All seven failures are a single model call that exceeded the 8 s per-call timeout** (`llm_unavailable error=TimeoutError` ×7; no 503, no turn budget exhausted); none is a wrong, ungrounded or unsafe answer. Every safety target is met at production settings. E2-S1-AC3 (booking ≥ 90%) stays open on model latency (R-GEM-02, NFR-01): the remaining lever is D-34 option C (a faster model or paid tier), not agent logic.

## Evening status (2026-11-04)

- **Gemini quota reached.** The free tier allows **500 requests per day per project per model**
  (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, read from the API's 429 reply, QUOTA-01); today's evaluation
  runs used it up, so from about 17:45 UTC every model call returned HTTP 429 until the reset (about 13:30 IST on
  2026-11-05). The live bot shares the quota: until the reset, patients get the fallback reply with the clinic
  phone number (E1-S1-AC3 and E7-S6-AC2 behaving as designed). Before the 429s, the same model had slowed to
  11–37 s for a one-word reply.
- **Not measured yet:** a clean production-settings run of the final suite (38 scenarios). AEV-PROD-03 was
  invalidated by a network outage on this PC. To do after the quota resets: `EVAL_RUNS=2` at production settings.
- **New checks with genuine evidence:** XA-02 known FAQ answer and XA-03 refusal shape (AEV-DIAG-04); BK-01 with
  the date said back and every time grounded (AEV-DIAG-05). XA-01 (unknown specialty) has no genuine pass yet.
- **Recommendation:** run the evaluation suite in its own Google Cloud project (limits apply per project, not per
  API key, so a second key in the same project does not help), or use a paid tier, so evaluation runs can never
  use up the live bot's daily requests.
- **Model switch attempt (D-37, reverted by D-38):** `gemini-3.5-flash` answered probes in 1.5–1.6 s but its free
  tier allows only **20 requests per day** (QUOTA-02); the probes and the first evaluation calls used them up. Both
  models reset at midnight Pacific time (13:30 IST). Free-tier limits per model are shown only in AI Studio.

## Live persona tests (2026-11-05)

Every persona was exercised on the running stack (dev mode) with real Telegram and a real browser. Free-text replies were the fallback all morning because the Gemini daily quota was used up, so the AI-driven flows are listed as deferred, not passed.

| Persona | Channel | Verified live | Deferred |
|---|---|---|---|
| Patient | Telegram (Arman's account, @clinic_dev_project_bot) | consent and decline, registration, emergency reply and alert, fallback, message length and rate limits, 24 h and 2 h reminders, Confirm / Cancel / Reschedule buttons, clinic-cancel and leave notices with reason, /deletemydata prompt and Keep, /start and /help (LIVE-TG-01); FAQ, booking, listing, rescheduling and cancelling by chat, medical refusal, prompt-injection refusal, handoff, and the final /deletemydata with anonymisation checked in the database (LIVE-TG-02) | — (several AI turns needed the diagnostic 15/45 budgets: Gemini was at 6–7 s per call, see NFR-01) |
| Receptionist | Dashboard (Playwright Chromium) | Today page and reminder states, alert acknowledgement, booking (existing and walk-in with verbal consent), limit refusals, staff cancel with reason, attendance completed / no-show, admin pages and admin API denied (LIVE-DASH-01) | — |
| Clinic admin | Dashboard (Playwright Chromium) | add doctor, weekly hours, leave with affected-bookings preview and confirmation, staff accounts (create, taken username, password reset), activity log, weekly numbers, CSRF refusal (LIVE-DASH-01) | — |
| Doctor | No login (GAP-11) | needs met through the admin's hours and leave screens and the E4-S4 notices (verified above) | — |

Evening (LIVE-TG-02) fixes: D-50 Gemini 5xx retried once, D-51 staged summary shown when the model fails, D-52 reply send retried once, D-53 Markdown bold stripped. Defects found live and fixed test-first the same morning: D-43 (booking-limit hint), D-44 (taken username gave 500), D-45 (no password-reset control), D-46 (dialogs cut off on short screens), D-47 ("not due yet" for patients without Telegram), plus singular wording on the leave checkbox (d2d8e1c).

## Non-functional requirements

| NFR | Status | Evidence |
|---|---|---|
| NFR-01 reply ≤ 5 s for 95% | **Not met on this PC** | p95 10.5 s (production budget) / 23.3 s (diagnostic); model alone ≈ 5.5 s median |
| NFR-02 no duplicate or missed reminders | Met (automated) | `test_reminders_are_never_sent_twice_even_after_a_restart` (M6-FULL-01) |
| NFR-03 secrets only in `.env` | Met | `.gitignore`, SEC-SCAN-01, START-01 log scan |
| NFR-04 hashed passwords, lockout | Met | argon2id, 5 failures / 15 min (test_staff_auth.py) |
| NFR-05 patient data isolation | Met | ToolContext tests; eval PI-01..04 in both runs |
| NFR-06 data minimisation | Met | `test_patients_store_only_identity_consent_and_bookkeeping` |
| NFR-07 chat history in memory only, last 20 messages | Met | `test_memory_keeps_the_last_ten_exchanges_per_user`, `test_memory_forgets_an_idle_conversation` |
| NFR-08 rate limit, 1,000-character limit | Met | test_rate_limit.py, test_m4_conversation.py |
| NFR-09 tap buttons for confirmations and reminders | Met: automated, and tapped live in Telegram on 2026-11-05 (LIVE-TG-01: reminder Confirm, Cancel → Confirm cancel, Reschedule, Keep my data) | conversation and reminder tests; LIVE-TG-01 |
| NFR-10 tests and evaluation suite | Met | this report |
| NFR-11 JSON logs with a request id per message | Met | test_observability.py, `test_each_message_gets_its_own_request_id_shared_by_its_tool_calls` |

## Open items before go-live

| Item | Owner |
|---|---|
| Reply time: option A is in place (D-34); the remaining failures need option C (model latency) and benefit from B | Arman |
| Gemini quota: 500 requests/day on the free tier is shared by the bot and the evaluation suite; use a separate Google Cloud project for evaluations (limits are per project, not per key), or a paid tier | Arman |
| Final evaluation done (AEV-PROD-06: 31/38, all failures model timeouts). To close E2-S1-AC3: a faster model, a paid tier or a separate Google Cloud project, then rerun with `EVAL_RUNS=2` | Arman (decision) |
| BLK-05: install the Supabase CA certificate and set `DB_SSL_ROOT_CERT` (verify-full TLS) | Arman |
| ~~BLK-06~~ Done: every patient flow was used live in Telegram on 2026-11-05 (LIVE-TG-01, LIVE-TG-02), ending with /deletemydata and a database check | — |
| Rotate the database password, Gemini key and bot token shared in chat during setup | Arman |
| Review and merge PR #1 (CI green: backend 414 passed, web 116 passed, audits clean) | Arman |
| Security residual risks: [`../security/security-review.md`](../security/security-review.md) | — |
