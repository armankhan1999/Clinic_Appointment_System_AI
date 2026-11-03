import { expect, test } from "@playwright/test";

import { openNav, signIn, uniquePhone } from "./support";

// REQUIRES THE RUNNING STACK (dashboard + FastAPI + seeded dev database). Not runnable against mocks.
// Writes to the dev database: books one appointment for a new synthetic patient, then cancels it.

test("walk-in booking for a new patient, visible on the schedule, then cancelled (E6-S4)", async ({ page }) => {
  await signIn(page, "receptionist");
  await openNav(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Book appointment" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Book an appointment" })).toBeVisible();

  await page.getByRole("combobox", { name: "Doctor" }).click();
  await page.getByRole("option").first().click();

  // Find the first day within two weeks that has a free slot.
  const dateInput = page.getByLabel("Day", { exact: true });
  const firstSlot = page.getByRole("radio").first();
  let found = false;
  for (let offset = 1; offset <= 14 && !found; offset += 1) {
    const day = new Date();
    day.setDate(day.getDate() + offset);
    await dateInput.fill(day.toLocaleDateString("en-CA"));
    await expect(page.getByText("No free times on this day").or(firstSlot)).toBeVisible();
    found = await firstSlot.isVisible();
  }
  expect(found, "a free slot within 14 days").toBe(true);
  const slotLabel = (await firstSlot.locator("..").textContent())?.trim() ?? "";
  await firstSlot.check({ force: true });

  const phone = uniquePhone();
  await page.getByLabel("Patient's phone number").fill(phone);
  await page.getByRole("button", { name: "Find patient" }).click();
  await page.getByLabel("Full name").fill("Playwright Walkin");
  await page.getByRole("button", { name: "Book appointment" }).click();
  await expect(page.getByText("Ask the patient for consent before saving their details")).toBeVisible();
  await page.getByRole("checkbox", { name: "The patient gave verbal consent" }).click();
  await page.getByRole("button", { name: "Book appointment" }).click();

  await expect(page.getByRole("heading", { name: "Appointment booked" })).toBeVisible();
  const reference = (await page.getByText(/^APT-\d+$/).textContent())?.trim() ?? "";
  expect(reference).toMatch(/^APT-\d{6,}$/);

  await page.getByRole("link", { name: "See the day's schedule" }).click();
  const row = page.getByRole("listitem").filter({ hasText: reference });
  await expect(row).toContainText("Playwright Walkin");
  await expect(row).toContainText("Front desk");
  await expect(row).toContainText(slotLabel);

  await row.getByRole("button", { name: /^Actions for / }).click();
  await page.getByRole("menuitem", { name: "Cancel appointment…" }).click();
  const dialog = page.getByRole("alertdialog");
  await dialog.getByRole("button", { name: "Cancel appointment" }).click();
  await expect(dialog.getByText("Give a short reason so the patient knows why")).toBeVisible();
  await dialog.getByLabel("Reason for the patient").fill("E2E test clean-up");
  await dialog.getByRole("button", { name: "Cancel appointment" }).click();
  await expect(row).toContainText("Cancelled");
});
