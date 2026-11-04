import { expect, type Page } from "@playwright/test";
import { z } from "zod";

import { api } from "./support";

export type NewStaff = { displayName: string; username: string; password: string };

const staffPage = z.object({
  items: z.array(
    z.object({
      id: z.string(),
      username: z.string(),
      display_name: z.string(),
      role: z.string(),
      active: z.boolean(),
      locked_until: z.string().nullable(),
    }),
  ),
});

/** Creates a receptionist through Staff accounts > Add staff account. The page must show /admin/staff. */
export async function addReceptionistInUi(page: Page, staff: NewStaff): Promise<void> {
  await page.getByRole("button", { name: "Add staff account" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a staff account" });
  await dialog.getByLabel("Name", { exact: true }).fill(staff.displayName);
  await dialog.getByLabel("Username", { exact: true }).fill(staff.username);
  await dialog.getByLabel("Password", { exact: true }).fill(staff.password);
  await dialog.getByLabel("Type the password again").fill(staff.password);
  await dialog.getByRole("button", { name: "Create account" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(`${staff.displayName} can sign in as "${staff.username}".`)).toBeVisible();
}

/** The account as the API reports it (admin session), for checking what the UI changed. */
export async function staffAccount(page: Page, username: string) {
  const res = await api(page, "GET", "/staff-users?page=1&page_size=100");
  expect(res.status(), "GET /staff-users").toBe(200);
  return staffPage.parse(await res.json()).items.find((user) => user.username === username);
}
