import type { Locator, Page } from "@playwright/test";
import { z } from "zod";

import { addDays } from "../../lib/dates";

import { expect, test } from "./clean-browser";

import { api, cleanUp, createAppointments, doctorDay, signInAs, type FixtureAppointment } from "./support";

// REQUIRES THE RUNNING STACK. POST /appointments refuses past slots, so the appointments come from a backend
// fixture (apps/backend/tests/e2e_support/appointment_fixture.py) and are deleted afterwards.

const daySchema = z.object({
  doctors: z.array(
    z.object({
      doctor_id: z.string(),
      name: z.string(),
      specialty: z.string(),
      appointments: z.array(z.object({ id: z.string(), reference: z.string(), status: z.string() })),
    }),
  ),
});
type Doctor = { name: string; specialty: string };

// "Booked" is not checked as text: every row's source pill also reads "Booked via …" to screen readers.
const FINAL_LABELS: Record<string, string> = { completed: "Completed", no_show: "No-show", cancelled: "Cancelled" };

async function expectStatus(row: Locator, status: string): Promise<void> {
  for (const [value, label] of Object.entries(FINAL_LABELS)) {
    if (value === status) await expect(row).toContainText(label);
    else await expect(row).not.toContainText(label);
  }
}

async function daySchedule(page: Page, date: string) {
  const res = await api(page, "GET", `/schedule?date=${date}`);
  expect(res.status(), `GET /schedule?date=${date}`).toBe(200);
  return daySchema.parse(await res.json());
}

function appointmentRow(page: Page, doctor: Doctor | undefined, appointment: FixtureAppointment) {
  if (!doctor) throw new Error("the appointment fixture did not name the doctor");
  return doctorDay(page, doctor).getByRole("listitem").filter({ hasText: appointment.reference });
}

test("receptionist marks started appointments completed or no-show; not-yet-started ones cannot be marked (E6-S5, E6-S2-AC1)", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const past = await createAppointments(["--minutes-from-now", "-120", "--count", "2", "--label", "Attendance"]);
  const upcoming = await createAppointments(["--minutes-from-now", String(3 * 24 * 60), "--label", "Upcoming"]);
  try {
    const doctor = past.doctor;
    const upcomingDoctor = upcoming.doctor;
    const [toComplete, toMiss] = past.appointments;
    const [notStarted] = upcoming.appointments;

    await signInAs(page, "receptionist", `/?date=${toComplete.date}`);
    const completeRow = appointmentRow(page, doctor, toComplete);
    await expect(completeRow).toContainText(past.patient.full_name);
    await expect(completeRow).toContainText(toComplete.time_label);
    await expectStatus(completeRow, "booked");

    await completeRow.getByRole("button", { name: `Actions for ${past.patient.full_name} at ${toComplete.time_label}` }).click();
    await expect(page.getByRole("menuitem", { name: "Mark completed" })).toBeEnabled();
    await page.getByRole("menuitem", { name: "Mark completed" }).click();
    const markCompleted = page.getByRole("alertdialog", { name: "Mark as completed?" });
    await expect(markCompleted).toContainText("Only a clinic admin can change this afterwards.");
    await markCompleted.getByRole("button", { name: "Mark completed" }).click();
    await expect(markCompleted).toBeHidden();
    await expect(page.getByText("Marked as completed", { exact: true })).toBeVisible();
    await expectStatus(completeRow, "completed");
    await expect(completeRow.getByRole("button", { name: /^Actions for / })).toHaveCount(0);

    const missRow = appointmentRow(page, doctor, toMiss);
    await missRow.getByRole("button", { name: `Actions for ${past.patient.full_name} at ${toMiss.time_label}` }).click();
    await page.getByRole("menuitem", { name: "Mark no-show" }).click();
    const markMissed = page.getByRole("alertdialog", { name: "Mark as no-show?" });
    await markMissed.getByRole("button", { name: "Mark no-show" }).click();
    await expect(markMissed).toBeHidden();
    await expect(page.getByText("Marked as no-show", { exact: true })).toBeVisible();
    await expectStatus(missRow, "no_show");

    // Each doctor's day lists exactly that doctor's appointments with their statuses (E6-S2-AC1/AC2).
    const day = await daySchedule(page, toComplete.date);
    const statuses = new Map(day.doctors.flatMap((d) => d.appointments.map((a) => [a.id, a.status] as const)));
    expect(statuses.get(toComplete.id)).toBe("completed");
    expect(statuses.get(toMiss.id)).toBe("no_show");
    for (const entry of day.doctors) {
      const rows = doctorDay(page, entry).getByRole("listitem");
      await expect(rows).toHaveCount(entry.appointments.length);
      for (const appointment of entry.appointments) {
        await expectStatus(rows.filter({ hasText: appointment.reference }), appointment.status);
      }
    }

    // Not started yet: both marks are disabled and the menu says why (E6-S5-AC2).
    await page.getByLabel("Day to show").fill(notStarted.date);
    await expect(page).toHaveURL(new RegExp(`\\?date=${notStarted.date}$`));
    const notStartedRow = appointmentRow(page, upcomingDoctor, notStarted);
    await notStartedRow.getByRole("button", { name: `Actions for ${upcoming.patient.full_name} at ${notStarted.time_label}` }).click();
    await expect(page.getByText("Completed and no-show can be marked once the appointment time has started.")).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Mark completed" })).toBeDisabled();
    await expect(page.getByRole("menuitem", { name: "Mark no-show" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Previous day" }).click();
    await expect(page).toHaveURL(new RegExp(`\\?date=${addDays(notStarted.date, -1)}$`));

    // Only an admin may change a mark afterwards (GAP-22).
    await signInAs(page, "admin", `/?date=${toMiss.date}`);
    await missRow.getByRole("button", { name: `Actions for ${past.patient.full_name} at ${toMiss.time_label}` }).click();
    await page.getByRole("menuitem", { name: "Change to completed" }).click();
    const change = page.getByRole("alertdialog", { name: "Mark as completed?" });
    await expect(change).toContainText("You can change this later.");
    await change.getByRole("button", { name: "Mark completed" }).click();
    await expect(change).toBeHidden();
    await expectStatus(missRow, "completed");
    expect((await daySchedule(page, toMiss.date)).doctors.flatMap((d) => d.appointments).find((a) => a.id === toMiss.id)?.status).toBe(
      "completed",
    );
  } finally {
    await cleanUp({ patients: [past.patient.id, upcoming.patient.id] });
  }
});
