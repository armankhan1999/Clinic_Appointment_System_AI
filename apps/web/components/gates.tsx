"use client";

import { LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { ErrorState, ForbiddenState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/errors";
import { useSession } from "@/lib/session";

/** Loads the session once for all staff pages. proxy.ts only checks that a cookie exists. */
export function StaffGate({ children }: { children: ReactNode }) {
  const session = useSession();

  if (session.isPending) {
    return (
      <div role="status" aria-live="polite" className="mx-auto flex max-w-6xl flex-col gap-4 p-8">
        <span className="sr-only">Loading your session</span>
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (session.isError) {
    if (isApiError(session.error) && session.error.status === 401) {
      return (
        <p role="status" className="flex items-center gap-2 p-8 text-muted-foreground">
          <LoaderCircle aria-hidden className="size-5 animate-spin" />
          Your session has ended. Taking you to the sign-in page…
        </p>
      );
    }
    return (
      <div className="mx-auto max-w-xl p-8">
        <ErrorState what="your account" error={session.error} onRetry={() => session.refetch()} />
      </div>
    );
  }

  return <AppShell user={session.data.user}>{children}</AppShell>;
}

/** Hides admin screens from receptionists (E6-S1-AC4). The API is the real enforcement point. */
export function AdminGate({ children }: { children: ReactNode }) {
  const session = useSession();
  if (session.data?.user.role !== "admin") {
    return <ForbiddenState message="This page is for clinic admins. Ask an admin if you need something changed here." />;
  }
  return <>{children}</>;
}
