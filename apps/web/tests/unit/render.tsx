import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { ToastProvider } from "@/components/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";

/** Renders with fresh providers; retries off so error states appear immediately. */
export function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <ToastProvider>{ui}</ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

export function appointment(overrides: Record<string, unknown> = {}) {
  return {
    id: "apt-1",
    reference: "APT-000123",
    doctor_id: "d-1",
    doctor_name: "Dr Rao",
    start: "2030-01-09T04:00:00Z",
    end: "2030-01-09T04:15:00Z",
    date: "2030-01-09",
    time_label: "9:30 AM",
    status: "booked",
    source: "bot",
    patient: { id: "p-1", full_name: "Test Patient", phone: "+91 90000 00000" },
    reminders: { "24h": "sent", "2h": null },
    patient_confirmed: true,
    staff_attention: null,
    can_mark_attendance: false,
    ...overrides,
  };
}
