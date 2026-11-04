import { expect, test } from "./clean-browser";

import { api, openNav, signIn, signInAs, submitLogin, uniqueLetters } from "./support";

// REQUIRES THE RUNNING STACK (dashboard + FastAPI + seeded dev database). Not runnable against mocks.

const ADMIN_SCREENS = [
  { path: "/admin/doctors", nav: "Doctors and hours" },
  { path: "/admin/faq", nav: "Clinic answers" },
  { path: "/admin/metrics", nav: "Weekly numbers" },
  { path: "/admin/audit", nav: "Activity log" },
  { path: "/admin/staff", nav: "Staff accounts" },
  { path: "/admin/settings", nav: "Clinic settings" },
];

test.describe("sign-in (E6-S1)", () => {
  test("a receptionist signs in and lands on Today with their name and role", async ({ page }) => {
    await signIn(page, "receptionist");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
    const me = (await (await page.request.get("/api/v1/auth/me")).json()) as { user: { display_name: string; role: string } };
    expect(me.user.role).toBe("receptionist");
    await openNav(page);
    await expect(page.getByText(me.user.display_name, { exact: true })).toBeVisible();
    await expect(page.getByText("Receptionist", { exact: true })).toBeVisible();
  });

  // A wrong password for a real account is checked in lockout.spec.ts on a throwaway account, so the shared
  // E2E accounts never collect failed attempts. An unknown username must get exactly the same answer.
  test("an unknown username gets the same generic message and keeps the username", async ({ page }) => {
    const username = `e2e_tmp_nobody_${uniqueLetters(8)}`;
    await page.goto("/login");
    expect(await submitLogin(page, username, "definitely-not-the-password")).toBe(401);
    await expect(page.getByText("Username or password is incorrect")).toBeVisible();
    await expect(page.getByLabel("Username")).toHaveValue(username);
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  });

  test("a signed-out visit to an admin page goes to sign-in and returns afterwards", async ({ page }) => {
    await page.goto("/admin/faq");
    await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Ffaq$/);
    await signIn(page, "admin", page.url());
    await expect(page).toHaveURL(/\/admin\/faq$/);
    await expect(page.getByRole("heading", { level: 1, name: "Clinic answers" })).toBeVisible();
  });

  test("a receptionist sees no admin navigation and is refused admin screens (E6-S1-AC4, E7-S2-AC3)", async ({ page }) => {
    await signIn(page, "receptionist");
    await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
    await openNav(page);
    await expect(page.getByRole("link", { name: "Activity log" })).toHaveCount(0);

    await page.goto("/admin/audit");
    await expect(page.getByText("You don't have access to this")).toBeVisible();

    // The API is the enforcement point, not the hidden menu.
    const res = await page.request.get("/api/v1/audit?page=1");
    expect(res.status()).toBe(403);
  });

  test("every admin screen and admin API shows a receptionist the forbidden state (E6-S1-AC4)", async ({ page }) => {
    await signInAs(page, "receptionist");
    await openNav(page);
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Today" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Book appointment" })).toBeVisible();
    for (const screen of ADMIN_SCREENS) {
      await expect(nav.getByRole("link", { name: screen.nav })).toHaveCount(0);
    }
    await expect(page.getByText("Clinic admin", { exact: true })).toHaveCount(0);

    const doctors = (await (await api(page, "GET", "/doctors?active=true")).json()) as { items: { id: string }[] };
    const doctorId = doctors.items[0]?.id;
    expect(doctorId, "at least one active doctor in the seed").toBeTruthy();
    for (const path of [...ADMIN_SCREENS.map((s) => s.path), `/admin/doctors/${doctorId}`]) {
      await page.goto(path);
      const refusal = page.getByRole("alert").filter({ hasText: "You don't have access to this" });
      await expect(refusal, path).toContainText("This page is for clinic admins");
      await expect(refusal.getByRole("link", { name: "Go to today's schedule" })).toBeVisible();
    }

    for (const path of [
      `/doctors/${doctorId}/schedule`,
      `/doctors/${doctorId}/leaves`,
      "/faq",
      "/settings",
      "/audit",
      "/staff-users",
      "/metrics/weekly?week_start=2026-11-02",
    ]) {
      expect((await api(page, "GET", path)).status(), `GET ${path}`).toBe(403);
    }
    expect((await api(page, "POST", "/doctors", { name: "Playwright Not Allowed", specialty: "None" })).status()).toBe(403);
  });

  test("an admin sees the admin navigation and can sign out", async ({ page }) => {
    await signIn(page, "admin");
    await openNav(page);
    await expect(page.getByRole("link", { name: "Activity log" })).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    const res = await page.request.get("/api/v1/auth/me");
    expect(res.status()).toBe(401);
  });
});
