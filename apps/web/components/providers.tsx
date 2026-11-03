"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { ToastProvider } from "@/components/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { setUnauthenticatedHandler } from "@/lib/api/client";
import { loginUrlFor } from "@/lib/navigation";
import { makeQueryClient } from "@/lib/query";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);

  useEffect(() => {
    let redirecting = false;
    return setUnauthenticatedHandler(() => {
      if (redirecting || window.location.pathname === "/login") return;
      redirecting = true;
      queryClient.cancelQueries();
      queryClient.clear();
      // A full navigation (not router.push) also drops patient data kept in hidden, preserved routes.
      window.location.replace(loginUrlFor(window.location.pathname + window.location.search));
    });
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <ToastProvider>{children}</ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
