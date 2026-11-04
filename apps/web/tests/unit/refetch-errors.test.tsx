import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StaffGate } from "@/components/gates";
import { ScheduleEditor } from "@/features/admin/doctors/schedule-editor";
import { FaqEditor } from "@/features/admin/faq/faq-editor";
import { SettingsFormView } from "@/features/admin/settings/settings-form";
import { AttentionPanel } from "@/features/today/attention-panel";
import { TodayView } from "@/features/today/today-view";
import { queryKeys } from "@/lib/query";

import { errorEnvelope, jsonResponse, sessionBody, stubFetch, type StubbedCall } from "./helpers";
import { appointment, renderWithProviders } from "./render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams("date=2030-01-09"),
}));

/*
 * M1: a failed background refetch must not replace content the user already has
 * (and possibly edited) with a full-page error. The full error is only for a first
 * load that failed; a failed refresh shows a non-blocking notice.
 */

const serverDown = () => jsonResponse(500, errorEnvelope("ERROR", "Database unavailable", { request_id: "r-refetch" }));

describe("a failed background refetch keeps the content", () => {
  it("StaffGate keeps the app shell and page when the session refresh fails", async () => {
    let meCalls = 0;
    stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/auth/me") {
        meCalls += 1;
        return meCalls === 1 ? jsonResponse(200, sessionBody("receptionist")) : serverDown();
      }
      throw new Error(`unexpected ${call.url}`);
    });
    const { queryClient } = renderWithProviders(
      <StaffGate>
        <p>Child content</p>
      </StaffGate>,
    );
    expect(await screen.findByText("Child content")).toBeTruthy();

    await act(() => queryClient.refetchQueries({ queryKey: queryKeys.session }));
    await waitFor(() => expect(queryClient.getQueryState(queryKeys.session)?.status).toBe("error"));

    expect(screen.getByText("Child content")).toBeTruthy();
    expect(await screen.findByText(/Couldn't refresh your account/)).toBeTruthy();
    expect(screen.queryByText("Couldn't load your account")).toBeNull();
  });

  it("ScheduleEditor keeps unsaved edits when a refresh fails", async () => {
    let gets = 0;
    stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/doctors/d-1/schedule" && call.method === "GET") {
        gets += 1;
        return gets === 1
          ? jsonResponse(200, { blocks: [{ weekday: 0, start: "09:00:00", end: "13:00:00", slot_minutes: 15 }] })
          : serverDown();
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    const { queryClient } = renderWithProviders(<ScheduleEditor doctorId="d-1" doctorName="Dr Rao" />);
    const start = (await screen.findByLabelText("Starts")) as HTMLInputElement;
    await waitFor(() => expect(start.value).toBe("09:00"));
    fireEvent.change(start, { target: { value: "08:00" } });

    await act(() => queryClient.refetchQueries({ queryKey: queryKeys.weeklySchedule("d-1") }));
    await waitFor(() => expect(queryClient.getQueryState(queryKeys.weeklySchedule("d-1"))?.status).toBe("error"));

    expect((screen.getByLabelText("Starts") as HTMLInputElement).value).toBe("08:00");
    expect(await screen.findByText(/Couldn't refresh the weekly hours/)).toBeTruthy();
  });

  it("Settings keeps unsaved edits when a refresh fails", async () => {
    let gets = 0;
    stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/settings" && call.method === "GET") {
        gets += 1;
        return gets === 1 ? jsonResponse(200, settingsBody()) : serverDown();
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    const { queryClient } = renderWithProviders(<SettingsFormView />);
    const name = (await screen.findByLabelText("Clinic name")) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "Sunrise Family Clinic" } });

    await act(() => queryClient.refetchQueries({ queryKey: queryKeys.settings }));
    await waitFor(() => expect(queryClient.getQueryState(queryKeys.settings)?.status).toBe("error"));

    expect((screen.getByLabelText("Clinic name") as HTMLInputElement).value).toBe("Sunrise Family Clinic");
    expect(await screen.findByText(/Couldn't refresh clinic settings/)).toBeTruthy();
  });

  it("Today keeps the last schedule on screen when the 30-second refresh fails", async () => {
    let scheduleGets = 0;
    stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/schedule")) {
        scheduleGets += 1;
        return scheduleGets === 1
          ? jsonResponse(200, {
              date: "2030-01-09",
              doctors: [{ doctor_id: "d-1", name: "Dr Rao", specialty: "General physician", appointments: [appointment()] }],
            })
          : serverDown();
      }
      if (call.url === "/api/v1/attention") return jsonResponse(200, { tickets: [], alerts: [], flagged: [] });
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("receptionist"));
      throw new Error(`unexpected ${call.url}`);
    });
    const { queryClient } = renderWithProviders(<TodayView />);
    expect(await screen.findByText("Test Patient")).toBeTruthy();

    await act(() => queryClient.refetchQueries({ queryKey: queryKeys.schedule("2030-01-09") }));
    await waitFor(() => expect(queryClient.getQueryState(queryKeys.schedule("2030-01-09"))?.status).toBe("error"));

    expect(screen.getByText("Test Patient")).toBeTruthy();
    expect(await screen.findByText(/Couldn't refresh the schedule/)).toBeTruthy();
    expect(screen.queryByText("Couldn't load the schedule")).toBeNull();
  });

  it("the attention panel keeps listed alerts and never claims 'nothing needs attention' after a failed refresh", async () => {
    let gets = 0;
    const alert = { id: "a-1", created_at: "2030-01-09T04:00:00Z", patient: null, telegram_user_id: 12345 };
    stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/attention") {
        gets += 1;
        if (gets === 1) return jsonResponse(200, { tickets: [], alerts: [alert], flagged: [] });
        return serverDown();
      }
      throw new Error(`unexpected ${call.url}`);
    });
    const { queryClient } = renderWithProviders(<AttentionPanel />);
    expect(await screen.findByText(/Unregistered Telegram user/)).toBeTruthy();

    await act(() => queryClient.refetchQueries({ queryKey: queryKeys.attention }));
    await waitFor(() => expect(queryClient.getQueryState(queryKeys.attention)?.status).toBe("error"));

    expect(screen.getByText(/Unregistered Telegram user/)).toBeTruthy();
    expect(await screen.findByText(/Couldn't refresh emergency alerts and help requests/)).toBeTruthy();
    expect(screen.queryByText(/Nothing needs attention/)).toBeNull();
  });

  it("admin lists (FAQ) keep their rows after a failed refresh", async () => {
    let gets = 0;
    stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/faq")) {
        gets += 1;
        if (gets === 1) {
          const entry = { id: "f-1", topic: "parking_info", aliases: [], answer: "Behind the clinic.", updated_at: "2030-01-09T04:00:00Z" };
          return jsonResponse(200, { items: [entry], page: 1, page_size: 100, total: 1 });
        }
        return serverDown();
      }
      throw new Error(`unexpected ${call.url}`);
    });
    const { queryClient } = renderWithProviders(<FaqEditor />);
    expect(await screen.findByText("parking_info")).toBeTruthy();

    await act(() => queryClient.refetchQueries({ queryKey: queryKeys.faq }));
    await waitFor(() => expect(queryClient.getQueryState(queryKeys.faq)?.status).toBe("error"));

    expect(screen.getByText("parking_info")).toBeTruthy();
    expect(await screen.findByText(/Couldn't refresh clinic answers/)).toBeTruthy();
  });

  it("still shows the full error when the first load fails", async () => {
    stubFetch(() => serverDown());
    renderWithProviders(<SettingsFormView />);
    expect(await screen.findByText("Couldn't load clinic settings")).toBeTruthy();
  });
});

function settingsBody() {
  return {
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
}
