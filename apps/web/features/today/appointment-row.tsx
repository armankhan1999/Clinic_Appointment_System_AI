"use client";

import { ChevronDown, CircleCheck, CircleX, PhoneCall, UserX } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  AttentionPill,
  ConfirmedPill,
  ReminderPill,
  SourcePill,
  STATUS_EDGE,
  StatusPill,
  attentionReasonText,
} from "@/components/status";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import type { Appointment, PatientRef } from "@/lib/api/schemas";
import { CANCEL_REASON_MAX, cancelSchema } from "@/lib/validation/forms";
import { cn } from "cn";

import { useDayActions } from "./use-day-actions";

type DialogKind = "cancel" | "completed" | "no_show" | "clear" | null;

export function PatientContact({ patient }: { patient: PatientRef }) {
  return (
    <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <span className="font-semibold">{patient.full_name}</span>
      {patient.phone ? (
        <a href={`tel:${patient.phone.replace(/[^\d+]/g, "")}`} className="tabular text-body-sm text-muted-foreground underline-offset-4 hover:underline">
          {patient.phone}
        </a>
      ) : (
        <span className="text-body-sm text-muted-foreground">No phone on file</span>
      )}
    </span>
  );
}

export function AppointmentRow({ appointment, isAdmin }: { appointment: Appointment; isAdmin: boolean }) {
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const actions = useDayActions();
  const a = appointment;
  const cancelled = a.status === "cancelled";
  const marked = a.status === "completed" || a.status === "no_show";

  const close = () => {
    setDialog(null);
    setReason("");
    setReasonError(null);
    actions.cancel.reset();
    actions.attendance.reset();
    actions.clear.reset();
  };

  const submitCancel = () => {
    const parsed = cancelSchema.safeParse({ reason });
    if (!parsed.success) {
      setReasonError(parsed.error.issues[0]?.message ?? "Enter a reason");
      return;
    }
    setReasonError(null);
    actions.cancel.mutate({ id: a.id, reason: parsed.data.reason }, { onSuccess: close });
  };

  const markAs = (status: "completed" | "no_show") => actions.attendance.mutate({ id: a.id, status }, { onSuccess: close });

  const canChangeMark = isAdmin && marked;
  const hasActions = a.status === "booked" || canChangeMark || a.staff_attention !== null;
  const who = `${a.patient.full_name} at ${a.time_label}`;

  return (
    <li
      className={cn(
        "grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-4 gap-y-3 border-l-4 bg-card px-4 py-3 md:grid-cols-[6.5rem_minmax(0,1fr)_auto] md:items-start",
        STATUS_EDGE[a.status],
        a.staff_attention && "bg-status-attention-bg/50",
      )}
    >
      <div className="flex flex-col">
        <time dateTime={a.start} className={cn("text-slot font-bold", cancelled && "text-muted-foreground line-through")}>
          {a.time_label}
        </time>
        <span className="tabular text-caption text-muted-foreground">{a.reference}</span>
      </div>

      <div className="min-w-0 space-y-2">
        <PatientContact patient={a.patient} />
        <div className="flex flex-wrap gap-1.5">
          <StatusPill status={a.status} />
          <SourcePill source={a.source} />
          {a.patient_confirmed ? <ConfirmedPill /> : null}
          {a.staff_attention ? <AttentionPill /> : null}
          {!cancelled ? (
            <>
              <ReminderPill window="24h" status={a.reminders["24h"]} />
              <ReminderPill window="2h" status={a.reminders["2h"]} />
            </>
          ) : null}
        </div>
        {a.staff_attention ? (
          <p className="text-body-sm text-status-attention">
            <PhoneCall aria-hidden className="mr-1 inline size-4 align-text-bottom" />
            Call the patient: {attentionReasonText(a.staff_attention.reason)}
          </p>
        ) : null}
      </div>

      {hasActions ? (
        <div className="col-span-2 flex md:col-span-1 md:justify-end">
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" aria-label={`Actions for ${who}`}>
                Actions
                <ChevronDown aria-hidden data-icon="inline-end" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              {a.status === "booked" ? (
                <>
                  {!a.can_mark_attendance ? (
                    <DropdownMenuLabel className="text-caption font-normal text-muted-foreground">
                      Completed and no-show can be marked once the appointment time has started.
                    </DropdownMenuLabel>
                  ) : null}
                  <DropdownMenuItem disabled={!a.can_mark_attendance} onSelect={() => setDialog("completed")}>
                    <CircleCheck aria-hidden />
                    Mark completed
                  </DropdownMenuItem>
                  <DropdownMenuItem disabled={!a.can_mark_attendance} onSelect={() => setDialog("no_show")}>
                    <UserX aria-hidden />
                    Mark no-show
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" onSelect={() => setDialog("cancel")}>
                    <CircleX aria-hidden />
                    Cancel appointment…
                  </DropdownMenuItem>
                </>
              ) : null}
              {canChangeMark ? (
                <DropdownMenuItem onSelect={() => setDialog(a.status === "completed" ? "no_show" : "completed")}>
                  {a.status === "completed" ? <UserX aria-hidden /> : <CircleCheck aria-hidden />}
                  {a.status === "completed" ? "Change to no-show" : "Change to completed"}
                </DropdownMenuItem>
              ) : null}
              {a.staff_attention ? (
                <>
                  {a.status === "booked" || canChangeMark ? <DropdownMenuSeparator /> : null}
                  <DropdownMenuItem onSelect={() => setDialog("clear")}>
                    <PhoneCall aria-hidden />
                    Clear call flag
                  </DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ) : null}

      <ConfirmDialog
        open={dialog === "cancel"}
        onOpenChange={(open) => (!open ? close() : undefined)}
        title="Cancel this appointment?"
        description={
          <>
            <p>
              {a.patient.full_name}, {a.time_label} with {a.doctor_name}. This can&apos;t be undone; the slot becomes free
              for others to book.
            </p>
            <p>If the patient uses the Telegram assistant, they get a message with your reason.</p>
          </>
        }
        confirmLabel="Cancel appointment"
        cancelLabel="Keep appointment"
        destructive
        pending={actions.cancel.isPending}
        error={actions.cancel.error}
        onConfirm={submitCancel}
      >
        <Field data-invalid={!!reasonError}>
          <FieldLabel htmlFor={`cancel-reason-${a.id}`}>Reason for the patient</FieldLabel>
          <Textarea
            id={`cancel-reason-${a.id}`}
            value={reason}
            maxLength={CANCEL_REASON_MAX}
            aria-invalid={!!reasonError}
            aria-describedby={`cancel-reason-${a.id}-help`}
            onChange={(e) => setReason(e.target.value)}
            placeholder="For example: Doctor is unwell today"
          />
          <FieldDescription id={`cancel-reason-${a.id}-help`}>
            {reason.trim().length}/{CANCEL_REASON_MAX} characters
          </FieldDescription>
          <FieldError>{reasonError}</FieldError>
        </Field>
      </ConfirmDialog>

      <ConfirmDialog
        open={dialog === "completed" || dialog === "no_show"}
        onOpenChange={(open) => (!open ? close() : undefined)}
        title={dialog === "no_show" ? "Mark as no-show?" : "Mark as completed?"}
        description={
          <p>
            {a.patient.full_name}, {a.time_label} with {a.doctor_name}.{" "}
            {isAdmin ? "You can change this later." : "Only a clinic admin can change this afterwards."}
          </p>
        }
        confirmLabel={dialog === "no_show" ? "Mark no-show" : "Mark completed"}
        pending={actions.attendance.isPending}
        error={actions.attendance.error}
        onConfirm={() => (dialog === "completed" || dialog === "no_show" ? markAs(dialog) : undefined)}
      />

      <ConfirmDialog
        open={dialog === "clear"}
        onOpenChange={(open) => (!open ? close() : undefined)}
        title="Clear the call flag?"
        description={<p>Do this after you have spoken to {a.patient.full_name}. The flag disappears for everyone.</p>}
        confirmLabel="Clear flag"
        pending={actions.clear.isPending}
        error={actions.clear.error}
        onConfirm={() => actions.clear.mutate(a.id, { onSuccess: close })}
      />
    </li>
  );
}
