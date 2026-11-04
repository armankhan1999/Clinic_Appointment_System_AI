"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { ToastProvider } from "@/components/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { setSessionChangedHandler, setSessionUserSource, setUnauthenticatedHandler } from "@/lib/api/client";
import type { Session } from "@/lib/api/schemas";
import { loginUrlFor } from "@/lib/navigation";
import { makeQueryClient, queryKeys } from "@/lib/query";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);

  useEffect(() => {
    let leaving = false;
    // A full navigation (not router.push) also drops patient data kept in hidden, preserved routes.
    const leave = (target: () => void) => {
      if (leaving) return;
      leaving = true;
      void queryClient.cancelQueries();
      queryClient.clear();
      target();
    };

    const offUnauthenticated = setUnauthenticatedHandler(() => {
      if (window.location.pathname === "/login") return;
      leave(() => window.location.replace(loginUrlFor(window.location.pathname + window.location.search)));
    });
    // The user the app is showing, so a CSRF retry can tell when the cookie now belongs to someone else.
    const offSource = setSessionUserSource(() => queryClient.getQueryData<Session>(queryKeys.session)?.user.id ?? null);
    const offChanged = setSessionChangedHandler(() => leave(() => window.location.reload()));

    return () => {
      offUnauthenticated();
      offSource();
      offChanged();
    };
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <ToastProvider>{children}</ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
