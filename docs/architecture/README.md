# Architecture

The design spec was approved by Arman on 2026-11-03 (D-22). These documents now describe **what was built**: they were audited against the code, the migrations and the decision log on 2026-11-05 (commit 3938155). Where the build differs from the source requirements (`docs/requirements/source/brd-prd-backlog.md`), the difference is listed below with its decision. Implementation plans from the build live in `docs/superpowers/plans/`.

| Document | Contents |
|---|---|
| [system-architecture.md](system-architecture.md) | Context, processes, package layering, repo layout, how it runs, platform facts, cross-cutting concerns |
| [database-design.md](database-design.md) | ERD, every table with constraints and indexes, double-booking defences, database access control, migrations |
| [agent-design.md](agent-design.md) | Message pipeline, confirmation gate, the 8 tools, guardrails, grounding guard, Gemini integration, time budgets, privacy, failure handling, evaluation suite |
| [api-and-auth.md](api-and-auth.md) | REST conventions, endpoint catalogue with roles, staff authentication, CSRF, idle timeout, security headers |
| [../api/staff-api.md](../api/staff-api.md) | The staff API contract: every route, request and response shape, error codes |
| [../security/threat-model.md](../security/threat-model.md) | Assets, trust boundaries, threats with controls, residual risks |

## Design in one paragraph

Patients chat with a Telegram bot. Every message first passes deterministic guardrails: the emergency phrase filter (no model call), then the per-user rate limit and the 1,000-character limit. Unregistered users go through a code-only consent → share phone → name flow. Registered patients reach a plain Gemini tool-calling loop that can act only through 8 Pydantic-validated tools. The patient ID is injected from the Telegram session, never taken from the model. Write tools only stage a pending action; the change runs when the patient taps Confirm on a summary rendered by code, and it is re-validated inside a Postgres transaction. A partial unique index and an exclusion constraint enforce the no-double-booking rule. Before a reply is sent, a grounding guard checks that every time and fee in it came from a tool result. Each model call is capped at 8 s and a whole turn at 25 s (D-34); on a timeout or error the patient gets a fallback with the clinic phone number. Reminders and clinic-side notices run as jobs inside the bot process; the API only writes outbox rows. Staff use a Next.js dashboard that reaches FastAPI through a same-origin rewrite, with argon2id passwords, server-side sessions, a CSRF token, lockout, and a 60-minute idle timeout that background polls do not extend (D-29). Supabase Postgres (schema `clinic`, reached through the session pooler with asyncpg, TLS verify-full when the CA certificate is configured, D-25/D-26) is the single source of truth.

## Built versus source

| Source requirement | What was built | Decision |
|---|---|---|
| Staff dashboard in **Streamlit** (§3.7, L252) | **Next.js 16** + TypeScript + Tailwind v4 + shadcn/ui in `apps/web` | D-01 |
| **SQLite** for development, PostgreSQL optional (§3.7 L249, DM-11) | **Postgres only**: hosted Supabase, session pooler (port 5432), asyncpg. The schema and code use Postgres-only features (exclusion constraint, `ON CONFLICT`), so SQLite is not supported | D-02, D-15a, D-17, D-25 |
| Start script **or Docker Compose** (E7-S6-AC1) | PowerShell `scripts/start.ps1`, `stop.ps1`, `restart.ps1`; there is no Compose file | D-05, D-31 |
| LLM free tier **or a local model** (CON-01, RSK-05, E7-S6-AC2) | Gemini free tier (`gemini-3.5-flash-lite`); when the model is unreachable the patient gets a fallback reply with the clinic phone number. No local model is configured | D-03, D-13, D-38 |
| Reply within 5 s for 95% of messages (NFR-01) | **Not met** on the dev PC. Each model call may take up to 8 s and a turn up to 25 s, while Telegram shows "typing…" | D-34 |
| English only in the MVP (A6) | Every message written by code is English, but the system prompt tells the model to reply "in the patient's language" (`agent/prompt.py`) | **None**: this change has no decision yet |

Kept as in the source: Telegram as the only patient channel (D-04), a plain provider-SDK tool loop with no LangGraph (AGT-14, D-01), in-memory conversation state (NFR-07, D-07), a single clinic (D-06), and custom staff auth on `staff_users` (D-08).

## Dependencies as built

Versions are the ones locked in `apps/backend/uv.lock` and pinned in `apps/web/package.json`.

- **Backend runtime:** fastapi 0.162.0, uvicorn 0.54.0, pydantic 2.14.2, pydantic-settings 2.16.2, sqlalchemy 2.1.6 (asyncio), asyncpg 0.32.0, alembic 1.20.1, python-telegram-bot 22.8 with `[job-queue]` (APScheduler 3.11.3), google-genai 2.34.0, argon2-cffi 25.1.0, structlog 26.1.0, phonenumbers 9.0.42.
- **Backend development:** pytest 9.2.0, pytest-asyncio 1.4.1.post1, httpx 0.28.1, ruff 0.17.3, mypy 2.4.1, pip-audit 2.10.1. psycopg is not a project dependency; `scripts/check_env.py` pulls it in with `uv run --with` (D-25).
- **Dashboard runtime:** next 16.4.4, react / react-dom 19.3.1, @tanstack/react-query 5.105.3, react-hook-form 7.91.0, zod 4.6.7, @hookform/resolvers 7.0.1, radix-ui 1.8.1 (shadcn/ui components are copied into `components/ui`), lucide-react 1.67.0, class-variance-authority 0.7.1, clsx 2.1.1 + tailwind-merge 3.7.0 (D-33), tw-animate-css 1.4.0. Dates use the built-in `Intl` APIs; no date library.
- **Dashboard development:** typescript 6.0.3, tailwindcss and @tailwindcss/postcss 4.3.4, eslint 9.39.5 with eslint-config-next 16.4.4, vitest 5.1.0, @testing-library/react 16.3.3, jsdom 30.1.3, @playwright/test 1.64.1.

## Not built

Out of scope by the source or by decision: multiple clinics, payments, medical records, web chat for patients, WhatsApp/SMS, LangGraph, doctor logins, an LLM-based emergency classifier (future scope in the source, E5-S3 note), a live cloud deployment (D-05), Docker Compose (D-31), and a local-model fallback.

Not done yet, although a design document or the master prompt mentions it: a Telegram webhook mode and its deployment guide, a documented backup/restore procedure, a privacy assessment, and a measured variance across repeated evaluation runs.

## Running it

Prerequisites, setup and commands are in the repository [README](../../README.md); operations and log events are in [`../operations/runbook.md`](../operations/runbook.md).
