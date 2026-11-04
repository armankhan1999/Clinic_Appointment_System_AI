import type { Page } from "@playwright/test";
import { z } from "zod";

import { expect, test } from "./clean-browser";

import { api, signInAs, uniqueLetters } from "./support";

// REQUIRES THE RUNNING STACK. Every test restores the settings it changed. The time-zone test switches to
// an alias with identical rules (Asia/Kolkata <-> Asia/Calcutta) so the live demo's times never move.

const settingsSchema = z.object({ staff_hours_text: z.string(), timezone: z.string(), emergency_phrases: z.array(z.string()) });
const SAME_RULES: Record<string, string> = { "Asia/Kolkata": "Asia/Calcutta", "Asia/Calcutta": "Asia/Kolkata" };

async function currentSettings(page: Page) {
  const res = await api(page, "GET", "/settings");
  expect(res.status(), "GET /settings").toBe(200);
  return settingsSchema.parse(await res.json());
}

async function restore(page: Page, changes: Partial<z.infer<typeof settingsSchema>>) {
  expect((await api(page, "PATCH", "/settings", changes)).status(), "restore the original settings").toBe(200);
}

function countSettingsWrites(page: Page): () => number {
  let writes = 0;
  page.on("request", (request) => {
    if (request.method() === "PATCH" && new URL(request.url()).pathname === "/api/v1/settings") writes += 1;
  });
  return () => writes;
}

test.describe("clinic settings (IMP-05)", () => {
  test.beforeEach(async ({ page }) => {
    await signInAs(page, "admin", "/admin/settings");
    await expect(page.getByRole("heading", { level: 1, name: "Clinic settings" })).toBeVisible();
  });

  test("a changed setting is saved and still shown after a reload", async ({ page }) => {
    const original = await currentSettings(page);
    const changed = `Monday to Saturday, 9 AM to 6 PM (Playwright ${uniqueLetters(5)})`;
    try {
      const field = page.getByLabel("Front desk hours");
      await expect(field).toHaveValue(original.staff_hours_text);
      await field.fill(changed);
      await expect(page.getByRole("button", { name: "Save settings" })).toBeEnabled();
      await page.getByRole("button", { name: "Save settings" }).click();
      await expect(page.getByText("Clinic settings saved", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Save settings" })).toBeDisabled();
      expect((await currentSettings(page)).staff_hours_text).toBe(changed);

      await page.reload();
      await expect(page.getByLabel("Front desk hours")).toHaveValue(changed);
    } finally {
      await restore(page, { staff_hours_text: original.staff_hours_text });
    }
    expect((await currentSettings(page)).staff_hours_text).toBe(original.staff_hours_text);
  });

  test("an empty emergency phrase list is refused before anything is sent", async ({ page }) => {
    const original = await currentSettings(page);
    expect(original.emergency_phrases.length, "the seed has emergency phrases").toBeGreaterThan(0);
    const writes = countSettingsWrites(page);

    const phrases = page.getByLabel("Emergency phrases");
    await expect(phrases).toHaveValue(original.emergency_phrases.join("\n"));
    await phrases.fill("   \n  ");
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText("Add at least one phrase. Without phrases the assistant can't recognise emergencies.")).toBeVisible();
    expect(writes(), "no PATCH /settings was sent").toBe(0);
    expect((await currentSettings(page)).emergency_phrases).toEqual(original.emergency_phrases);

    await page.getByRole("button", { name: "Discard changes" }).click();
    await expect(phrases).toHaveValue(original.emergency_phrases.join("\n"));
  });

  test("a time-zone change asks for confirmation before it is saved", async ({ page }) => {
    const original = await currentSettings(page);
    const alias = SAME_RULES[original.timezone];
    expect(alias, `a same-rules alias for ${original.timezone}`).toBeTruthy();
    const writes = countSettingsWrites(page);
    try {
      await page.getByLabel("Clinic time zone").fill(alias);
      await expect(page.getByText("Changing the time zone moves every slot and appointment label.")).toBeVisible();

      await page.getByRole("button", { name: "Save settings" }).click();
      const confirm = page.getByRole("alertdialog", { name: `Change the clinic time zone to ${alias}?` });
      await expect(confirm).toContainText("Only do this if the clinic's location really changed.");
      await confirm.getByRole("button", { name: `Keep ${original.timezone}` }).click();
      await expect(confirm).toBeHidden();
      expect(writes(), "keeping the time zone sends nothing").toBe(0);
      expect((await currentSettings(page)).timezone).toBe(original.timezone);

      await page.getByRole("button", { name: "Save settings" }).click();
      await confirm.getByRole("button", { name: "Change time zone" }).click();
      await expect(confirm).toBeHidden();
      await expect(page.getByText("Clinic settings saved", { exact: true })).toBeVisible();
      expect(writes()).toBe(1);
      expect((await currentSettings(page)).timezone).toBe(alias);
    } finally {
      await restore(page, { timezone: original.timezone });
    }
    expect((await currentSettings(page)).timezone).toBe(original.timezone);
  });
});
