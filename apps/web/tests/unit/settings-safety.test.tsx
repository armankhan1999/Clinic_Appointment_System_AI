import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SettingsFormView } from "@/features/admin/settings/settings-form";
import { settingsFormSchema } from "@/lib/validation/forms";

import { jsonResponse, sessionBody, stubFetch, type StubbedCall } from "./helpers";
import { renderWithProviders } from "./render";

/* L3: two settings changes are dangerous enough to need a guard. */

const settings = {
  clinic_name: "Sunrise Clinic",
  phone: "+91 80 1234 5678",
  address: "12 MG Road",
  staff_hours_text: "Mon-Sat 9 AM-6 PM",
  timezone: "Asia/Kolkata",
  emergency_number: "112",
  emergency_phrases: ["chest pain"],
  cutoff_minutes: 120,
  booking_window_days: 30,
  max_upcoming_per_patient: 3,
  max_per_doctor_per_day: 1,
  morning_end: "12:00:00",
  afternoon_end: "17:00:00",
};

const formValues = {
  clinic_name: "Clinic",
  phone: "+91 1",
  address: "Road",
  staff_hours_text: "9-5",
  timezone: "Asia/Kolkata",
  emergency_number: "112",
  emergencyPhrasesText: "chest pain",
  cutoff_minutes: 120,
  booking_window_days: 30,
  max_upcoming_per_patient: 3,
  max_per_doctor_per_day: 1,
  morning_end: "12:00",
  afternoon_end: "17:00",
};

describe("emergency phrases are required", () => {
  it.each(["", "   \n \n"])("rejects an empty phrase list (%j) with a safety message", (text) => {
    const result = settingsFormSchema.safeParse({ ...formValues, emergencyPhrasesText: text });
    expect(result.success).toBe(false);
    const issue = result.error?.issues.find((i) => i.path[0] === "emergencyPhrasesText");
    expect(issue?.message).toMatch(/can't recognise emergencies/);
  });

  it("accepts one or more phrases", () => {
    expect(settingsFormSchema.safeParse(formValues).success).toBe(true);
  });
});

describe("changing the clinic time zone", () => {
  function stub() {
    return stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/settings" && call.method === "GET") return jsonResponse(200, settings);
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
      if (call.url === "/api/v1/settings" && call.method === "PATCH") {
        return jsonResponse(200, { ...settings, ...(call.body as object) });
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
  }

  it("asks for confirmation before saving, and saves only after it", async () => {
    const { calls } = stub();
    renderWithProviders(<SettingsFormView />);
    fireEvent.change(await screen.findByLabelText("Clinic time zone"), { target: { value: "Asia/Dubai" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Change the clinic time zone to Asia\/Dubai\?/)).toBeTruthy();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);

    fireEvent.click(within(dialog).getByRole("button", { name: "Change time zone" }));
    await screen.findByText("Clinic settings saved");
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ timezone: "Asia/Dubai" });
  });

  it("going back from the confirmation saves nothing", async () => {
    const { calls } = stub();
    renderWithProviders(<SettingsFormView />);
    fireEvent.change(await screen.findByLabelText("Clinic time zone"), { target: { value: "Asia/Dubai" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Keep Asia/Kolkata" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });
});
