import type { Page } from "@playwright/test";
import { z } from "zod";

import { addDays } from "../../lib/dates";

import { expect, test } from "./clean-browser";

import { api, cleanUp, clinicToday, createAppointments, doctorDay, longDateInPage, signInAs } from "./support";

// REQUIRES THE RUNNING STACK. The leave goes on a seed doctor's day beyond the booking window, so no patient
// can book that day while the test runs; the only booking on it is the synthetic one the fixture writes.
// The leave and the synthetic patient are removed afterwards.

const doctorList = z.object({ items: z.array(z.object({ id: z.string(), name: z.string(), specialty: z.string() })) });
const leaveList = z.object({ items: z.array(z.object({ id: z.string(), date: z.string(), reason: z.string() })) });
const preview = z.object({ affected: z.array(z.object({ id: z.string() })) });
const settings = z.object({ booking_window_days: z.number() });
const daySchema = z.object({ doctors: z.array(z.object({ appointments: z.array(z.object({ id: z.string(), status: z.string() })) })) });

async function json<S extends z.ZodType>(page: Page, method: string, path: string, schema: S, body?: unknown): Promise<z.infer<S>> {
  const res = await api(page, method, path, body);
  expect(res.ok(), `${method} ${path}`).toBe(true);
  return schema.parse(await res.json());
}

/** A day past the booking window with no leave and no booking yet for this doctor. */
async function emptyDayBeyondWindow(page: Page, doctorId: string): Promise<string> {
  const today = await clinicToday(page);
  const { booking_window_days: window } = await json(page, "GET", "/settings", settings);
  const taken = new Set((await json(page, "GET", `/doctors/${doctorId}/leaves`, leaveList)).items.map((l) => l.date));
  for (let offset = window + 10; offset < window + 70; offset += 1) {
    const day = addDays(today, offset);
    if (taken.has(day)) continue;
    const { affected } = await json(page, "POST", `/doctors/${doctorId}/leaves/preview`, preview, { date: day });
    if (affected.length === 0) return day;
  }
  throw new Error("no empty day found beyond the booking window");
}

test("leave: the preview lists the affected booking, confirming cancels it, and the leave can be removed (E6-S3-AC3, E4-S4)", async ({
  page,
}) => {
  test.setTimeout(150_000);
  await signInAs(page, "admin");
  const doctor = (await json(page, "GET", "/doctors?active=true", doctorList)).items[0];
  const day = await emptyDayBeyondWindow(page, doctor.id);
  const booked = await createAppointments(["--day", day, "--time", "10:00", "--doctor-id", doctor.id, "--label", "Leave"]);
  const [appointment] = booked.appointments;
  const reason = "Playwright check: attending a conference";
  const leavesOnDay = async () => (await json(page, "GET", `/doctors/${doctor.id}/leaves`, leaveList)).items.filter((l) => l.date === day);

  try {
    await page.goto("/admin/doctors");
    await page.getByRole("row").filter({ hasText: doctor.name }).getByRole("link", { name: "Hours and leave" }).click();
    await expect(page.getByRole("heading", { level: 1, name: doctor.name })).toBeVisible();
    await page.getByRole("tab", { name: "Leave days" }).click();

    const form = page.getByRole("region", { name: "Add a leave day" });
    await form.getByLabel("Day off").fill(day);
    // The API refuses a leave without a reason, and affected patients are sent it, so the form asks first.
    await form.getByRole("button", { name: "Check bookings on this day" }).click();
    await expect(form.getByText("Give a reason. Patients whose appointments are cancelled are sent it.")).toBeVisible();
    await expect(form.getByRole("button", { name: /^Cancel \d+ appointments? and add leave$/ })).toHaveCount(0);

    await form.getByLabel(/^Reason/).fill(reason);
    await form.getByRole("button", { name: "Check bookings on this day" }).click();
    await expect(form).toContainText(`${doctor.name} off on ${await longDateInPage(page, day)}`);
    const warning = form.getByRole("alert").filter({ hasText: "1 booked appointment will be cancelled" });
    await expect(warning.getByRole("listitem")).toHaveCount(1);
    await expect(warning).toContainText(booked.patient.full_name);
    await expect(warning).toContainText(appointment.reference);
    await expect(warning).toContainText(appointment.time_label);

    const confirm = form.getByRole("button", { name: "Cancel 1 appointment and add leave" });
    await expect(confirm).toBeDisabled();
    await form.getByRole("checkbox", { name: "I understand this appointment will be cancelled" }).click();
    await confirm.click();
    await expect(page.getByText("Leave added", { exact: true })).toBeVisible();
    await expect(page.getByText(/1 appointment cancelled\. Patients on Telegram get a notice\./)).toBeVisible();

    const longDay = await longDateInPage(page, day);
    const listed = page.getByRole("region", { name: "Upcoming leave" }).getByRole("listitem").filter({ hasText: longDay });
    await expect(listed).toContainText(reason);
    expect(await leavesOnDay()).toEqual([expect.objectContaining({ reason })]);
    const schedule = await json(page, "GET", `/schedule?date=${day}`, daySchema);
    expect(schedule.doctors.flatMap((d) => d.appointments).find((a) => a.id === appointment.id)?.status).toBe("cancelled");

    // The doctor's day on the schedule shows the cancelled booking (Doctor persona, E4-S4).
    await page.goto(`/?date=${day}`);
    await expect(doctorDay(page, doctor).getByRole("listitem").filter({ hasText: appointment.reference })).toContainText("Cancelled");

    await page.goBack();
    await page.getByRole("tab", { name: "Leave days" }).click();
    await page.getByRole("button", { name: `Remove leave on ${longDay}` }).click();
    const remove = page.getByRole("alertdialog", { name: "Remove this leave day?" });
    await expect(remove).toContainText("Appointments already cancelled for this leave stay cancelled.");
    await remove.getByRole("button", { name: "Remove leave" }).click();
    await expect(remove).toBeHidden();
    await expect(page.getByText("Leave removed", { exact: true })).toBeVisible();
    await expect(listed).toHaveCount(0);
    expect(await leavesOnDay()).toEqual([]);
  } finally {
    for (const leftover of await leavesOnDay()) {
      expect((await api(page, "DELETE", `/doctors/${doctor.id}/leaves/${leftover.id}`)).status(), "clean-up DELETE leave").toBe(204);
    }
    await cleanUp({ patients: [booked.patient.id] });
  }
});
