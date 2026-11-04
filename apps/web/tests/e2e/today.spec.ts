import { expect, test } from "@playwright/test";

import { signIn } from "./support";

// REQUIRES THE RUNNING STACK (dashboard + FastAPI + seeded dev database). Not runnable against mocks.

test.describe("Today (E6-S2)", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, "receptionist");
  });

  test("shows the attention panel and every active doctor's day", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /Needs attention/ }).or(page.getByText("Nothing needs attention right now.", { exact: false })),
    ).toBeVisible();

    const today = new Date().toLocaleDateString("en-CA");
    const schedule = await page.request.get(`/api/v1/schedule?date=${today}`);
    expect(schedule.status()).toBe(200);
    const body = (await schedule.json()) as { doctors: { name: string }[] };
    for (const doctor of body.doctors) {
      await expect(page.getByRole("heading", { level: 2, name: new RegExp(doctor.name) })).toBeVisible();
    }
  });

  test("moves between days and keeps the date in the address", async ({ page }) => {
    await page.getByRole("button", { name: "Next day" }).click();
    await expect(page).toHaveURL(/\?date=\d{4}-\d{2}-\d{2}$/);
    await expect(page.getByRole("heading", { level: 1, name: "Schedule" })).toBeVisible();
    await page.getByRole("button", { name: "Back to today" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
  });

  test("attendance actions are disabled for appointments that have not started (E6-S5-AC2)", async ({ page }) => {
    await page.getByRole("button", { name: "Next day" }).click();
    const actions = page.getByRole("button", { name: /^Actions for / });
    test.skip((await actions.count()) === 0, "No appointments tomorrow in the seed data");
    await actions.first().click();
    await expect(page.getByRole("menuitem", { name: "Mark completed" })).toBeDisabled();
    await expect(page.getByRole("menuitem", { name: "Mark no-show" })).toBeDisabled();
  });
});
