import { z } from "zod";

import { expect, test } from "./clean-browser";

import { api, signInAs, uniqueLetters } from "./support";

// REQUIRES THE RUNNING STACK. Adds one clinic answer under a unique topic and deletes it; seed answers are untouched.

const faqPage = z.object({
  items: z.array(z.object({ id: z.string(), topic: z.string(), aliases: z.array(z.string()), answer: z.string() })),
});

test("admin adds, edits and deletes a clinic answer; a taken topic is refused on its field (IMP-02)", async ({ page }) => {
  const topic = `e2e_${uniqueLetters(10)}`;
  const findEntries = async () =>
    faqPage.parse(await (await api(page, "GET", "/faq?page=1&page_size=100")).json()).items.filter((e) => e.topic === topic);

  try {
    await signInAs(page, "admin", "/admin/faq");
    await expect(page.getByRole("heading", { level: 1, name: "Clinic answers" })).toBeVisible();

    await page.getByRole("button", { name: "Add answer" }).click();
    const add = page.getByRole("dialog", { name: "Add a clinic answer" });
    await add.getByLabel("Topic name").fill("Not A Slug");
    await add.getByLabel("Answer").fill("Playwright check answer, first version.");
    await add.getByRole("button", { name: "Add answer" }).click();
    await expect(add.getByText("Use 1–40 lowercase letters, numbers or underscores, e.g. parking_info")).toBeVisible();

    await add.getByLabel("Topic name").fill(topic);
    await add.getByLabel("Other ways patients ask (optional)").fill("playwright alias one, playwright alias two");
    await add.getByRole("button", { name: "Add answer" }).click();
    await expect(add).toBeHidden();
    await expect(page.getByText("Answer added", { exact: true })).toBeVisible();

    const entry = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: topic, exact: true }) });
    await expect(entry).toContainText("Also matches: playwright alias one, playwright alias two");
    await expect(entry).toContainText("Playwright check answer, first version.");
    expect(await findEntries()).toEqual([
      expect.objectContaining({ aliases: ["playwright alias one", "playwright alias two"], answer: "Playwright check answer, first version." }),
    ]);

    await entry.getByRole("button", { name: `Edit ${topic}` }).click();
    const edit = page.getByRole("dialog", { name: "Edit clinic answer" });
    await expect(edit.getByLabel("Topic name")).toHaveValue(topic);
    await edit.getByLabel("Answer").fill("Playwright check answer, second version.");
    await edit.getByRole("button", { name: "Save answer" }).click();
    await expect(edit).toBeHidden();
    await expect(page.getByText("Answer updated", { exact: true })).toBeVisible();
    await expect(entry).toContainText("Playwright check answer, second version.");

    await page.getByRole("button", { name: "Add answer" }).click();
    await add.getByLabel("Topic name").fill(topic);
    await add.getByLabel("Answer").fill("A second answer under the same topic.");
    await add.getByRole("button", { name: "Add answer" }).click();
    await expect(add.getByText("Another answer already uses this topic name. Choose a different one or edit that answer.")).toBeVisible();
    await expect(add.getByLabel("Topic name")).toHaveAttribute("aria-invalid", "true");
    await add.getByRole("button", { name: "Close without saving" }).click();
    await expect(add).toBeHidden();
    expect(await findEntries()).toEqual([expect.objectContaining({ answer: "Playwright check answer, second version." })]);

    await entry.getByRole("button", { name: `Delete ${topic}` }).click();
    const confirm = page.getByRole("alertdialog", { name: `Delete "${topic}"?` });
    await confirm.getByRole("button", { name: "Delete answer" }).click();
    await expect(confirm).toBeHidden();
    await expect(page.getByText("Answer deleted", { exact: true })).toBeVisible();
    await expect(entry).toHaveCount(0);
    expect(await findEntries()).toEqual([]);
  } finally {
    for (const leftover of await findEntries()) {
      expect((await api(page, "DELETE", `/faq/${leftover.id}`)).status(), "clean-up DELETE /faq").toBe(204);
    }
  }
});
