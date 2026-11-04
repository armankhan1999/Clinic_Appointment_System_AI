import { CalendarDays } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { LoginForm } from "@/features/auth/login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <span aria-hidden className="grid size-11 place-items-center rounded-lg bg-primary text-primary-foreground">
            <CalendarDays className="size-6" />
          </span>
          <div>
            <h1 className="text-heading font-bold">Sign in to Front Desk</h1>
            <p className="text-body-sm text-muted-foreground">For clinic staff only</p>
          </div>
        </div>
        <div className="rounded-xl border bg-card p-6 shadow-[var(--shadow-panel)]">
          <Suspense fallback={<Skeleton className="h-64 w-full" />}>
            <LoginForm />
          </Suspense>
        </div>
        <p className="mt-6 text-caption text-muted-foreground">
          Forgot your password or locked out? Ask the clinic admin to unlock your account.
        </p>
      </div>
    </main>
  );
}
