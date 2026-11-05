import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppointmentRow } from "@/features/today/appointment-row";
import { AttentionPanel } from "@/features/today/attention-panel";
import { loginErrorMessage } from "@/features/auth/login-form";
import { ApiError } from "@/lib/api/errors";
import type { Appointment } from "@/lib/api/schemas";

import { errorEnvelope, jsonResponse, stubFetch } from "./helpers";
import { appointment, renderWithProviders } from "./render";

describe("AttentionPanel", () => {
  it("shows a calm empty state when nothing needs attention", async () => {
    stubFetch([jsonResponse(200, { tickets: [], alerts: [], flagged: [] })]);
    renderWithProviders(<AttentionPanel />);
    expect(await screen.findByText(/Nothing needs attention right now/)).toBeTruthy();
  });

  it("lists emergency alerts first with patient details, or names an unregistered Telegram user", async () => {
    stubFetch([
      jsonResponse(200, {
        tickets: [
          {
            id: "t-1",
            reason: "patient_requested",
            created_at: "2030-01-09T04:00:00Z",
            patient: { id: "p-2", full_name: "Ravi Kumar", phone: "+91 91111 11111" },
          },
        ],
        alerts: [
          { id: "a-1", created_at: "2030-01-09T04:00:00Z", patient: { id: "p-3", full_name: "Meera Iyer", phone: "+91 92222 22222" }, telegram_user_id: 77 },
          { id: "a-2", created_at: "2030-01-09T04:00:00Z", patient: null, telegram_user_id: 12345 },
        ],
        flagged: [appointment({ staff_attention: { reason: "notification_failed", at: "2030-01-09T04:00:00Z" } })],
      }),
    ]);
    renderWithProviders(<AttentionPanel />);

    const panel = await screen.findByRole("region", { name: /Needs attention/ });
    const items = within(panel).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0].textContent).toContain("Emergency message");
    expect(items[0].textContent).toContain("Meera Iyer");
    expect(items[0].textContent).toContain("+91 92222 22222");
    expect(items[1].textContent).toContain("Unregistered Telegram user");
    expect(items[1].textContent).toContain("12345");
    expect(items[2].textContent).toContain("Patient asked to talk to a person");
    expect(items[3].textContent).toContain("Couldn't deliver the Telegram message");
    expect(within(items[0]).getByRole("button", { name: "Acknowledge" })).toBeTruthy();
    expect(within(items[2]).getByRole("button", { name: "Resolve" })).toBeTruthy();
    expect(within(items[3]).getByRole("button", { name: "Clear attention" })).toBeTruthy();
  });

  it("shows the error with the request id instead of hiding alerts when loading fails", async () => {
    stubFetch([jsonResponse(500, errorEnvelope("ERROR", "Database unavailable", { request_id: "req-500" }))]);
    renderWithProviders(<AttentionPanel />);
    const heading = await screen.findByText("Couldn't load emergency alerts and help requests");
    const alert = heading.closest('[role="alert"]');
    expect(alert).not.toBeNull();
    if (!alert) return;
    expect(alert.textContent).toContain("Database unavailable");
    expect(alert.textContent).toContain("req-500");
  });

  it("acknowledges an alert only after confirmation and sends the CSRF header", async () => {
    const { calls } = stubFetch((call) => {
      if (call.url === "/api/v1/attention") {
        return jsonResponse(200, {
          tickets: [],
          alerts: [{ id: "a-1", created_at: "2030-01-09T04:00:00Z", patient: null, telegram_user_id: null }],
          flagged: [],
        });
      }
      if (call.url === "/api/v1/auth/me") {
        return jsonResponse(200, { user: { id: "u", username: "u", display_name: "U", role: "receptionist", active: true }, csrf_token: "tok" });
      }
      if (call.url === "/api/v1/alerts/a-1/acknowledge") {
        return jsonResponse(200, { id: "a-1", acknowledged_by: "u", acknowledged_at: "2030-01-09T04:05:00Z" });
      }
      throw new Error(`unexpected ${call.url}`);
    });
    renderWithProviders(<AttentionPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Acknowledge" }));
    expect(calls.some((c) => c.url.includes("acknowledge"))).toBe(false);

    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Acknowledge" }));
    await screen.findByText("Emergency alert acknowledged");
    const ack = calls.find((c) => c.url.endsWith("/acknowledge"));
    expect(ack?.method).toBe("POST");
    expect(ack?.headers["x-csrf-token"]).toBe("tok");
  });
});

describe("AppointmentRow", () => {
  const row = (overrides: Record<string, unknown>) =>
    renderWithProviders(
      <ol>
        <AppointmentRow appointment={appointment(overrides) as Appointment} isAdmin={false} />
      </ol>,
    );

  it("shows time, patient, phone, status, source, confirmation and reminder status with text labels", () => {
    row({});
    const item = screen.getByRole("listitem");
    for (const text of ["9:30 AM", "APT-000123", "Test Patient", "+91 90000 00000", "Booked", "Telegram", "Patient confirmed", "24 h reminder sent", "2 h reminder not due yet"]) {
      expect(item.textContent).toContain(text);
    }
  });

  it("says a patient without Telegram gets no reminders instead of 'not due yet'", () => {
    // Live finding 2026-11-05: a started walk-in appointment read "24 h reminder not due yet".
    row({ source: "staff", patient: { id: "p-2", full_name: "Walk In", phone: "+1 202-555-0191", telegram: false }, reminders: { "24h": null, "2h": null } });
    const text = screen.getByRole("listitem").textContent ?? "";
    expect(text).toContain("No reminders: not on Telegram");
    expect(text).not.toContain("not due yet");
  });

  it("shows the staff-attention flag and reason", () => {
    row({ staff_attention: { reason: "notification_failed", at: "2030-01-09T04:00:00Z" } });
    expect(screen.getByRole("listitem").textContent).toContain("Needs a call");
  });

  it("has no actions for a cancelled appointment", () => {
    row({ status: "cancelled" });
    expect(screen.queryByRole("button", { name: /Actions for/ })).toBeNull();
  });
});

describe("login error messages", () => {
  it("is generic for wrong credentials and gives the lockout time for 423", () => {
    expect(loginErrorMessage(new ApiError({ status: 401, code: "UNAUTHENTICATED" })).title).toBe("Username or password is incorrect");
    const locked = loginErrorMessage(
      new ApiError({ status: 423, code: "ACCOUNT_LOCKED", details: { locked_until: "2030-01-09T04:15:00Z" } }),
      new Date("2030-01-09T04:03:30Z"),
    );
    expect(locked.body).toContain("about 12 minutes");
    expect(loginErrorMessage(new ApiError({ status: 429, code: "RATE_LIMITED" })).title).toBe("Too many sign-in attempts");
  });
});
