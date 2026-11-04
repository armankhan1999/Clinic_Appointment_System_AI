import type { Page } from "@playwright/test";
import { z } from "zod";

import { addDays } from "../../lib/dates";

import { expect, test } from "./clean-browser";

import { api, cleanUp, clinicToday, createAppointments, openNav, signInAs, uniqueName, uniquePhone } from "./support";

// REQUIRES THE RUNNING STACK (dashboard + FastAPI + seeded dev database). Not runnable against mocks.
// Books real free slots for synthetic patients, cancels or deletes them, and deletes the patients afterwards.

const doctorList = z.object({ items: z.array(z.object({ id: z.string(), name: z.string(), specialty: z.string() })) });
const lookup = z.object({ items: z.array(z.object({ id: z.string() })) });
const daySchema = z.object({
  doctors: z.array(z.object({ appointments: z.array(z.object({ reference: z.string(), status: z.string(), source: z.string(), patient: z.object({ id: z.string() }) })) })),
});

/** Chooses the first active doctor in the Doctor list and returns it as the API lists it. */
async function chooseFirstDoctor(page: Page) {
  const doctors = doctorList.parse(await (await api(page, "GET", "/doctors?active=true")).json());
  const doctor = doctors.items[0];
  await page.getByRole("combobox", { name: "Doctor" }).click();
  await page.getByRole("option", { name: `${doctor.name}, ${doctor.specialty}` }).click();
  return doctor;
}

/** Picks the first free slot from tomorrow on (clinic time) and returns its label and start instant. */
async function pickFirstFreeSlot(page: Page): Promise<{ label: string; start: string; date: string }> {
  const today = await clinicToday(page);
  const dateInput = page.getByLabel("Day", { exact: true });
  const firstSlot = page.getByRole("radio").first();
  for (let offset = 1; offset <= 14; offset += 1) {
    const date = addDays(today, offset);
    await dateInput.fill(date);
    await expect(page.getByText("No free times on this day").or(firstSlot)).toBeVisible();
    if (await firstSlot.isVisible()) {
      const label = (await firstSlot.locator("..").textContent())?.trim() ?? "";
      const start = (await firstSlot.getAttribute("value")) ?? "";
      await firstSlot.check({ force: true });
      return { label, start, date };
    }
  }
  throw new Error("no free slot within 14 days");
}

async function patientIdByPhone(page: Page, phone: string): Promise<string | undefined> {
  const res = await api(page, "POST", "/patients/lookup", { phone });
  return res.ok() ? lookup.parse(await res.json()).items[0]?.id : undefined;
}

async function cancelFromSchedule(page: Page, reference: string): Promise<void> {
  const row = page.getByRole("listitem").filter({ hasText: reference });
  await row.getByRole("button", { name: /^Actions for / }).click();
  await page.getByRole("menuitem", { name: "Cancel appointment…" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Cancel this appointment?" });
  await dialog.getByRole("button", { name: "Cancel appointment" }).click();
  await expect(dialog.getByText("Give a short reason so the patient knows why")).toBeVisible();
  await dialog.getByLabel("Reason for the patient").fill("Playwright check: the patient called to cancel");
  await dialog.getByRole("button", { name: "Cancel appointment" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Appointment cancelled", { exact: true })).toBeVisible();
  await expect(row).toContainText("Cancelled");
}

test("walk-in booking for a new patient, visible on the schedule, then cancelled (E6-S4)", async ({ page }) => {
  const phone = uniquePhone();
  const name = uniqueName("Walkin");
  await signInAs(page, "receptionist");
  try {
    await openNav(page);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Book appointment" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Book an appointment" })).toBeVisible();

    await chooseFirstDoctor(page);
    const slot = await pickFirstFreeSlot(page);

    await page.getByLabel("Patient's phone number").fill(phone);
    await page.getByRole("button", { name: "Find patient" }).click();
    await page.getByLabel("Full name").fill(name);
    await page.getByRole("button", { name: "Book appointment" }).click();
    await expect(page.getByText("Ask the patient for consent before saving their details")).toBeVisible();
    await page.getByRole("checkbox", { name: "The patient gave verbal consent" }).click();
    await page.getByRole("button", { name: "Book appointment" }).click();

    await expect(page.getByRole("heading", { name: "Appointment booked" })).toBeVisible();
    const reference = (await page.getByText(/^APT-\d+$/).textContent())?.trim() ?? "";
    expect(reference).toMatch(/^APT-\d{6,}$/);

    await page.getByRole("link", { name: "See the day's schedule" }).click();
    const row = page.getByRole("listitem").filter({ hasText: reference });
    await expect(row).toContainText(name);
    await expect(row).toContainText("Front desk");
    await expect(row).toContainText(slot.label);

    await cancelFromSchedule(page, reference);
  } finally {
    const patientId = await patientIdByPhone(page, phone);
    if (patientId) await cleanUp({ patients: [patientId] });
  }
});

test("walk-in booking for an existing patient found by phone (E6-S4-AC1)", async ({ page }) => {
  const known = await createAppointments(["--count", "0", "--label", "Known"]);
  try {
    await signInAs(page, "receptionist", "/book");
    await expect(page.getByRole("heading", { level: 1, name: "Book an appointment" })).toBeVisible();
    const doctor = await chooseFirstDoctor(page);
    const slot = await pickFirstFreeSlot(page);

    await page.getByLabel("Patient's phone number").fill(known.patient.phone);
    await page.getByRole("button", { name: "Find patient" }).click();
    const match = page.getByRole("group", { name: "Patient with this number" });
    await expect(match.getByRole("radio", { name: new RegExp(known.patient.full_name) })).toBeChecked();
    await expect(page.getByLabel("Full name")).toHaveCount(0);
    await expect(page.getByText(`for ${known.patient.full_name}`)).toBeVisible();

    await page.getByRole("button", { name: "Book appointment" }).click();
    await expect(page.getByRole("heading", { name: "Appointment booked" })).toBeVisible();
    await expect(page.getByText(`${known.patient.full_name} with ${doctor.name}`)).toBeVisible();
    const reference = (await page.getByText(/^APT-\d+$/).textContent())?.trim() ?? "";

    const day = daySchema.parse(await (await api(page, "GET", `/schedule?date=${slot.date}`)).json());
    const booked = day.doctors.flatMap((d) => d.appointments).find((a) => a.reference === reference);
    expect(booked, "the booking is on the schedule").toMatchObject({ status: "booked", source: "staff", patient: { id: known.patient.id } });

    await page.getByRole("link", { name: "See the day's schedule" }).click();
    await expect(page.getByRole("listitem").filter({ hasText: reference })).toContainText(known.patient.full_name);
    await cancelFromSchedule(page, reference);
    const after = daySchema.parse(await (await api(page, "GET", `/schedule?date=${slot.date}`)).json());
    expect(after.doctors.flatMap((d) => d.appointments).find((a) => a.reference === reference)?.status).toBe("cancelled");
  } finally {
    await cleanUp({ patients: [known.patient.id] });
  }
});

test("a slot taken while the receptionist is booking is reported and the free times reload (E6-S4-AC2)", async ({ page }) => {
  const known = await createAppointments(["--count", "0", "--label", "Slow"]);
  const rivalPhone = uniquePhone();
  try {
    await signInAs(page, "receptionist", "/book");
    const doctor = await chooseFirstDoctor(page);
    const slot = await pickFirstFreeSlot(page);
    await page.getByLabel("Patient's phone number").fill(known.patient.phone);
    await page.getByRole("button", { name: "Find patient" }).click();
    await expect(page.getByRole("group", { name: "Patient with this number" }).getByRole("radio")).toBeChecked();

    // Someone else (the Telegram assistant, in real life) books that exact slot first.
    const rival = await api(page, "POST", "/appointments", {
      doctor_id: doctor.id,
      start: slot.start,
      patient: { full_name: uniqueName("Rival"), phone: rivalPhone, verbal_consent: true },
    });
    expect(rival.status(), "the competing booking").toBe(201);

    const attempt = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/v1/appointments" && r.request().method() === "POST");
    await page.getByRole("button", { name: "Book appointment" }).click();
    expect((await attempt).status()).toBe(409);
    const notice = page.getByRole("alert").filter({ hasText: "That time is no longer free" });
    await expect(notice).toContainText(`${slot.label} was just booked by someone else`);
    await expect(page.locator(`input[type="radio"][name="slot"][value="${slot.start}"]`)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Book appointment" })).toBeDisabled();
    await expect(page.getByText("Choose a time to continue.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Appointment booked" })).toHaveCount(0);
  } finally {
    const rivalId = await patientIdByPhone(page, rivalPhone);
    await cleanUp({ patients: [known.patient.id, ...(rivalId ? [rivalId] : [])] });
  }
});
