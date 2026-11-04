"use client";

import { CircleAlert, CircleHelp, Inbox, LockKeyhole, RefreshCw, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isOutcomeUnknown, toApiError } from "@/lib/api/errors";
import { cn } from "cn";

export function RequestReference({ requestId }: { requestId: string | null | undefined }) {
  if (!requestId) return null;
  return (
    <p className="text-caption text-muted-foreground">
      Support reference: <span className="tabular select-all">{requestId}</span>
    </p>
  );
}

export type UnknownOutcomeCopy = { title: string; hint: ReactNode };

/**
 * Inline error for forms and dialogs: the API's user-facing message plus the request id for support.
 * When a write got no answer at all (timeout or dropped connection) it may still have happened, so
 * a "was not saved" title would be wrong: say the outcome is unknown and what to check instead.
 */
export function InlineError({
  error,
  title,
  className,
  unknownOutcome,
  fieldsMarked = false,
}: {
  error: unknown;
  title?: string;
  className?: string;
  unknownOutcome?: UnknownOutcomeCopy;
  /** True when the form already marked the fields a 422 named; replaces the API's technical field list. */
  fieldsMarked?: boolean;
}) {
  if (!error) return null;
  const apiError = toApiError(error);
  if (isOutcomeUnknown(error)) {
    return (
      <div
        role="alert"
        className={cn("flex gap-3 rounded-lg border border-l-4 border-l-status-attention-edge bg-status-attention-bg p-3 text-sm", className)}
      >
        <CircleHelp aria-hidden className="mt-0.5 size-5 shrink-0 text-status-attention" />
        <div className="min-w-0 space-y-1">
          <p className="font-semibold">{unknownOutcome?.title ?? "We couldn't confirm whether this was saved"}</p>
          <p>The connection dropped before the clinic server answered, so it may have gone through.</p>
          <div>{unknownOutcome?.hint ?? "Check the list before trying again."}</div>
        </div>
      </div>
    );
  }
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
        <p>{fieldsMarked ? "Some details weren't accepted. Check the marked fields." : apiError.message}</p>
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

/**
 * Non-blocking notice for a failed background refresh while earlier data is still on screen.
 * The content (and anything typed into it) stays; only a first load that failed gets ErrorState.
 */
export function StaleDataNotice({ error, onRetry, what }: { error: unknown; onRetry?: () => void; what: string }) {
  const apiError = toApiError(error);
  return (
    <div
      role="status"
      className="flex flex-col gap-2 rounded-lg border border-l-4 border-l-status-attention-edge bg-status-attention-bg px-4 py-3 text-body-sm text-status-attention sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="space-y-0.5">
        <p className="font-semibold">Couldn&apos;t refresh {what}. Showing what was loaded earlier.</p>
        <p>{apiError.message}</p>
        <RequestReference requestId={apiError.requestId} />
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" className="shrink-0 bg-card" onClick={onRetry}>
          <RefreshCw aria-hidden />
          Try again
        </Button>
      ) : null}
    </div>
  );
}

/** For a query result: the blocking error only when nothing was ever loaded. */
export function RefetchNotice({
  query,
  what,
}: {
  query: { isRefetchError: boolean; error: unknown; refetch: () => unknown };
  what: string;
}) {
  if (!query.isRefetchError) return null;
  return <StaleDataNotice what={what} error={query.error} onRetry={() => void query.refetch()} />;
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
