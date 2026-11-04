import { expect, test } from "./clean-browser";

import { addReceptionistInUi, staffAccount } from "./staff-helpers";
import { cleanUp, signInAs, submitLogin, uniqueLetters, uniqueName } from "./support";

// REQUIRES THE RUNNING STACK. Uses a throwaway receptionist created here, never e2e_desk or e2e_admin,
// and deletes it afterwards. Sign-in attempts are paced to stay within the API's per-address rate limit.

test("five wrong passwords lock an account; an admin unlocks it and the user signs in (E6-S1-AC3, IMP-04)", async ({ page }) => {
  test.setTimeout(240_000);
  const staff = {
    displayName: uniqueName("Lockout"),
    username: `e2e_tmp_lock_${uniqueLetters(8)}`,
    password: `lockout-${uniqueLetters(16)}`,
  };

  try {
    await signInAs(page, "admin", "/admin/staff");
    await addReceptionistInUi(page, staff);

    await page.context().clearCookies();
    await page.goto("/login");
    for (let attempt = 1; attempt <= 5; attempt += 1) {
      expect(await submitLogin(page, staff.username, `wrong-${attempt}-${uniqueLetters(10)}`), `wrong password ${attempt}`).toBe(401);
      await expect(page.getByText("Username or password is incorrect")).toBeVisible();
      await expect(page.getByText("After 5 wrong tries the account is locked for 15 minutes.")).toBeVisible();
    }
    await expect(page.getByLabel("Username")).toHaveValue(staff.username);
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");

    // Even the right password is refused while the lock lasts.
    expect(await submitLogin(page, staff.username, staff.password)).toBe(423);
    await expect(page.getByText("This account is locked")).toBeVisible();
    await expect(page.getByText(/Try again in about 1[45] minutes, or ask a clinic admin to unlock it\./)).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);

    await signInAs(page, "admin", "/admin/staff");
    expect((await staffAccount(page, staff.username))?.locked_until, "locked_until in the database").toBeTruthy();
    const row = page.getByRole("row").filter({ hasText: staff.username });
    await expect(row).toContainText("Locked");
    await expect(row).toContainText("Too many wrong passwords; unlocks by itself in about");
    await row.getByRole("button", { name: `Unlock ${staff.displayName}` }).click();
    const dialog = page.getByRole("alertdialog", { name: `Unlock ${staff.displayName}?` });
    await dialog.getByRole("button", { name: "Unlock account" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Account unlocked")).toBeVisible();
    await expect(row).toContainText("Active");
    await expect(row).not.toContainText("Locked");
    expect((await staffAccount(page, staff.username))?.locked_until ?? null).toBeNull();

    await page.context().clearCookies();
    await page.goto("/login");
    expect(await submitLogin(page, staff.username, staff.password)).toBe(200);
    await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
  } finally {
    await cleanUp({ staff: [staff.username] });
  }
});
