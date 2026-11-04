import { z } from "zod";

import { expect, test } from "./clean-browser";

import { api, cleanUp, signInAs, uniqueName } from "./support";

// REQUIRES THE RUNNING STACK. Adds one uniquely named doctor and deletes it afterwards; seed doctors are untouched.

const doctorList = z.object({
  items: z.array(z.object({ id: z.string(), name: z.string(), specialty: z.string(), active: z.boolean() })),
});

test("admin adds a doctor, edits the specialty and deactivates them (IMP-01)", async ({ page }) => {
  const name = uniqueName("Doctor");
  const findDoctor = async (filter = "") =>
    doctorList.parse(await (await api(page, "GET", `/doctors${filter}`)).json()).items.find((d) => d.name === name);

  try {
    await signInAs(page, "admin", "/admin/doctors");
    await expect(page.getByRole("heading", { level: 1, name: "Doctors and hours" })).toBeVisible();

    await page.getByRole("button", { name: "Add doctor" }).click();
    const add = page.getByRole("dialog", { name: "Add a doctor" });
    await add.getByRole("button", { name: "Add doctor" }).click();
    await expect(add.getByText("Enter the name (at least 2 characters)")).toBeVisible();
    await expect(add.getByText("Enter the specialty (at least 2 characters)")).toBeVisible();
    await add.getByLabel("Name").fill(name);
    await add.getByLabel("Specialty").fill("General Physician");
    await add.getByRole("button", { name: "Add doctor" }).click();
    await expect(add).toBeHidden();
    await expect(page.getByText("Doctor added", { exact: true })).toBeVisible();

    const row = page.getByRole("row").filter({ hasText: name });
    await expect(row).toContainText("General Physician");
    await expect(row).toContainText("Active");
    expect(await findDoctor()).toMatchObject({ specialty: "General Physician", active: true });

    await row.getByRole("button", { name: `Edit ${name}` }).click();
    const edit = page.getByRole("dialog", { name: "Edit doctor" });
    await expect(edit.getByLabel("Name")).toHaveValue(name);
    await expect(edit.getByLabel("Specialty")).toHaveValue("General Physician");
    await edit.getByLabel("Specialty").fill("Dermatologist");
    await edit.getByRole("button", { name: "Save changes" }).click();
    await expect(edit).toBeHidden();
    await expect(page.getByText("Doctor updated", { exact: true })).toBeVisible();
    await expect(row).toContainText("Dermatologist");

    await row.getByRole("button", { name: "Deactivate" }).click();
    const confirm = page.getByRole("alertdialog", { name: `Deactivate ${name}?` });
    await expect(confirm).toContainText("Patients can no longer book this doctor");
    await confirm.getByRole("button", { name: "Deactivate" }).click();
    await expect(confirm).toBeHidden();
    await expect(page.getByText("Doctor deactivated", { exact: true })).toBeVisible();
    await expect(row).toContainText("Inactive");
    await expect(row.getByRole("button", { name: "Reactivate" })).toBeVisible();

    expect(await findDoctor()).toMatchObject({ specialty: "Dermatologist", active: false });
    expect(await findDoctor("?active=true"), "an inactive doctor is not offered for booking").toBeUndefined();
  } finally {
    const created = await findDoctor();
    if (created) await cleanUp({ doctors: [created.id] });
  }
});
