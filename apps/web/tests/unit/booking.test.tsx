import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BookingFlow } from "@/features/booking/booking-flow";

import { errorEnvelope, jsonResponse, sessionBody, stubFetch, type StubbedCall } from "./helpers";
import { appointment, renderWithProviders } from "./render";

const doctor = { id: "d-1", name: "Dr Rao", specialty: "General physician", active: true };
const slotsFirst = [
  { start: "2030-01-09T04:00:00Z", time_label: "9:30 AM" },
  { start: "2030-01-09T04:15:00Z", time_label: "9:45 AM" },
];
const slotsAfterConflict = [{ start: "2030-01-09T04:15:00Z", time_label: "9:45 AM" }];

async function chooseDoctor() {
  const trigger = await screen.findByRole("combobox", { name: "Doctor" });
  await waitFor(() => expect(trigger.hasAttribute("disabled")).toBe(false));
  fireEvent.keyDown(trigger, { key: "Enter" });
  const option = await screen.findByRole("option", { name: /Dr Rao/ });
  fireEvent.keyDown(option, { key: "Enter" });
}

describe("BookingFlow", () => {
  it("shows SLOT_TAKEN clearly, reloads the free times and books nothing twice", async () => {
    let availabilityCalls = 0;
    const { calls } = stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/doctors")) return jsonResponse(200, { items: [doctor] });
      if (call.url.startsWith("/api/v1/availability")) {
        availabilityCalls += 1;
        return jsonResponse(200, { date: "2030-01-09", slots: availabilityCalls === 1 ? slotsFirst : slotsAfterConflict });
      }
      if (call.url.startsWith("/api/v1/patients")) {
        return jsonResponse(200, { items: [{ id: "p-1", full_name: "Test Patient", phone: "+91 90000 00000" }] });
      }
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody());
      if (call.url === "/api/v1/appointments") {
        return jsonResponse(409, errorEnvelope("SLOT_TAKEN", "Slot already booked", { request_id: "r-409" }));
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });

    renderWithProviders(<BookingFlow />);
    await chooseDoctor();

    fireEvent.click(await screen.findByRole("radio", { name: "9:30 AM" }));
    fireEvent.change(screen.getByLabelText("Patient's phone number"), { target: { value: "+91 90000 00000" } });
    fireEvent.click(screen.getByRole("button", { name: "Find patient" }));
    await waitFor(() => expect((screen.getByRole("radio", { name: /Test Patient/ }) as HTMLInputElement).checked).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));

    expect(await screen.findByText("That time is no longer free")).toBeTruthy();
    expect(screen.getByText(/9:30 AM was just booked by someone else/)).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("radio", { name: "9:30 AM" })).toBeNull());
    expect(screen.getByRole("radio", { name: "9:45 AM" })).toBeTruthy();

    const posts = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/appointments");
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toEqual({ doctor_id: "d-1", start: "2030-01-09T04:00:00Z", patient: { id: "p-1" } });
    expect(posts[0].headers["x-csrf-token"]).toBe("csrf-1");
    expect((screen.getByRole("button", { name: "Book appointment" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it.each([
    ["same_doctor_same_day", /already has an appointment with this doctor on this day/, /Cancel one of theirs first/],
    ["max_upcoming", /Cancel one of theirs first/, /with this doctor on this day/],
  ])("explains which booking limit refused the booking (%s)", async (reason, shown, notShown) => {
    stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/doctors")) return jsonResponse(200, { items: [doctor] });
      if (call.url.startsWith("/api/v1/availability")) return jsonResponse(200, { date: "2030-01-09", slots: slotsFirst });
      if (call.url.startsWith("/api/v1/patients")) {
        return jsonResponse(200, { items: [{ id: "p-1", full_name: "Test Patient", phone: "+91 90000 00000" }] });
      }
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody());
      if (call.url === "/api/v1/appointments") {
        return jsonResponse(409, errorEnvelope("LIMIT_REACHED", "The patient has reached the booking limit.", { details: { reason } }));
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });

    renderWithProviders(<BookingFlow />);
    await chooseDoctor();
    fireEvent.click(await screen.findByRole("radio", { name: "9:30 AM" }));
    fireEvent.change(screen.getByLabelText("Patient's phone number"), { target: { value: "+91 90000 00000" } });
    fireEvent.click(screen.getByRole("button", { name: "Find patient" }));
    await waitFor(() => expect((screen.getByRole("radio", { name: /Test Patient/ }) as HTMLInputElement).checked).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));

    expect(await screen.findByText(shown)).toBeTruthy();
    expect(screen.queryByText(notShown)).toBeNull();
  });

  it("registers a new patient only with verbal consent, then confirms the booking with its reference", async () => {
    const { calls } = stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/doctors")) return jsonResponse(200, { items: [doctor] });
      if (call.url.startsWith("/api/v1/availability")) return jsonResponse(200, { date: "2030-01-09", slots: slotsFirst });
      if (call.url.startsWith("/api/v1/patients")) return jsonResponse(200, { items: [] });
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody());
      if (call.url === "/api/v1/appointments") {
        return jsonResponse(201, appointment({ source: "staff", patient: { id: "p-9", full_name: "Meera Iyer", phone: "+91 92222 22222" } }));
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });

    renderWithProviders(<BookingFlow />);
    await chooseDoctor();
    fireEvent.click(await screen.findByRole("radio", { name: "9:45 AM" }));
    fireEvent.change(screen.getByLabelText("Patient's phone number"), { target: { value: "+91 92222 22222" } });
    fireEvent.click(screen.getByRole("button", { name: "Find patient" }));

    fireEvent.change(await screen.findByLabelText("Full name"), { target: { value: "Meera Iyer" } });
    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));
    expect(await screen.findByText("Ask the patient for consent before saving their details")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/v1/appointments")).toBe(false);

    fireEvent.click(screen.getByRole("checkbox", { name: "The patient gave verbal consent" }));
    fireEvent.click(screen.getByRole("button", { name: "Book appointment" }));

    expect(await screen.findByRole("heading", { name: "Appointment booked" })).toBeTruthy();
    expect(screen.getByText("APT-000123")).toBeTruthy();
    const post = calls.find((c) => c.method === "POST" && c.url === "/api/v1/appointments");
    expect(post?.body).toEqual({
      doctor_id: "d-1",
      start: "2030-01-09T04:15:00Z",
      patient: { full_name: "Meera Iyer", phone: "+91 92222 22222", verbal_consent: true },
    });
  });
});
