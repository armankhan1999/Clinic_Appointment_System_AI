import type { Page } from "@playwright/test";
import { z } from "zod";

import { addDays, mondayOf } from "../../lib/dates";

import { expect, test } from "./clean-browser";

import { clinicToday, signInAs } from "./support";

// REQUIRES THE RUNNING STACK. Read-only. The figures on screen are compared with the API response the page
// itself received, so a booking made by the live demo in the meantime cannot make the check flaky.

const metricsSchema = z.object({
  week_start: z.string(),
  bookings_by_source: z.object({ bot: z.number(), staff: z.number() }),
  cancellations: z.number(),
  per_doctor: z.array(
    z.object({ doctor_id: z.string(), name: z.string(), completed: z.number(), no_show: z.number(), no_show_rate: z.number() }),
  ),
});
type Metrics = z.infer<typeof metricsSchema>;

const count = new Intl.NumberFormat("en-IN");
const percent = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 1 });

function metricsResponse(page: Page, weekStart: string): Promise<Metrics> {
  return page
    .waitForResponse((r) => {
      const url = new URL(r.url());
      return url.pathname === "/api/v1/metrics/weekly" && url.searchParams.get("week_start") === weekStart && r.ok();
    })
    .then(async (r) => metricsSchema.parse(await r.json()));
}

async function expectFigures(page: Page, data: Metrics): Promise<void> {
  const tile = (label: string) =>
    page.locator("dl > div").filter({ has: page.locator("dt", { hasText: new RegExp(`^${label}$`) }) }).locator("dd");
  const { bot, staff } = data.bookings_by_source;
  await expect(tile("Booked through Telegram")).toHaveText(count.format(bot));
  await expect(tile("Booked at the front desk")).toHaveText(count.format(staff));
  await expect(tile("All bookings")).toHaveText(count.format(bot + staff));
  await expect(tile("Cancellations")).toHaveText(count.format(data.cancellations));

  const table = page.locator("section", { has: page.getByRole("heading", { name: "Attendance by doctor" }) }).getByRole("table");
  await expect(table.getByRole("row")).toHaveCount(1 + Math.max(1, data.per_doctor.length));
  for (const doctor of data.per_doctor) {
    // One name can start another ("Dr. Live Test", "Dr. Live Test Two"): match the whole first cell.
    const row = table.getByRole("row").filter({ has: page.getByRole("cell", { name: doctor.name, exact: true }) });
    const cells = row.getByRole("cell");
    await expect(cells).toHaveText([
      doctor.name,
      count.format(doctor.completed),
      count.format(doctor.no_show),
      percent.format(doctor.no_show_rate),
    ]);
  }
}

test("weekly numbers show the four figures and the per-doctor table, and move between weeks (E6-S6)", async ({ page }) => {
  await signInAs(page, "admin");
  const thisWeek = mondayOf(await clinicToday(page));

  const current = metricsResponse(page, thisWeek);
  await page.goto("/admin/metrics");
  await expect(page.getByRole("heading", { level: 1, name: "Weekly numbers" })).toBeVisible();
  await expect(page.getByLabel("Any day in the week")).toHaveValue(thisWeek);
  await expectFigures(page, await current);
  await expect(page.getByRole("button", { name: "This week" })).toHaveCount(0);

  const lastWeek = addDays(thisWeek, -7);
  const previous = metricsResponse(page, lastWeek);
  await page.getByRole("button", { name: "Previous week" }).click();
  await expect(page).toHaveURL(new RegExp(`/admin/metrics\\?week=${lastWeek}$`));
  await expect(page.getByLabel("Any day in the week")).toHaveValue(lastWeek);
  await expectFigures(page, await previous);

  await page.getByRole("button", { name: "This week" }).click();
  await expect(page).toHaveURL(/\/admin\/metrics$/);
  await expect(page.getByLabel("Any day in the week")).toHaveValue(thisWeek);

  const nextWeek = addDays(thisWeek, 7);
  const next = metricsResponse(page, nextWeek);
  await page.getByRole("button", { name: "Next week" }).click();
  await expect(page).toHaveURL(new RegExp(`\\?week=${nextWeek}$`));
  await expectFigures(page, await next);

  // Any day picks its week: a Thursday two weeks back shows that week's Monday.
  const twoWeeksBack = addDays(thisWeek, -14);
  const picked = metricsResponse(page, twoWeeksBack);
  await page.getByLabel("Any day in the week").fill(addDays(twoWeeksBack, 3));
  await expect(page).toHaveURL(new RegExp(`\\?week=${twoWeeksBack}$`));
  await expectFigures(page, await picked);
});
