import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WeeklyMetrics } from "@/features/admin/metrics/weekly-metrics";

import { jsonResponse, stubFetch } from "./helpers";
import { renderWithProviders } from "./render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/admin/metrics",
  useSearchParams: () => new URLSearchParams("week=2030-01-09"),
}));

describe("WeeklyMetrics", () => {
  it("requests the Monday of the chosen week and shows zeros, not an error, for an empty week (E6-S6-AC2)", async () => {
    const { calls } = stubFetch((call) =>
      call.url === "/api/v1/clinic/today"
        ? jsonResponse(200, { date: "2030-01-09", timezone: "Asia/Kolkata" })
        : jsonResponse(200, {
            week_start: "2030-01-07",
            bookings_by_source: { bot: 0, staff: 0 },
            cancellations: 0,
            per_doctor: [{ doctor_id: "d-1", name: "Dr Rao", completed: 0, no_show: 0, no_show_rate: 0 }],
          }),
    );
    renderWithProviders(<WeeklyMetrics />);

    expect(await screen.findByText("No bookings, cancellations or attendance were recorded this week.")).toBeTruthy();
    expect(calls.filter((c) => c.url.startsWith("/api/v1/metrics")).map((c) => c.url)).toEqual([
      "/api/v1/metrics/weekly?week_start=2030-01-07",
    ]);
    expect(screen.getByText("Booked through Telegram").nextElementSibling?.textContent).toBe("0");
    expect(screen.getByText("Cancellations").nextElementSibling?.textContent).toBe("0");
    expect(screen.getByRole("cell", { name: "0%" })).toBeTruthy();
    expect(screen.queryByText(/Couldn't load/)).toBeNull();
  });
});
