import { expect, type Page } from "@playwright/test";

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

export async function signIn(page: Page, role: Role, path = "/login"): Promise<void> {
  const { username, password } = credentials(role);
  await page.goto(path);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("main#main")).toBeVisible();
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
