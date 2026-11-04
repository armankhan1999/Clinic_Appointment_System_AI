import type { Page } from "@playwright/test";
import { z } from "zod";

import { addDays } from "../../lib/dates";

import { expect, test } from "./clean-browser";

import { clinicToday, signInAs } from "./support";

// REQUIRES THE RUNNING STACK. Read-only.

const PAGE_SIZE = 50;
const auditPage = z.object({
  items: z.array(z.object({ id: z.number(), ts: z.string(), action: z.string(), actor_type: z.string() })),
  page: z.number(),
  total: z.number(),
});

function nextAuditPage(page: Page, expected: (url: URL) => boolean) {
  return page
    .waitForResponse((r) => {
      const url = new URL(r.url());
      return url.pathname === "/api/v1/audit" && r.ok() && expected(url);
    })
    .then(async (r) => auditPage.parse(await r.json()));
}

const rows = (page: Page) => page.locator("main table tbody tr");

test("the activity log pages through entries and filters by action, actor and date (IMP-03)", async ({ page }) => {
  await signInAs(page, "admin");
  const today = await clinicToday(page);

  const first = nextAuditPage(page, (url) => !url.searchParams.has("action") && url.searchParams.get("page") === "1");
  await page.goto("/admin/audit");
  await expect(page.getByRole("heading", { level: 1, name: "Activity log" })).toBeVisible();
  const page1 = await first;
  const pages = Math.ceil(page1.total / PAGE_SIZE);
  expect(pages, "enough activity in the dev database to page through").toBeGreaterThan(1);
  const status = page.getByRole("navigation", { name: "Activity log pages" });
  await expect(status).toContainText(`Page 1 of ${pages}, ${page1.total} entries`);
  await expect(rows(page)).toHaveCount(PAGE_SIZE);
  await expect(page.getByRole("button", { name: "Newer" })).toBeDisabled();

  const second = nextAuditPage(page, (url) => url.searchParams.get("page") === "2");
  await page.getByRole("button", { name: "Older" }).click();
  await expect(page).toHaveURL(/\/admin\/audit\?page=2$/);
  const page2 = await second;
  await expect(status).toContainText(`Page 2 of ${Math.ceil(page2.total / PAGE_SIZE)}`);
  const oldestOnPage1 = page1.items[page1.items.length - 1];
  expect(page2.items[0].ts <= oldestOnPage1.ts, "page 2 continues with older entries").toBe(true);
  await expect(rows(page).first().locator("time")).toHaveAttribute("datetime", page2.items[0].ts);

  await page.getByRole("button", { name: "Newer" }).click();
  await expect(page).toHaveURL(/\/admin\/audit$/);
  await expect(status).toContainText("Page 1 of");

  // Every sign-in by these specs today is audited as staff.login.
  const filters = page.getByRole("form", { name: "Filter the activity log" });
  await filters.getByLabel("From", { exact: true }).fill(today);
  await filters.getByLabel("To", { exact: true }).fill(today);
  await filters.getByLabel("Action", { exact: true }).fill("staff.login");
  await filters.getByRole("combobox", { name: "Done by" }).click();
  await page.getByRole("option", { name: "Staff", exact: true }).click();
  const filtered = nextAuditPage(page, (url) => url.searchParams.get("action") === "staff.login");
  await filters.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(new RegExp(`\\?from=${today}&to=${today}&actor_type=staff&action=staff\\.login$`));
  const logins = await filtered;
  expect(logins.total, "today's sign-ins are in the log").toBeGreaterThan(0);
  expect(new Set(logins.items.map((e) => e.action))).toEqual(new Set(["staff.login"]));
  expect(new Set(logins.items.map((e) => e.actor_type))).toEqual(new Set(["staff"]));
  await expect(status).toContainText(`${logins.total} entries`);
  await expect(rows(page)).toHaveCount(Math.min(PAGE_SIZE, logins.total));
  for (const action of await rows(page).locator("td:nth-child(3)").allTextContents()) expect(action).toBe("staff.login");

  await filters.getByLabel("To", { exact: true }).fill(addDays(today, -1));
  await filters.getByRole("button", { name: "Apply filters" }).click();
  await expect(filters.getByText("The end date must be on or after the start date")).toBeVisible();

  await filters.getByLabel("To", { exact: true }).fill(today);
  await filters.getByLabel("Action", { exact: true }).fill("e2e.nothing_matches_this");
  await filters.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByText("Nothing matches these filters")).toBeVisible();

  await filters.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).toHaveURL(/\/admin\/audit$/);
  await expect(filters.getByLabel("Action", { exact: true })).toHaveValue("");
  await expect(status).toContainText(`Page 1 of`);
});
