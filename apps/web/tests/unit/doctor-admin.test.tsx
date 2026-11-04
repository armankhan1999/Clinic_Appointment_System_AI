import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LeaveManager } from "@/features/admin/doctors/leave-manager";
import { ScheduleEditor } from "@/features/admin/doctors/schedule-editor";

import { jsonResponse, sessionBody, stubFetch, type StubbedCall } from "./helpers";
import { appointment, renderWithProviders } from "./render";

describe("ScheduleEditor", () => {
  it("loads blocks per weekday, flags an overlap, clears it once fixed and saves the replacement pattern", async () => {
    const { calls } = stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/doctors/d-1/schedule" && call.method === "GET") {
        return jsonResponse(200, { blocks: [{ weekday: 0, start: "09:00:00", end: "13:00:00", slot_minutes: 15 }] });
      }
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
      if (call.url === "/api/v1/doctors/d-1/schedule" && call.method === "PUT") return jsonResponse(200, call.body);
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });

    renderWithProviders(<ScheduleEditor doctorId="d-1" doctorName="Dr Rao" />);
    const mondayStart = (await screen.findByLabelText("Starts")) as HTMLInputElement;
    await waitFor(() => expect(mondayStart.value).toBe("09:00"));

    fireEvent.click(screen.getByRole("button", { name: "Add another block" }));
    const starts = screen.getAllByLabelText("Starts");
    const ends = screen.getAllByLabelText("Ends");
    fireEvent.change(starts[1], { target: { value: "12:00" } });
    fireEvent.change(ends[1], { target: { value: "14:00" } });
    fireEvent.blur(ends[1]);
    expect(await screen.findByText("Overlaps the 09:00–13:00 block")).toBeTruthy();

    fireEvent.change(starts[1], { target: { value: "13:30" } });
    fireEvent.blur(starts[1]);
    await waitFor(() => expect(screen.queryByText(/Overlaps the/)).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Save weekly hours" }));
    await screen.findByText("Weekly hours saved");
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers["x-csrf-token"]).toBe("csrf-1");
    expect(put?.body).toEqual({
      blocks: [
        { weekday: 0, start: "09:00", end: "13:00", slot_minutes: 15 },
        { weekday: 0, start: "13:30", end: "14:00", slot_minutes: 15 },
      ],
    });
  });

  it("blocks saving when the end time is not after the start time (E6-S3-AC2)", async () => {
    const { calls } = stubFetch([jsonResponse(200, { blocks: [] })]);
    renderWithProviders(<ScheduleEditor doctorId="d-1" doctorName="Dr Rao" />);
    fireEvent.click(await screen.findByRole("button", { name: "Add hours on Monday" }));
    fireEvent.change(screen.getByLabelText("Ends"), { target: { value: "08:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save weekly hours" }));
    expect(await screen.findByText("End time must be after the start time")).toBeTruthy();
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
  });
});

describe("LeaveManager", () => {
  it("previews affected bookings and requires explicit confirmation before sending confirm_affected=true", async () => {
    const affected = [appointment({ id: "apt-7", time_label: "10:00 AM", patient: { id: "p", full_name: "Asha Patel", phone: "+91 93333 33333" } })];
    const { calls } = stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/doctors/d-1/leaves" && call.method === "GET") return jsonResponse(200, { items: [] });
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
      if (call.url === "/api/v1/doctors/d-1/leaves/preview") return jsonResponse(200, { affected });
      if (call.url === "/api/v1/doctors/d-1/leaves" && call.method === "POST") {
        return jsonResponse(201, { leave: { id: "l-1", date: "2030-01-09", reason: "Conference" }, cancelled: affected });
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });

    renderWithProviders(<LeaveManager doctorId="d-1" doctorName="Dr Rao" />);
    fireEvent.change(await screen.findByLabelText("Day off"), { target: { value: "2030-01-09" } });
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Conference" } });
    fireEvent.click(screen.getByRole("button", { name: "Check bookings on this day" }));

    expect(await screen.findByText("1 booked appointment will be cancelled")).toBeTruthy();
    expect(screen.getByText("Asha Patel")).toBeTruthy();
    const confirm = screen.getByRole("button", { name: "Cancel 1 appointment and add leave" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    // Live finding 2026-11-05: the label read "these 1 appointment".
    fireEvent.click(screen.getByRole("checkbox", { name: "I understand this appointment will be cancelled" }));
    expect(confirm.disabled).toBe(false);
    fireEvent.click(confirm);

    await screen.findByText("Leave added");
    const post = calls.find((c) => c.method === "POST" && c.url === "/api/v1/doctors/d-1/leaves");
    expect(post?.body).toEqual({ date: "2030-01-09", reason: "Conference", confirm_affected: true });
  });

  it("asks for a reason before checking bookings, because the API refuses a leave without one", async () => {
    const { calls } = stubFetch((call: StubbedCall) => {
      if (call.url === "/api/v1/doctors/d-1/leaves" && call.method === "GET") return jsonResponse(200, { items: [] });
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });

    renderWithProviders(<LeaveManager doctorId="d-1" doctorName="Dr Rao" />);
    fireEvent.change(await screen.findByLabelText("Day off"), { target: { value: "2030-01-09" } });
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Check bookings on this day" }));

    expect(await screen.findByText("Give a reason. Patients whose appointments are cancelled are sent it.")).toBeTruthy();
    expect(screen.getByLabelText(/Reason/).getAttribute("aria-invalid")).toBe("true");
    expect(screen.queryByText(/optional/i)).toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });
});
