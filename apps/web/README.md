# Front Desk (staff dashboard)

Requires Node.js 22 or newer (Next.js needs 20.9+; the test tooling's jsdom dependencies declare 22.22+ or 24.15+). Next.js 16 App Router, TypeScript (strict), Tailwind CSS v4, shadcn/ui (Radix), TanStack Query, React Hook Form + Zod. Built against the contract in [`docs/api/staff-api.md`](../../docs/api/staff-api.md); design rules in [`docs/design/design-system.md`](../../docs/design/design-system.md).

## Run (PowerShell)

```powershell
Set-Location apps/web
npm ci
$env:API_PORT = "8010"   # the port clinic-api listens on; 8000 by default
npm run dev              # http://localhost:3000, API reached through /api/v1 on the same origin
```

`API_PORT` is read when `next dev` or `next build` starts and is written into the build (`.next/routes-manifest.json`), so set it before building and rebuild after changing it. Production: `npm run build` then `npm run start`.

## Checks

```powershell
npm run lint
npx tsc --noEmit
npm run test        # Vitest + Testing Library (jsdom), fetch stubbed
npm run build
npm run test:e2e    # Playwright, REQUIRES the running stack (see below)
```

### End-to-end tests

`tests/e2e` drives the real dashboard, FastAPI and the seeded dev database; nothing is mocked. Before running:

1. Start the API (`apps/backend`: `uv run clinic-api`) and the dashboard (`npm run dev` or `npm run start`).
2. Create one admin and one receptionist account in the dev database and set `E2E_ADMIN_USERNAME`, `E2E_ADMIN_PASSWORD`, `E2E_RECEPTIONIST_USERNAME`, `E2E_RECEPTIONIST_PASSWORD` (see `.env.example`).
3. `npx playwright install chromium` once.

`global-setup.ts` stops the run with an explanation if the accounts are not set or `/api/v1/auth/me` does not return the API's 401 envelope.

The specs cover every staff screen (sign-in and lockout, Today and the attention panel, attendance, booking, doctors, hours and leave, clinic answers, activity log, weekly numbers, staff accounts, settings). They write to the dev database and clean up after themselves:

- What the staff API cannot create (handoff tickets, emergency alerts, call flags, appointments that already started) comes from `apps/backend/tests/e2e_support` fixtures, run through `uv run` from `apps/backend`. They write to the dev schema only, refuse `ENV=production`, mark every row (`Playwright …` names, `e2e_tmp_` usernames), and `cleanup.py` deletes only marked rows. The fixtures read the repository `.env`; from a git worktree without it, set `UV_ENV_FILE` to that file (uv splits this variable on spaces, so use a path without spaces, such as its 8.3 short form).
- Settings, weekly hours and leave days are restored; seed data is never deleted. The time-zone test switches to an alias with the same rules, so times never move.
- The API allows 10 sign-in attempts per minute from one address, shared with every browser on the PC. Specs reuse one session per role (`signInAs`) and `submitLogin` paces all sign-ins to 7 per minute; the lockout and staff-account specs use throwaway accounts, never the E2E accounts.

## Layout

| Path | Contents |
|---|---|
| `app/` | Routes: `login`, `(staff)` (session gate + shell), `(staff)/admin/*` (admin gate) |
| `features/` | Screen components: `today`, `booking`, `admin/{doctors,faq,settings,staff,audit,metrics}`, `auth` |
| `components/` | Shell, states (loading/empty/error/forbidden), status pills, confirm dialog, toasts; `ui/` is shadcn source |
| `lib/api/` | Typed client (`client.ts`), contract schemas (`schemas.ts`), endpoints, `ApiError` |
| `lib/validation/` | Zod form schemas, including the weekly-schedule rules |
| `proxy.ts` | Optimistic redirect to `/login` when the session cookie is missing (authorization stays in the API) |

## Security notes

- Session: HttpOnly `clinic_session` cookie set by the API; the CSRF token is held in memory only and sent as `X-CSRF-Token` on every write. No tokens in `localStorage`/`sessionStorage`.
- A 401 clears cached data and does a full navigation to `/login?next=…` (validated against open redirects). A 403 shows a "not allowed" state.
- Errors show the API's message and its `request_id` ("Support reference"). The console never receives response values (patient names or phones).
- Headers from `next.config.ts`: CSP (no `unsafe-eval` in production; `unsafe-inline` scripts are needed by Next.js without per-request nonces), `nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` + `frame-ancestors 'none'`, minimal `Permissions-Policy`. HSTS belongs on the HTTPS terminator when there is one.
