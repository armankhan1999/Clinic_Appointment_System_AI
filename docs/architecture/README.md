# Architecture — Design Spec (for approval)

Status: **APPROVED** by Arman on 2026-11-03 (D-22). Implementation plans live in `docs/superpowers/plans/`.

| Document | Contents |
|---|---|
| [system-architecture.md](system-architecture.md) | Context, processes, package layering, repo layout, deployment, verified platform facts, cross-cutting concerns |
| [database-design.md](database-design.md) | ERD, every entity with constraints and indexes, double-booking defences, DB access control, migrations |
| [agent-design.md](agent-design.md) | Message pipeline, confirmation gate, 8 tools, guardrails, Gemini integration, privacy, failure handling, eval suite |
| [api-and-auth.md](api-and-auth.md) | REST conventions, endpoint catalogue with roles, staff auth flow, CSRF, headers |
| [../security/threat-model.md](../security/threat-model.md) | Assets, trust boundaries, 20 threats with controls, residual risks |

## Design in one paragraph

Patients chat with a Telegram bot. Each message passes deterministic guardrails (emergency filter first, then rate and length limits). Unregistered users go through a code-only consent → phone → name flow. Registered patients reach a plain Gemini tool-calling loop that can act only through 8 Pydantic-validated tools. The patient ID is injected from the session, and write tools only stage a pending action that executes when the patient taps Confirm, with revalidation inside a Postgres transaction. A partial unique index enforces the no-double-booking rule (plus an exclusion constraint where available). Staff use a Next.js dashboard that reaches FastAPI same-origin, with argon2id passwords, server-side sessions and role checks in the API. Reminders and clinic-side notices run on the bot's scheduler with database-enforced idempotency. Supabase Postgres (schema `clinic`, Data API off, least-privilege app role) is the single source of truth.

## Dependencies to be added (approval of this spec approves these)

Backend (uv, pinned in `uv.lock`): fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy[asyncio], asyncpg (D-25, replaces psycopg[binary]), alembic, python-telegram-bot[job-queue], google-genai, argon2-cffi, structlog, phonenumbers (E.164 normalisation). Dev: pytest, pytest-asyncio, httpx, ruff, mypy, pip-audit.
Web (npm, pinned in `package-lock.json`): next, react, react-dom, typescript, tailwindcss, shadcn/ui components (Radix-based, copied into the repo), lucide-react, @tanstack/react-query, react-hook-form, zod, @hookform/resolvers, date-fns-tz or Intl (decided at implementation). Dev: eslint, vitest, @testing-library/react, @playwright/test.
`phonenumbers` and the date library are the only choices beyond the stack you named; versions are checked for maintenance and advisories when added.

## What is deliberately not built (YAGNI, per source scope)

Multi-clinic tenancy, payments, medical records, web chat for patients, WhatsApp/SMS, LangGraph, doctor logins, LLM-based emergency classifier, live cloud deployment.

## Prerequisites from you before Milestone 1

1. One Supabase Free project (D-17: schemas `clinic` and `clinic_test`), with the Data API turned off. Session-pooler details and the owner password go in `.env` only, never in chat.
2. A Telegram bot token from @BotFather (dev bot).
3. A Gemini API key from Google AI Studio, and its free-tier limits shown there (RPM/RPD) for the chosen models.
