import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FaqEditor } from "@/features/admin/faq/faq-editor";
import { SettingsFormView } from "@/features/admin/settings/settings-form";
import { StaffAccounts, lockMinutesLeft } from "@/features/admin/staff/staff-accounts";

import { errorEnvelope, jsonResponse, sessionBody, stubFetch, type StubbedCall } from "./helpers";
import { renderWithProviders } from "./render";

const page = <T,>(items: T[]) => ({ items, page: 1, page_size: 100, total: items.length });

describe("staff accounts use locked_until", () => {
  it("computes the minutes left only for a future lockout", () => {
    const now = new Date("2030-01-09T04:00:00Z");
    const base = { id: "u", username: "u", display_name: "U", role: "receptionist" as const, active: true };
    expect(lockMinutesLeft({ ...base, locked_until: "2030-01-09T04:09:10Z" }, now)).toBe(10);
    expect(lockMinutesLeft({ ...base, locked_until: "2030-01-09T03:59:00Z" }, now)).toBeNull();
    expect(lockMinutesLeft({ ...base, locked_until: null }, now)).toBeNull();
  });

  it("marks locked accounts and offers Unlock only for them", async () => {
    const future = new Date(Date.now() + 10 * 60_000).toISOString();
    stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
      if (call.url.startsWith("/api/v1/staff-users")) {
        return jsonResponse(
          200,
          page([
            { id: "u-1", username: "asha", display_name: "Asha", role: "receptionist", active: true, locked_until: future },
            { id: "u-2", username: "ravi", display_name: "Ravi", role: "receptionist", active: true, locked_until: null },
          ]),
        );
      }
      throw new Error(`unexpected ${call.url}`);
    });
    renderWithProviders(<StaffAccounts />);

    const ashaRow = (await screen.findByText("Asha")).closest("tr");
    const raviRow = screen.getByText("Ravi").closest("tr");
    if (!ashaRow || !raviRow) throw new Error("rows not rendered");
    expect(ashaRow.textContent).toContain("Locked");
    expect(within(ashaRow).getByRole("button", { name: "Unlock Asha" })).toBeTruthy();
    expect(raviRow.textContent).toContain("Active");
    expect(within(raviRow).queryByRole("button", { name: /Unlock/ })).toBeNull();
  });
});

describe("staff password reset", () => {
  it("lets an admin set a new password for someone else, never for their own row", async () => {
    const { calls } = stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
      if (call.url === "/api/v1/staff-users/u-2" && call.method === "PATCH") {
        return jsonResponse(200, { id: "u-2", username: "ravi", display_name: "Ravi", role: "receptionist", active: true, locked_until: null });
      }
      if (call.url.startsWith("/api/v1/staff-users")) {
        return jsonResponse(
          200,
          page([
            { id: "u-1", username: "desk1", display_name: "Asha Desk", role: "admin", active: true, locked_until: null },
            { id: "u-2", username: "ravi", display_name: "Ravi", role: "receptionist", active: true, locked_until: null },
          ]),
        );
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    renderWithProviders(<StaffAccounts />);

    const meRow = (await screen.findByText("Asha Desk")).closest("tr");
    if (!meRow) throw new Error("row not rendered");
    expect(within(meRow).queryByRole("button", { name: /new password/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Set a new password for Ravi" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("New password"), { target: { value: "short" } });
    fireEvent.change(within(dialog).getByLabelText("Type the new password again"), { target: { value: "short" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Set new password" }));
    expect(await within(dialog).findByText("Use at least 12 characters")).toBeTruthy();

    fireEvent.change(within(dialog).getByLabelText("New password"), { target: { value: "a long new passphrase" } });
    fireEvent.change(within(dialog).getByLabelText("Type the new password again"), { target: { value: "a long new passphrase" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Set new password" }));

    expect(await screen.findByText("Password changed")).toBeTruthy();
    const patches = calls.filter((c) => c.method === "PATCH");
    expect(patches).toHaveLength(1);
    expect(patches[0].body).toEqual({ password: "a long new passphrase" });
    expect(patches[0].headers["x-csrf-token"]).toBe("csrf-1");
  });
});

describe("FAQ duplicate topic", () => {
  it("shows the 409 CONFLICT on the topic field and keeps the dialog open", async () => {
    stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/faq") && call.method === "GET") return jsonResponse(200, page([]));
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
      if (call.url === "/api/v1/faq" && call.method === "POST") {
        return jsonResponse(409, errorEnvelope("CONFLICT", "Topic already exists"));
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    renderWithProviders(<FaqEditor />);
    fireEvent.click(await screen.findByRole("button", { name: "Add the first answer" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Topic name"), { target: { value: "parking_info" } });
    fireEvent.change(within(dialog).getByLabelText("Answer"), { target: { value: "Free parking behind the clinic." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add answer" }));

    expect(await within(dialog).findByText(/Another answer already uses this topic name/)).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});

describe("clinic settings times", () => {
  it("shows HH:MM:SS from the API as HH:MM and PATCHes only the changed fields", async () => {
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
    const { calls } = stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/settings" && call.method === "GET") return jsonResponse(200, settings);
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
      if (call.url === "/api/v1/settings" && call.method === "PATCH") {
        return jsonResponse(200, { ...settings, ...(call.body as object), morning_end: "11:30:00" });
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    renderWithProviders(<SettingsFormView />);

    const morning = (await screen.findByLabelText("Morning ends at")) as HTMLInputElement;
    expect(morning.value).toBe("12:00");
    fireEvent.change(morning, { target: { value: "11:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await screen.findByText("Clinic settings saved");
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({ morning_end: "11:30" });
    await waitFor(() => expect((screen.getByLabelText("Morning ends at") as HTMLInputElement).value).toBe("11:30"));
  });
});
