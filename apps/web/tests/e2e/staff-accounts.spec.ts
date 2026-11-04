import { expect, test } from "./clean-browser";

import { staffAccount } from "./staff-helpers";
import { cleanUp, signInAs, submitLogin, uniqueLetters, uniqueName } from "./support";

// REQUIRES THE RUNNING STACK. Creates one throwaway receptionist and deletes it afterwards.

test("admin creates a staff account, a weak password is refused, the password is reset and the account deactivated (IMP-04)", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const displayName = uniqueName("Staff");
  const username = `e2e_tmp_staff_${uniqueLetters(8)}`;
  const firstPassword = `first-${uniqueLetters(16)}`;
  const newPassword = `second-${uniqueLetters(16)}`;

  try {
    await signInAs(page, "admin", "/admin/staff");
    await expect(page.getByRole("heading", { level: 1, name: "Staff accounts" })).toBeVisible();

    await page.getByRole("button", { name: "Add staff account" }).click();
    const create = page.getByRole("dialog", { name: "Add a staff account" });
    await create.getByLabel("Name", { exact: true }).fill(displayName);
    await create.getByLabel("Username", { exact: true }).fill(username);
    await create.getByLabel("Password", { exact: true }).fill("short-pass");
    await create.getByLabel("Type the password again").fill("short-pass");
    await create.getByRole("button", { name: "Create account" }).click();
    await expect(create.getByText("Use at least 12 characters")).toBeVisible();
    await expect(create.getByLabel("Password", { exact: true })).toHaveAttribute("aria-invalid", "true");

    await create.getByLabel("Password", { exact: true }).fill(firstPassword);
    await create.getByLabel("Type the password again").fill(`${firstPassword}x`);
    await create.getByRole("button", { name: "Create account" }).click();
    await expect(create.getByText("The two passwords don't match")).toBeVisible();
    expect(await staffAccount(page, username), "nothing saved while the form is invalid").toBeUndefined();

    await create.getByLabel("Type the password again").fill(firstPassword);
    await create.getByRole("button", { name: "Create account" }).click();
    await expect(create).toBeHidden();
    await expect(page.getByText(`${displayName} can sign in as "${username}".`)).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: username });
    await expect(row).toContainText(displayName);
    await expect(row).toContainText("Receptionist");
    await expect(row).toContainText("Active");
    expect(await staffAccount(page, username)).toMatchObject({ display_name: displayName, role: "receptionist", active: true });

    await row.getByRole("button", { name: `Reset password for ${displayName}` }).click();
    const reset = page.getByRole("dialog", { name: `Reset password for ${displayName}` });
    await expect(reset).toContainText("signed out on every computer");
    await reset.getByLabel("New password", { exact: true }).fill("too-short");
    await reset.getByLabel("Type the new password again").fill("too-short");
    await reset.getByRole("button", { name: "Reset password" }).click();
    await expect(reset.getByText("Use at least 12 characters")).toBeVisible();
    await reset.getByLabel("New password", { exact: true }).fill(newPassword);
    await reset.getByLabel("Type the new password again").fill(newPassword);
    await reset.getByRole("button", { name: "Reset password" }).click();
    await expect(reset).toBeHidden();
    await expect(page.getByText("Password reset", { exact: true })).toBeVisible();

    await page.context().clearCookies();
    await page.goto("/login");
    expect(await submitLogin(page, username, firstPassword), "the old password no longer works").toBe(401);
    expect(await submitLogin(page, username, newPassword), "the new password works").toBe(200);
    await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();

    await signInAs(page, "admin", "/admin/staff");
    const sameRow = page.getByRole("row").filter({ hasText: username });
    await sameRow.getByRole("button", { name: "Deactivate" }).click();
    const confirm = page.getByRole("alertdialog", { name: `Deactivate ${displayName}?` });
    await expect(confirm).toContainText("They can no longer sign in.");
    await confirm.getByRole("button", { name: "Deactivate" }).click();
    await expect(confirm).toBeHidden();
    await expect(page.getByText("Account deactivated")).toBeVisible();
    await expect(sameRow).toContainText("Deactivated");
    await expect(sameRow.getByRole("button", { name: "Reactivate" })).toBeVisible();
    expect((await staffAccount(page, username))?.active).toBe(false);

    await page.context().clearCookies();
    await page.goto("/login");
    expect(await submitLogin(page, username, newPassword), "a deactivated account cannot sign in").toBe(401);
    await expect(page.getByText("Username or password is incorrect")).toBeVisible();
  } finally {
    await cleanUp({ staff: [username] });
  }
});
