"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleCheck, HeartPulse, MessageCircleQuestion, PhoneCall, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, RefetchNotice } from "@/components/states";
import { attentionReasonText, ticketReasonText } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getAttention } from "@/lib/api/endpoints";
import type { Appointment, EmergencyAlert, Ticket } from "@/lib/api/schemas";
import { formatRelative, formatShortDate, formatUtcTimestamp } from "@/lib/dates";
import { LIVE_REFRESH_MS, queryKeys } from "@/lib/query";
import { cn } from "@/lib/utils";

import { PatientContact } from "./appointment-row";
import { useDayActions } from "./use-day-actions";

type Pending =
  | { kind: "alert"; item: EmergencyAlert }
  | { kind: "ticket"; item: Ticket }
  | { kind: "flag"; item: Appointment }
  | null;

function Received({ at, verb = "Received" }: { at: string; verb?: string }) {
  return (
    <time dateTime={at} title={formatUtcTimestamp(at)} className="text-caption text-muted-foreground">
      {verb} {formatRelative(at)}
    </time>
  );
}

function Item({
  icon: Icon,
  tone,
  title,
  children,
  action,
}: {
  icon: LucideIcon;
  tone: "emergency" | "attention";
  title: string;
  children: ReactNode;
  action: ReactNode;
}) {
  return (
    <li
      className={cn(
        "flex flex-col gap-3 rounded-lg border border-l-4 bg-card p-3 sm:flex-row sm:items-center sm:justify-between",
        tone === "emergency" ? "border-l-status-emergency-edge bg-status-emergency-bg" : "border-l-status-attention-edge",
      )}
    >
      <div className="flex min-w-0 gap-3">
        <Icon
          aria-hidden
          className={cn("mt-0.5 size-5 shrink-0", tone === "emergency" ? "text-status-emergency" : "text-status-attention")}
        />
        <div className="min-w-0 space-y-1">
          <p className={cn("font-semibold", tone === "emergency" && "text-status-emergency")}>{title}</p>
          {children}
        </div>
      </div>
      <div className="shrink-0">{action}</div>
    </li>
  );
}

/** Open tickets, unacknowledged emergency alerts and flagged appointments, highlighted at the top (E6-S2-AC3). */
export function AttentionPanel() {
  const query = useQuery({
    queryKey: queryKeys.attention,
    queryFn: ({ signal }) => getAttention(signal),
    refetchInterval: LIVE_REFRESH_MS,
  });
  const actions = useDayActions();
  const [pending, setPending] = useState<Pending>(null);

  const close = () => {
    setPending(null);
    actions.acknowledge.reset();
    actions.resolve.reset();
    actions.clear.reset();
  };

  if (query.isPending) {
    return (
      <div role="status" aria-live="polite">
        <span className="sr-only">Checking for items that need attention</span>
        <Skeleton className="h-20 w-full rounded-xl" />
      </div>
    );
  }

  if (query.isLoadingError) {
    // Never fail silently here: this panel is where emergency alerts appear.
    return <ErrorState what="emergency alerts and help requests" error={query.error} onRetry={() => query.refetch()} />;
  }

  const { alerts, tickets, flagged } = query.data;
  const total = alerts.length + tickets.length + flagged.length;
  // A failed refresh keeps the last list visible and says so; new alerts may be missing from it.
  const refreshProblem = <RefetchNotice query={query} what="emergency alerts and help requests" />;

  if (total === 0) {
    // "Nothing needs attention" would be false reassurance if the last refresh failed.
    return query.isRefetchError ? (
      refreshProblem
    ) : (
      <p role="status" className="flex items-center gap-2 rounded-lg border bg-card px-4 py-3 text-muted-foreground">
        <CircleCheck aria-hidden className="size-5 text-status-booked" />
        Nothing needs attention right now. Emergency alerts and help requests will show up here.
      </p>
    );
  }

  const mutation =
    pending?.kind === "alert" ? actions.acknowledge : pending?.kind === "ticket" ? actions.resolve : actions.clear;

  return (
    <section
      aria-labelledby="attention-heading"
      className="space-y-3 rounded-xl border border-status-attention-edge/50 bg-status-attention-bg/60 p-4"
    >
      {refreshProblem}
      <h2 id="attention-heading" className="flex items-center gap-2 text-title font-bold">
        Needs attention
        <span className="rounded-full bg-card px-2 text-body-sm tabular">{total}</span>
      </h2>
      <ul className="space-y-2">
        {alerts.map((alert) => (
          <Item
            key={`alert-${alert.id}`}
            icon={HeartPulse}
            tone="emergency"
            title="Emergency message: contact the patient now"
            action={
              <Button onClick={() => setPending({ kind: "alert", item: alert })}>Acknowledge</Button>
            }
          >
            {alert.patient ? (
              <PatientContact patient={alert.patient} />
            ) : (
              <p>
                Unregistered Telegram user
                {alert.telegram_user_id !== null ? (
                  <span className="tabular text-muted-foreground"> (Telegram ID {alert.telegram_user_id})</span>
                ) : null}
              </p>
            )}
            <Received at={alert.created_at} />
          </Item>
        ))}

        {tickets.map((ticket) => (
          <Item
            key={`ticket-${ticket.id}`}
            icon={MessageCircleQuestion}
            tone="attention"
            title={ticketReasonText(ticket.reason)}
            action={
              <Button variant="outline" onClick={() => setPending({ kind: "ticket", item: ticket })}>
                Resolve
              </Button>
            }
          >
            <PatientContact patient={ticket.patient} />
            <Received at={ticket.created_at} verb="Asked" />
          </Item>
        ))}

        {flagged.map((apt) => (
          <Item
            key={`flag-${apt.id}`}
            icon={PhoneCall}
            tone="attention"
            title={`Call about ${apt.time_label}, ${formatShortDate(apt.date)} with ${apt.doctor_name}`}
            action={
              <Button variant="outline" onClick={() => setPending({ kind: "flag", item: apt })}>
                Clear attention
              </Button>
            }
          >
            <PatientContact patient={apt.patient} />
            <p className="text-body-sm">{attentionReasonText(apt.staff_attention?.reason ?? "")}</p>
            {apt.staff_attention ? <Received at={apt.staff_attention.at} verb="Flagged" /> : null}
          </Item>
        ))}
      </ul>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => (!open ? close() : undefined)}
        title={
          pending?.kind === "alert"
            ? "Acknowledge this emergency alert?"
            : pending?.kind === "ticket"
              ? "Mark this request as resolved?"
              : "Clear the call flag?"
        }
        description={
          pending?.kind === "alert" ? (
            <p>Only acknowledge once someone has contacted the patient or confirmed they are getting help. The alert leaves this list for everyone.</p>
          ) : pending?.kind === "ticket" ? (
            <p>Do this once the patient&apos;s question is handled. Your name is saved as the person who resolved it.</p>
          ) : (
            <p>Do this after you have spoken to the patient. The flag disappears for everyone.</p>
          )
        }
        confirmLabel={pending?.kind === "alert" ? "Acknowledge" : pending?.kind === "ticket" ? "Resolve" : "Clear flag"}
        pending={mutation.isPending}
        error={mutation.error}
        unknownOutcome={{
          title: "We couldn't confirm whether this was saved",
          hint: "Check the attention list before trying again. It is refreshing now.",
        }}
        onConfirm={() => {
          if (!pending) return;
          mutation.mutate(pending.item.id, { onSuccess: close });
        }}
      />
    </section>
  );
}
