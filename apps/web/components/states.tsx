"use client";

import { CircleAlert, Inbox, LockKeyhole, RefreshCw, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toApiError } from "@/lib/api/errors";
import { cn } from "cn";

export function RequestReference({ requestId }: { requestId: string | null | undefined }) {
  if (!requestId) return null;
  return (
    <p className="text-caption text-muted-foreground">
      Support reference: <span className="tabular select-all">{requestId}</span>
    </p>
  );
}

/** Inline error for forms and dialogs: the API's user-facing message plus the request id for support. */
export function InlineError({ error, title, className }: { error: unknown; title?: string; className?: string }) {
  if (!error) return null;
  const apiError = toApiError(error);
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-lg border border-l-4 border-l-destructive bg-card p-3 text-sm",
        className,
      )}
    >
      <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0 text-destructive" />
      <div className="min-w-0 space-y-1">
        {title ? <p className="font-semibold">{title}</p> : null}
        <p>{apiError.message}</p>
        <RequestReference requestId={apiError.requestId} />
      </div>
    </div>
  );
}

export function LoadingState({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-14 w-full rounded-lg" />
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed bg-card px-6 py-10 text-center">
      <Icon aria-hidden className="size-8 text-muted-foreground" />
      <div className="space-y-1">
        <p className="text-title font-semibold">{title}</p>
        {description ? <p className="max-w-prose text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

/** Full-section error with a retry, a plain-language message and the request id. 403 gets its own wording. */
export function ErrorState({ error, onRetry, what }: { error: unknown; onRetry?: () => void; what: string }) {
  const apiError = toApiError(error);
  if (apiError.code === "FORBIDDEN") return <ForbiddenState requestId={apiError.requestId} />;
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-l-4 border-l-destructive bg-card p-5">
      <div className="flex items-start gap-3">
        <CircleAlert aria-hidden className="mt-0.5 size-6 shrink-0 text-destructive" />
        <div className="space-y-1">
          <p className="text-title font-semibold">Couldn&apos;t load {what}</p>
          <p className="text-muted-foreground">{apiError.message}</p>
          <RequestReference requestId={apiError.requestId} />
        </div>
      </div>
      {onRetry ? (
        <Button variant="outline" onClick={onRetry}>
          <RefreshCw aria-hidden />
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function ForbiddenState({ requestId, message }: { requestId?: string | null; message?: string }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border bg-card p-5">
      <div className="flex items-start gap-3">
        <LockKeyhole aria-hidden className="mt-0.5 size-6 shrink-0 text-muted-foreground" />
        <div className="space-y-1">
          <p className="text-title font-semibold">You don&apos;t have access to this</p>
          <p className="text-muted-foreground">
            {message ?? "Your account isn't allowed to open this. If you need it, ask the clinic admin."}
          </p>
          <RequestReference requestId={requestId} />
        </div>
      </div>
      <Button variant="outline" asChild>
        <Link href="/">Go to today&apos;s schedule</Link>
      </Button>
    </div>
  );
}
