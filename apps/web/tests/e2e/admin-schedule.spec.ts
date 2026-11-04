import { expect, test } from "./clean-browser";

import { api, signIn } from "./support";

// REQUIRES THE RUNNING STACK (dashboard + FastAPI + seeded dev database). Not runnable against mocks.
// Edits one doctor's weekly hours and restores the original pattern afterwards.

type Block = { weekday: number; start: string; end: string; slot_minutes: number };

test("admin edits a doctor's weekly hours with validation (E6-S3-AC1/AC2)", async ({ page }) => {
  await signIn(page, "admin");
  await page.goto("/admin/doctors");
  await page.getByRole("link", { name: "Hours and leave" }).first().click();
  await expect(page.getByRole("tab", { name: "Weekly hours" })).toBeVisible();

  const doctorId = decodeURIComponent(new URL(page.url()).pathname.split("/").pop() ?? "");
  const original = (await (await api(page, "GET", `/doctors/${doctorId}/schedule`)).json()) as { blocks: Block[] };

  try {
    const sunday = page.getByRole("region", { name: "Sunday" });
    await sunday.getByRole("button", { name: /Add hours on Sunday|Add another block/ }).click();
    const lastStart = sunday.getByLabel("Starts").last();
    const lastEnd = sunday.getByLabel("Ends").last();

    await lastStart.fill("11:00");
    await lastEnd.fill("10:00");
    await page.getByRole("button", { name: "Save weekly hours" }).click();
    await expect(sunday.getByText("End time must be after the start time")).toBeVisible();

    await lastStart.fill("06:00");
    await lastEnd.fill("06:30");
    await sunday.getByLabel("Slot length (minutes)").last().fill("15");
    await page.getByRole("button", { name: "Save weekly hours" }).click();
    await expect(page.getByText("Weekly hours saved")).toBeVisible();

    const saved = (await (await api(page, "GET", `/doctors/${doctorId}/schedule`)).json()) as { blocks: Block[] };
    expect(saved.blocks).toContainEqual(expect.objectContaining({ weekday: 6, start: expect.stringMatching(/^06:00/), slot_minutes: 15 }));
  } finally {
    const restore = await api(page, "PUT", `/doctors/${doctorId}/schedule`, { blocks: original.blocks });
    expect(restore.status(), "restore original weekly hours").toBe(200);
  }
});
