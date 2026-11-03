# Release Readiness

Decision: **NOT READY** — discovery phase; no implementation exists.

States are distinct: Implemented ≠ Tested ≠ Verified ≠ Deployed ≠ Production-ready.

| Gate | Criterion | Status | Evidence |
|---|---|---|---|
| Requirements | All 20 Must stories COMPLETED with AC evidence | NOT_STARTED | — |
| Requirements | Should/Could stories COMPLETED or DEFERRED_WITH_APPROVAL | NOT_STARTED | — |
| Quality | Evaluation suite meets every §3.9 target, or the gap is explained | NOT_STARTED | — |
| Quality | Concurrency test: 10 parallel bookings → exactly 1 row | NOT_STARTED | — |
| Quality | Reminder restart and Telegram retry tests pass | NOT_STARTED | — |
| Security | Threat model reviewed; no open High/Critical findings | NOT_STARTED | — |
| Security | No secrets in repository (scan) | NOT_STARTED | — |
| Privacy | Privacy assessment written; organisational obligations listed (no compliance claim) | NOT_STARTED | — |
| Ops | One-command start ≤ 2 min (E7-S6); fallback reply without LLM | NOT_STARTED | — |
| Ops | Logs, health checks, backup/restore procedure documented and tested | NOT_STARTED | — |
| Docs | README, .env.example, API, architecture, deployment, runbooks | NOT_STARTED | — |
| Deployment | Target per D-05 deployed and smoke-tested | NOT_STARTED | — |
