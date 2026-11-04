import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BookingFlow } from "@/features/booking/booking-flow";
import { AppointmentRow } from "@/features/today/appointment-row";
import { ApiError, isOutcomeUnknown } from "@/lib/api/errors";
import type { Appointment } from "@/lib/api/schemas";

import { jsonResponse, sessionBody, stubFetch, type StubbedCall } from "./helpers";
import { appointment, renderWithProviders } from "./render";

/*
 * M2: when a write times out or the connection drops (status 0), the server may
 * have done it. The UI must not say "not booked/not cancelled"; it must say the
 * outcome is unknown, point to the schedule and refresh it.
 */

const dropped = () => Promise.reject(new TypeError("Failed to fetch"));

describe("isOutcomeUnknown", () => {
  it("is true only for transport failures with no HTTP answer", () => {
    expect(isOutcomeUnknown(new ApiError({ status: 0, code: "TIMEOUT" }))).toBe(true);
    expect(isOutcomeUnknown(new ApiError({ status: 0, code: "NETWORK_ERROR" }))).toBe(true);
    expect(isOutcomeUnknown(new ApiError({ status: 409, code: "SLOT_TAKEN" }))).toBe(false);
    expect(isOutcomeUnknown(new ApiError({ status: 500, code: "ERROR" }))).toBe(false);
    expect(isOutcomeUnknown(new Error("x"))).toBe(false);
  });
});

describe("booking whose answer never arrived", () => {
  it("says the result is unknown, reloads free times and clears the chosen time", async () => {
    let availabilityCalls = 0;
    stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/doctors")) {
        return jsonResponse(200, { items: [{ id: "d-1", name: "Dr Rao", specialty: "General physician", active: true }] });
      }
      if (call.url.startsWith("/api/v1/availability")) {
        availabilityCalls += 1;
        return jsonResponse(200, { date: "2030-01-09", slots: [{ start: "2030-01-09T04:00:00Z", time_label: "9:30 AM" }] });
      }
      if (call.url.startsWith("/api/v1/patients")) {
        return jsonResponse(200, { items: [{ id: "p-1", full_name: "Test Patient", phone: "+91 90000 00000" }] });
      }
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody());
      if (call.url === "/api/v1/appointments") return dropped();
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });

    renderWithProviders(<BookingFlow />);
    const trigger = await screen.findByRole("combobox", { name: "Doctor" });
    await waitFor(() => expect(trigger.hasAttribute("disabled")).toBe(false));
    fireEvent.keyDown(trigger, { key: "Enter" });
    fireEvent.keyDown(await screen.findByRole("option", { name: /Dr Rao/ }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("radio", { name: "9:30 AM" }));
    fireEvent.change(screen.getByLabelText("Patient's phone number"), { target: { value: "+91 90000 00000" } });
    fireEvent.click(screen.getByRole("button", { name: "Find patient" }));
    await waitFor(() => expect((screen.getByRole("radio", { name: /Test Patient/ }) as HTMLInputElement).checked).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));

    expect(await screen.findByText("We couldn't confirm whether the appointment was booked")).toBeTruthy();
    expect(screen.queryByText("The appointment was not booked")).toBeNull();
    expect(screen.getByRole("link", { name: /Check the schedule for/ }).getAttribute("href")).toMatch(/^\/\?date=\d{4}-\d{2}-\d{2}$/);
    await waitFor(() => expect(availabilityCalls).toBe(2));
    expect((screen.getByRole("button", { name: "Book appointment" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("cancel and attendance whose answer never arrived", () => {
  function renderRow(overrides: Record<string, unknown>) {
    stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody());
      if (call.method === "POST") return dropped();
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    const view = renderWithProviders(
      <ol>
        <AppointmentRow appointment={appointment(overrides) as Appointment} isAdmin={false} />
      </ol>,
    );
    const invalidate = vi.spyOn(view.queryClient, "invalidateQueries");
    fireEvent.keyDown(screen.getByRole("button", { name: /Actions for/ }), { key: "Enter" });
    return { invalidate };
  }

  it("cancel: says it may have been cancelled and refreshes the schedule", async () => {
    const { invalidate } = renderRow({});
    fireEvent.click(await screen.findByRole("menuitem", { name: "Cancel appointment…" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.change(within(dialog).getByLabelText("Reason for the patient"), { target: { value: "Doctor unwell" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));

    expect(await within(dialog).findByText("We couldn't confirm whether the appointment was cancelled")).toBeTruthy();
    expect(within(dialog).getByText(/Check its status in the schedule before trying again/)).toBeTruthy();
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["schedule"] }));
  });

  it("attendance: says it may have been marked and refreshes the schedule", async () => {
    const { invalidate } = renderRow({ can_mark_attendance: true });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Mark completed" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark completed" }));

    expect(await within(dialog).findByText("We couldn't confirm whether attendance was saved")).toBeTruthy();
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["schedule"] }));
  });
});
