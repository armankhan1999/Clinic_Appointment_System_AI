import { expect, test } from "@playwright/test";

import { credentials, openNav, signIn } from "./support";

// REQUIRES THE RUNNING STACK (dashboard + FastAPI + seeded dev database). Not runnable against mocks.

test.describe("sign-in (E6-S1)", () => {
  test("a wrong password gets the generic message and keeps the username", async ({ page }) => {
    const { username } = credentials("receptionist");
    await page.goto("/login");
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password", { exact: true }).fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
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
