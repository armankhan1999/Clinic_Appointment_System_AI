# Dependency Tracker

## Story dependencies (from the source)

| Story | Depends on | Sprint | Dependency sprint(s) | Order OK? |
|---|---|---|---|---|
| E1-S2 | E1-S1, E1-S3 | 1 | E1-S1→S1, E1-S3→S1 | Yes |
| E1-S4 | E1-S2, E3-S3 | 6 | E1-S2→S1, E3-S3→S3 | Yes |
| E2-S2 | E2-S1 | 2 | E2-S1→S1 | Yes |
| E2-S3 | E2-S2 | 2 | E2-S2→S2 | Yes |
| E2-S5 | E2-S2 | 3 | E2-S2→S2 | Yes |
| E3-S1 | E2-S3 | 3 | E2-S3→S2 | Yes |
| E3-S2 | E3-S1, E2-S4 | 3 | E3-S1→S3, E2-S4→S2 | Yes |
| E3-S3 | E3-S1 | 3 | E3-S1→S3 | Yes |
| E4-S1 | E2-S3 | 4 | E2-S3→S2 | Yes |
| E4-S2 | E4-S1 | 4 | E4-S1→S4 | Yes |
| E4-S3 | E4-S1, E3-S2, E3-S3 | 4 | E4-S1→S4, E3-S2→S3, E3-S3→S3 | Yes |
| E4-S4 | E6-S3 | 5 | E6-S3→S5 | Yes |
| E6-S2 | E6-S1 | 5 | E6-S1→S5 | Yes |
| E6-S3 | E6-S1 | 5 | E6-S1→S5 | Yes |
| E6-S4 | E6-S2, E2-S4 | 5 | E6-S2→S5, E2-S4→S2 | Yes |
| E6-S5 | E6-S2 | 6 | E6-S2→S5 | Yes |
| E6-S6 | E6-S5 | 6 | E6-S5→S6 | Yes |
| E7-S2 | E7-S1 | 1 | E7-S1→S1 | Yes |
| E7-S4 | E2-S3, E3-S1 | 6 | E2-S3→S2, E3-S1→S3 | Yes |
| E7-S5 | E2 to E5 P0 stories | 6 | E2-S1→S1, E2-S2→S2, E2-S3→S2, E2-S4→S2, E3-S1→S3, E3-S2→S3, E3-S3→S3, E4-S1→S4, E4-S3→S4, E5-S2→S3, E5-S3→S2 | Yes |
| E7-S6 | E7-S1 | 6 | E7-S1→S1 | Yes |

Ordering issues found: none

## External and environment dependencies

| ID | Dependency | Needed for | Status | Owner | Notes |
|---|---|---|---|---|---|
| DEP-EXT-01 | Telegram bot token (@BotFather) | E1–E5 live testing, demo (SC-01) | AVAILABLE | Arman | In `.env` only (NFR-03). Verified 2026-11-03: `check_env.py` telegram PASS (@clinic_dev_project_bot) |
| DEP-EXT-02 | LLM provider API key (Gemini, D-03) | Agent, evaluation suite (E7-S5) | AVAILABLE | Arman | In `.env` only. Verified 2026-11-03: `check_env.py` gemini PASS. Free-tier RPM/RPD still to be read from AI Studio (R-GEM-01) |
| DEP-EXT-03 | PostgreSQL for dev/test: hosted Supabase `hegcbpzondwcioarmiks` (D-02, D-17) | Migrations, integration and concurrency tests | AVAILABLE | Arman | Verified 2026-11-03: bootstrap applied via MCP; roles `clinic_migrator`/`clinic_app`/`clinic_test_app` log in through `aws-1-eu-west-3.pooler.supabase.com:5432` with client TLS; schema isolation verified; Postgres 17.11; btree_gist 1.7; security advisor 0 lints |
| DEP-ENV-01 | Python runtime | Backend, bot, scheduler, tests | AVAILABLE | — | Python 3.14.3 + uv 0.10.7 installed; version to pin decided at scaffold |
| DEP-ENV-02 | Node.js | Next.js dashboard (if D-01 picks it) | AVAILABLE | — | Node v24.13.0, npm 11.6.2 |
| DEP-ENV-03 | git | Version control | AVAILABLE | — | git 2.53.0; repository initialised, branch `chore/environment-setup` |
| DEP-ENV-04 | Ollama | Local LLM fallback (E7-S6 option) | NOT INSTALLED | Arman | Only if D-03 picks a local model |
