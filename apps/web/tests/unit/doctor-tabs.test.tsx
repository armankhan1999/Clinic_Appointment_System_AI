import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DoctorDetail } from "@/features/admin/doctors/doctor-detail";

import { jsonResponse, stubFetch, type StubbedCall } from "./helpers";
import { renderWithProviders } from "./render";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "d-1" }),
}));

/* M5: switching to the Leave tab and back must not discard unsaved weekly hours. */
describe("doctor detail tabs", () => {
  it("keeps unsaved weekly-hours edits across a tab switch", async () => {
    stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/doctors?") || call.url === "/api/v1/doctors") {
        return jsonResponse(200, { items: [{ id: "d-1", name: "Dr Rao", specialty: "General physician", active: true }] });
      }
      if (call.url === "/api/v1/doctors/d-1/schedule") {
        return jsonResponse(200, { blocks: [{ weekday: 0, start: "09:00:00", end: "13:00:00", slot_minutes: 15 }] });
      }
      if (call.url === "/api/v1/doctors/d-1/leaves") return jsonResponse(200, { items: [] });
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    renderWithProviders(<DoctorDetail />);

    const start = (await screen.findByLabelText("Starts")) as HTMLInputElement;
    await waitFor(() => expect(start.value).toBe("09:00"));
    fireEvent.change(start, { target: { value: "08:00" } });

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Leave days" }), { button: 0 });
    expect(await screen.findByRole("heading", { name: "Add a leave day" })).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Weekly hours" }), { button: 0 });

    await waitFor(() => expect(screen.getByRole("tab", { name: "Weekly hours" }).getAttribute("aria-selected")).toBe("true"));
    expect((screen.getByLabelText("Starts") as HTMLInputElement).value).toBe("08:00");
    expect(screen.getByText("You have unsaved changes.")).toBeTruthy();
  });

  it("shows only the active tab's content", async () => {
    stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/doctors?") || call.url === "/api/v1/doctors") {
        return jsonResponse(200, { items: [{ id: "d-1", name: "Dr Rao", specialty: "General physician", active: true }] });
      }
      if (call.url === "/api/v1/doctors/d-1/schedule") return jsonResponse(200, { blocks: [] });
      if (call.url === "/api/v1/doctors/d-1/leaves") return jsonResponse(200, { items: [] });
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    renderWithProviders(<DoctorDetail />);
    await screen.findByRole("button", { name: "Add hours on Monday" });
    expect(screen.queryByRole("heading", { name: "Add a leave day" })).toBeNull();
  });
});
