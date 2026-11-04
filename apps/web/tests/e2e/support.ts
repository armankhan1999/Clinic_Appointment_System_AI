import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";

import { expect, type Cookie, type Page } from "@playwright/test";
import { z } from "zod";

export type Role = "admin" | "receptionist";

const ENV = {
  admin: ["E2E_ADMIN_USERNAME", "E2E_ADMIN_PASSWORD"],
  receptionist: ["E2E_RECEPTIONIST_USERNAME", "E2E_RECEPTIONIST_PASSWORD"],
} as const;

export const REQUIRED_ENV = [...ENV.admin, ...ENV.receptionist];

export function credentials(role: Role): { username: string; password: string } {
  const [userKey, passKey] = ENV[role];
  const username = process.env[userKey];
  const password = process.env[passKey];
  if (!username || !password) throw new Error(`Set ${userKey} and ${passKey} for the ${role} test account.`);
  return { username, password };
}

/*
 * The API allows 10 sign-in attempts per minute from one address (LOGIN_ATTEMPTS_PER_MINUTE in
 * apps/backend/src/clinic/api/app.py), and everything on this PC shares that address, the owner's own
 * browser included. Every sign-in from these specs goes through submitLogin, which keeps the run at
 * LOGIN_BUDGET attempts per rolling minute. The log is a file because each project runs in a new worker.
 */
const LOGIN_LOG = path.join(tmpdir(), "clinic-e2e-login-attempts.json");
const LOGIN_BUDGET = 7;
const LOGIN_WINDOW_MS = 60_000;

function recentLoginAttempts(now: number): number[] {
  if (!existsSync(LOGIN_LOG)) return [];
  const parsed = z.array(z.number()).parse(JSON.parse(readFileSync(LOGIN_LOG, "utf8")));
  return parsed.filter((at) => now - at < LOGIN_WINDOW_MS);
}

async function takeLoginBudget(page: Page): Promise<void> {
  for (;;) {
    const now = Date.now();
    const recent = recentLoginAttempts(now);
    if (recent.length < LOGIN_BUDGET) {
      writeFileSync(LOGIN_LOG, JSON.stringify([...recent, now]));
      return;
    }
    await page.waitForTimeout(recent[0] + LOGIN_WINDOW_MS - now + 250);
  }
}

/** Fills and submits the sign-in form; returns the HTTP status of POST /auth/login. */
export async function submitLogin(page: Page, username: string, password: string): Promise<number> {
  for (let attempt = 1; ; attempt += 1) {
    await takeLoginBudget(page);
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password", { exact: true }).fill(password);
    const answered = page.waitForResponse((r) => r.url().endsWith("/api/v1/auth/login") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Sign in" }).click();
    const status = (await answered).status();
    // 429: something else on this PC used the shared budget. The API mutes the address for 60 s.
    if (status !== 429 || attempt === 2) return status;
    await page.waitForTimeout(LOGIN_WINDOW_MS + 1_000);
  }
}

export async function signIn(page: Page, role: Role, path = "/login"): Promise<void> {
  const { username, password } = credentials(role);
  await page.goto(path);
  expect(await submitLogin(page, username, password), `sign-in as ${role}`).toBe(200);
  await expect(page.locator("main#main")).toBeVisible();
}

const sessions = new Map<Role, Cookie[]>();

/**
 * Opens `path` signed in as `role`, reusing this worker's session for the role so the specs stay within
 * the sign-in rate limit. Specs about signing in itself use signIn. Never sign out a session from here:
 * use signIn for that, so the shared session stays valid.
 */
export async function signInAs(page: Page, role: Role, path = "/"): Promise<void> {
  const cached = sessions.get(role);
  if (cached) {
    await page.context().addCookies(cached);
    if ((await page.request.get("/api/v1/auth/me")).status() === 200) {
      await page.goto(path);
      await expect(page.locator("main#main")).toBeVisible();
      return;
    }
    await page.context().clearCookies();
    sessions.delete(role);
  }
  await signIn(page, role, path === "/" ? "/login" : `/login?next=${encodeURIComponent(path)}`);
  sessions.set(role, await page.context().cookies());
}

/** On tablet widths the navigation sits in a menu sheet; open it so nav links and Sign out are visible. */
export async function openNav(page: Page): Promise<void> {
  const menu = page.getByRole("button", { name: "Open menu" });
  if (await menu.isVisible()) await menu.click();
}

/** Calls the API from the signed-in browser context (same origin, cookie + CSRF), for setup and clean-up only. */
export async function api(page: Page, method: string, path: string, body?: unknown) {
  const me = await page.request.get("/api/v1/auth/me");
  expect(me.status(), "session for API call").toBe(200);
  const { csrf_token: csrf } = (await me.json()) as { csrf_token: string };
  return page.request.fetch(`/api/v1${path}`, {
    method,
    headers: { "X-CSRF-Token": csrf, "Content-Type": "application/json" },
    data: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** A phone number unlikely to exist in the seed data (E.164-style, Indian mobile range). */
export function uniquePhone(): string {
  const tail = String(Date.now()).slice(-9);
  return `+91 9${tail.slice(0, 4)} ${tail.slice(4)}`;
}

/** Letters only: patient names may not contain digits. "Abcdef" for names, "abcdef" for slugs. */
export function uniqueLetters(length = 6): string {
  const alphabet = "abcdefghijklmnopqrstuvwxyz";
  return Array.from(randomBytes(length), (byte) => alphabet[byte % alphabet.length]).join("");
}

export function uniqueName(label: string): string {
  const letters = uniqueLetters();
  return `Playwright ${label} ${letters.charAt(0).toUpperCase()}${letters.slice(1)}`;
}

/** Today in the clinic's time zone, as the dashboard itself gets it. */
export async function clinicToday(page: Page): Promise<string> {
  const res = await page.request.get("/api/v1/clinic/today");
  expect(res.status(), "GET /clinic/today").toBe(200);
  return z.object({ date: z.string() }).parse(await res.json()).date;
}

/**
 * A doctor's section on the day schedule. Its heading reads name then specialty ("Dr. Live TestGeneral
 * Physician"), so both are matched in full: one name can be the start of another ("Dr. Live Test Two").
 */
export function doctorDay(page: Page, doctor: { name: string; specialty: string }) {
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page.getByRole("region", { name: new RegExp(`^${escape(doctor.name)}\\s*${escape(doctor.specialty)}$`) });
}

/** Formats a YYYY-MM-DD day in the browser, exactly as lib/dates formatLongDate does for the page. */
export function longDateInPage(page: Page, iso: string): Promise<string> {
  return page.evaluate(
    (day) =>
      new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(
        new Date(`${day}T00:00:00Z`),
      ),
    iso,
  );
}

/*
 * Backend fixtures (apps/backend/tests/e2e_support): synthetic rows in the DEV schema for what the staff
 * API cannot create, such as handoff tickets, emergency alerts and appointments that already started,
 * plus a marker-checked clean-up. They refuse ENV=production. The API's settings come from the repository
 * .env; outside the main checkout set UV_ENV_FILE to that file (a path without spaces, e.g. its 8.3 form).
 */
const BACKEND_DIR = path.resolve(__dirname, "../../../backend");
const execFileAsync = promisify(execFile);

async function backendFixture<S extends z.ZodType>(module: string, args: string[], schema: S): Promise<z.infer<S>> {
  const { stdout } = await execFileAsync("uv", ["run", "python", "-m", `tests.e2e_support.${module}`, ...args], {
    cwd: BACKEND_DIR,
    timeout: 120_000,
    windowsHide: true,
  });
  return schema.parse(JSON.parse(stdout));
}

const fixturePatient = z.object({ id: z.string(), full_name: z.string(), phone: z.string() });
const fixtureDoctor = z.object({ id: z.string(), name: z.string(), specialty: z.string() });
const fixtureAppointment = z.object({
  id: z.string(),
  reference: z.string(),
  date: z.string(),
  start: z.string(),
  time_label: z.string(),
});
export type FixtureAppointment = z.infer<typeof fixtureAppointment>;

const appointmentFixture = z.object({
  patient: fixturePatient,
  doctor: fixtureDoctor.optional(),
  appointments: z.array(fixtureAppointment),
});
const attentionFixture = z.object({
  patient: fixturePatient,
  doctor: fixtureDoctor,
  alert_id: z.string(),
  ticket_id: z.string(),
  appointment: fixtureAppointment,
});
const cleanupResult = z.object({
  deleted: z.object({ patients: z.array(z.string()), doctors: z.array(z.string()), staff: z.array(z.string()) }),
  missing: z.array(z.string()),
});

/** A new synthetic patient with `count` booked appointments; see appointment_fixture.py for the options. */
export function createAppointments(args: string[]) {
  return backendFixture("appointment_fixture", args, appointmentFixture);
}

/** A new synthetic patient with an open ticket, an emergency alert and a flagged appointment. */
export function createAttentionItems() {
  return backendFixture("attention_fixture", [], attentionFixture);
}

/** Deletes rows these specs created (patients with their appointments, doctors, staff accounts). */
export function cleanUp(rows: { patients?: string[]; doctors?: string[]; staff?: string[] }) {
  const args = [
    ...(rows.patients ?? []).flatMap((id) => ["--patient", id]),
    ...(rows.doctors ?? []).flatMap((id) => ["--doctor", id]),
    ...(rows.staff ?? []).flatMap((username) => ["--staff", username]),
  ];
  return backendFixture("cleanup", args, cleanupResult);
}
