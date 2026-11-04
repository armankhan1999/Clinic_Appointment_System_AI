import { z } from "zod";

import { expect, test } from "./clean-browser";

import { api, cleanUp, createAttentionItems, signInAs } from "./support";

// REQUIRES THE RUNNING STACK. Tickets, emergency alerts and call flags come from the patient side, so a
// backend fixture creates them for one synthetic patient (apps/backend/tests/e2e_support/attention_fixture.py);
// the patient and everything attached to it is deleted afterwards.

const attentionSchema = z.object({
  tickets: z.array(z.object({ id: z.string() })),
  alerts: z.array(z.object({ id: z.string() })),
  flagged: z.array(z.object({ id: z.string() })),
});

test("the attention panel: acknowledge an emergency alert, resolve a ticket and clear a call flag (E6-S2-AC3, E5-S3-AC3, E5-S4-AC2, E4-S4-AC2)", async ({
  page,
}) => {
  const items = await createAttentionItems();
  try {
    await signInAs(page, "receptionist");
    const panel = page.getByRole("region", { name: /Needs attention/ });
    const mine = panel.getByRole("listitem").filter({ hasText: items.patient.full_name });
    await expect(mine).toHaveCount(3);

    const alert = mine.filter({ hasText: "Emergency message: contact the patient now" });
    await expect(alert).toContainText(items.patient.phone);
    await expect(alert).toContainText(/Received (just now|\d+ minutes? ago)/);
    await alert.getByRole("button", { name: "Acknowledge" }).click();
    const acknowledge = page.getByRole("alertdialog", { name: "Acknowledge this emergency alert?" });
    await expect(acknowledge).toContainText("Only acknowledge once someone has contacted the patient");
    await acknowledge.getByRole("button", { name: "Acknowledge" }).click();
    await expect(acknowledge).toBeHidden();
    await expect(page.getByText("Emergency alert acknowledged", { exact: true })).toBeVisible();
    await expect(alert).toHaveCount(0);

    const ticket = mine.filter({ hasText: "Patient asked to talk to a person" });
    await ticket.getByRole("button", { name: "Resolve" }).click();
    const resolve = page.getByRole("alertdialog", { name: "Mark this request as resolved?" });
    await resolve.getByRole("button", { name: "Resolve" }).click();
    await expect(resolve).toBeHidden();
    await expect(page.getByText("Request marked as resolved", { exact: true })).toBeVisible();
    await expect(ticket).toHaveCount(0);

    const flag = mine.filter({ hasText: `Call about ${items.appointment.time_label}` });
    await expect(flag).toContainText(`with ${items.doctor.name}`);
    await expect(flag).toContainText("Couldn't deliver the Telegram message to the patient");
    await flag.getByRole("button", { name: "Clear attention" }).click();
    const clear = page.getByRole("alertdialog", { name: "Clear the call flag?" });
    await clear.getByRole("button", { name: "Clear flag" }).click();
    await expect(clear).toBeHidden();
    await expect(page.getByText("Call flag cleared", { exact: true })).toBeVisible();
    await expect(mine).toHaveCount(0);

    const after = attentionSchema.parse(await (await api(page, "GET", "/attention")).json());
    expect(after.alerts.map((a) => a.id)).not.toContain(items.alert_id);
    expect(after.tickets.map((t) => t.id)).not.toContain(items.ticket_id);
    expect(after.flagged.map((f) => f.id)).not.toContain(items.appointment.id);
  } finally {
    await cleanUp({ patients: [items.patient.id] });
  }
});
