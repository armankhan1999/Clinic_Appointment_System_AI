import { QueryClient } from "@tanstack/react-query";

import { isApiError } from "@/lib/api/errors";

/** Schedule and attention refresh often enough that new bot bookings appear within a minute (E6-S2-AC2). */
export const LIVE_REFRESH_MS = 30_000;

export const queryKeys = {
  session: ["session"] as const,
  clinicToday: ["clinic-today"] as const,
  schedule: (date: string) => ["schedule", date] as const,
  scheduleAll: ["schedule"] as const,
  attention: ["attention"] as const,
  doctors: (filter: "active" | "all") => ["doctors", filter] as const,
  doctorsAll: ["doctors"] as const,
  availability: (doctorId: string, date: string) => ["availability", doctorId, date] as const,
  availabilityAll: ["availability"] as const,
  patientsByPhone: (phone: string) => ["patients", phone] as const,
  weeklySchedule: (doctorId: string) => ["weekly-schedule", doctorId] as const,
  leaves: (doctorId: string) => ["leaves", doctorId] as const,
  faq: ["faq"] as const,
  settings: ["settings"] as const,
  audit: (filters: Record<string, unknown>) => ["audit", filters] as const,
  metrics: (weekStart: string) => ["metrics", weekStart] as const,
  staffUsers: ["staff-users"] as const,
};

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        // 4xx answers and contract mismatches will not fix themselves; only retry transport and 5xx failures.
        retry: (failureCount, error) => {
          if (isApiError(error) && (error.isClientError || error.code === "BAD_RESPONSE")) return false;
          return failureCount < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}
