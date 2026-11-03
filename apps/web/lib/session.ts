"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchSession } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/query";

/** The signed-in staff user and CSRF token, from GET /auth/me (cached for the tab's lifetime). */
export function useSession() {
  return useQuery({
    queryKey: queryKeys.session,
    queryFn: ({ signal }) => fetchSession(signal),
    staleTime: 5 * 60_000,
    retry: (count, error) => !(isApiError(error) && error.isClientError) && count < 2,
  });
}

/** Admin-only UI is hidden for receptionists; the API still enforces every role check. */
export function useIsAdmin(): boolean {
  const { data } = useSession();
  return data?.user.role === "admin";
}
