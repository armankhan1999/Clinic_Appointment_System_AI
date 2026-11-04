import type { Page } from "@playwright/test";

import { expect, test } from "./clean-browser";

import { api, signInAs } from "./support";

// REQUIRES THE RUNNING STACK (dashboard + FastAPI + seeded dev database). Not runnable against mocks.
// Edits one doctor's weekly hours and restores the original pattern afterwards.

type Block = { weekday: number; start: string; end: string; slot_minutes: number };

async function openFirstDoctorHours(page: Page): Promise<string> {
  await signInAs(page, "admin", "/admin/doctors");
  await page.getByRole("link", { name: "Hours and leave" }).first().click();
  await expect(page.getByRole("tab", { name: "Weekly hours" })).toBeVisible();
  return decodeURIComponent(new URL(page.url()).pathname.split("/").pop() ?? "");
}

test("admin edits a doctor's weekly hours with validation (E6-S3-AC1/AC2)", async ({ page }) => {
  const doctorId = await openFirstDoctorHours(page);
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

test("overlapping blocks and an out-of-range slot length are refused, and changes can be discarded (E6-S3-AC2)", async ({ page }) => {
  const doctorId = await openFirstDoctorHours(page);
  const before = (await (await api(page, "GET", `/doctors/${doctorId}/schedule`)).json()) as { blocks: Block[] };
  let writes = 0;
  page.on("request", (request) => {
    if (request.method() === "PUT" && new URL(request.url()).pathname.endsWith("/schedule")) writes += 1;
  });

  const sunday = page.getByRole("region", { name: "Sunday" });
  const addBlock = sunday.getByRole("button", { name: /Add hours on Sunday|Add another block/ });
  await addBlock.click();
  await addBlock.click();
  const starts = sunday.getByLabel("Starts");
  const ends = sunday.getByLabel("Ends");
  const count = await starts.count();
  await starts.nth(count - 2).fill("07:00");
  await ends.nth(count - 2).fill("08:00");
  await starts.nth(count - 1).fill("07:30");
  await ends.nth(count - 1).fill("08:30");
  await sunday.getByLabel("Slot length (minutes)").nth(count - 1).fill("150");
  await page.getByRole("button", { name: "Save weekly hours" }).click();

  await expect(sunday.getByText("Overlaps the 07:00–08:00 block")).toBeVisible();
  await expect(sunday.getByText("Slots can be at most 120 minutes")).toBeVisible();
  await expect(page.getByText("Fix the highlighted times before saving.")).toBeVisible();
  await expect(starts.nth(count - 1)).toHaveAttribute("aria-invalid", "true");
  expect(writes, "nothing is sent while the hours are invalid").toBe(0);

  await page.getByRole("button", { name: "Discard changes" }).click();
  await expect(page.getByText("All changes saved.")).toBeVisible();
  await expect(starts).toHaveCount(count - 2);
  const after = (await (await api(page, "GET", `/doctors/${doctorId}/schedule`)).json()) as { blocks: Block[] };
  expect(after.blocks).toEqual(before.blocks);
});
