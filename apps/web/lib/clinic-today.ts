"use client";

import { useQuery } from "@tanstack/react-query";

import { getClinicToday } from "@/lib/api/endpoints";
import { todayIso } from "@/lib/dates";
import { queryKeys } from "@/lib/query";

const ONE_MINUTE_MS = 60_000;

/**
 * Today's date in the clinic's time zone, as the API reports it, so a PC set to another zone (or a wrong
 * clock) cannot shift the schedule, booking dates or the metrics week. The PC's date is used only until
 * the first answer arrives.
 */
export function useClinicToday(): string {
  const { data } = useQuery({
    queryKey: queryKeys.clinicToday,
    queryFn: ({ signal }) => getClinicToday(signal),
    staleTime: ONE_MINUTE_MS,
    refetchInterval: 5 * ONE_MINUTE_MS, // picks up the new day shortly after midnight
  });
  return data?.date ?? todayIso();
}
