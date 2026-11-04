import { expect, test } from "./clean-browser";

import { signIn } from "./support";

// REQUIRES THE RUNNING STACK. Live finding 2026-11-05: on a short window a tall dialog was cut off at the top and
// bottom with no way to scroll, so "Close without saving" and "Create account" could not be reached.
test.use({ viewport: { width: 1280, height: 500 } });

test("a tall dialog scrolls on a short screen so every button stays reachable", async ({ page }) => {
  await signIn(page, "admin");
  await page.goto("/admin/staff");
  await page.getByRole("button", { name: "Add staff account" }).first().click();
  const dialog = page.getByRole("dialog");

  await dialog.getByRole("button", { name: "Create account" }).click();
  await expect(dialog.getByText("Enter the person's name")).toBeVisible();

  const box = await dialog.boundingBox();
  expect(box, "dialog rendered").not.toBeNull();
  expect(box!.y, "dialog top inside the window").toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height, "dialog bottom inside the window").toBeLessThanOrEqual(500);

  await dialog.getByRole("button", { name: "Close without saving" }).click();
  await expect(dialog).toBeHidden();
});
