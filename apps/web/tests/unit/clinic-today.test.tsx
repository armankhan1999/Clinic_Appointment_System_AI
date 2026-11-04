import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { useClinicToday } from "@/lib/clinic-today";

import { jsonResponse, stubFetch } from "./helpers";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useClinicToday", () => {
  it("uses the clinic's date from the API, not the PC's clock", async () => {
    const { calls } = stubFetch([jsonResponse(200, { date: "2030-01-07", timezone: "Asia/Kolkata" })]);
    const { result } = renderHook(() => useClinicToday(), { wrapper });
    await waitFor(() => expect(result.current).toBe("2030-01-07"));
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["GET /api/v1/clinic/today"]);
  });
});
