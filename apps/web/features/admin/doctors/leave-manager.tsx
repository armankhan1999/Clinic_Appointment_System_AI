"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarOff, LoaderCircle, Search, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState, InlineError, LoadingState } from "@/components/states";
import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { createLeave, deleteLeave, getLeaves, previewLeave } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { appointmentSchema, type Appointment, type Leave } from "@/lib/api/schemas";
import { formatLongDate, todayIso } from "@/lib/dates";
import { queryKeys } from "@/lib/query";
import { LEAVE_REASON_MAX, leaveFormSchema, type LeaveForm } from "@/lib/validation/forms";

type Review = { date: string; reason: string; affected: Appointment[] };

const affectedFromConflict = z.object({ affected: z.array(appointmentSchema) });

function AffectedList({ appointments }: { appointments: Appointment[] }) {
  return (
    <ul className="divide-y rounded-lg border bg-card">
      {appointments.map((a) => (
        <li key={a.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-3 py-2">
          <span className="w-20 font-bold tabular">{a.time_label}</span>
          <span className="font-semibold">{a.patient.full_name}</span>
          <span className="tabular text-body-sm text-muted-foreground">{a.patient.phone ?? "No phone on file"}</span>
          <span className="tabular text-caption text-muted-foreground">{a.reference}</span>
        </li>
      ))}
    </ul>
  );
}

/** Leave days with a preview of affected bookings and an explicit confirm step (E6-S3-AC3, E4-S4). */
export function LeaveManager({ doctorId, doctorName }: { doctorId: string; doctorName: string }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const today = todayIso();
  const [review, setReview] = useState<Review | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [removing, setRemoving] = useState<Leave | null>(null);

  const leaves = useQuery({
    queryKey: queryKeys.leaves(doctorId),
    queryFn: ({ signal }) => getLeaves(doctorId, signal),
  });

  const form = useForm<LeaveForm>({ resolver: zodResolver(leaveFormSchema), defaultValues: { date: "", reason: "" } });

  const preview = useMutation({
    mutationFn: (values: LeaveForm) => previewLeave(doctorId, values.date),
    onSuccess: (result, values) => {
      setAcknowledged(false);
      setReview({ date: values.date, reason: values.reason.trim(), affected: result.affected });
    },
  });

  const create = useMutation({
    mutationFn: (input: Review) =>
      createLeave(doctorId, { date: input.date, reason: input.reason, confirm_affected: input.affected.length > 0 }),
    onSuccess: async (result) => {
      const count = result.cancelled.length;
      notify({
        tone: "success",
        title: "Leave added",
        description:
          count > 0
            ? `${formatLongDate(result.leave.date)}: ${count} appointment${count === 1 ? "" : "s"} cancelled. Patients on Telegram get a notice.`
            : formatLongDate(result.leave.date),
      });
      setReview(null);
      form.reset({ date: "", reason: "" });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.leaves(doctorId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.scheduleAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.attention }),
        queryClient.invalidateQueries({ queryKey: queryKeys.availabilityAll }),
      ]);
    },
    onError: (error, input) => {
      // A booking arrived after the preview: show the new list and ask again.
      if (isApiError(error) && error.code === "CONFLICT") {
        const parsed = affectedFromConflict.safeParse(error.details);
        if (parsed.success) {
          setAcknowledged(false);
          setReview({ ...input, affected: parsed.data.affected });
          create.reset();
        }
      }
    },
  });

  const remove = useMutation({
    mutationFn: (leave: Leave) => deleteLeave(doctorId, leave.id),
    onSuccess: async () => {
      notify({ tone: "success", title: "Leave removed", description: "Patients can book this day again." });
      setRemoving(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.leaves(doctorId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.availabilityAll }),
      ]);
    },
  });

  const errors = form.formState.errors;
  const sorted = [...(leaves.data?.items ?? [])].sort((a, b) => a.date.localeCompare(b.date));
  const upcoming = sorted.filter((l) => l.date >= today);
  const past = sorted.filter((l) => l.date < today);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section aria-labelledby="add-leave" className="space-y-4 rounded-xl border bg-card p-5">
        <h3 id="add-leave" className="text-title font-bold">
          Add a leave day
        </h3>

        {review === null ? (
          <form noValidate onSubmit={form.handleSubmit((values) => preview.mutate(values))} className="space-y-4">
            <FieldGroup>
              <Field data-invalid={!!errors.date}>
                <FieldLabel htmlFor="leave-date">Day off</FieldLabel>
                <Input id="leave-date" type="date" min={today} aria-invalid={!!errors.date} {...form.register("date")} />
                <FieldError errors={[errors.date]} />
              </Field>
              <Field data-invalid={!!errors.reason}>
                <FieldLabel htmlFor="leave-reason">Reason (optional, sent to affected patients)</FieldLabel>
                <Input id="leave-reason" maxLength={LEAVE_REASON_MAX} placeholder="For example: Attending a conference" {...form.register("reason")} />
                <FieldDescription>Up to {LEAVE_REASON_MAX} characters.</FieldDescription>
                <FieldError errors={[errors.reason]} />
              </Field>
            </FieldGroup>
            <InlineError error={preview.error} />
            <Button type="submit" disabled={preview.isPending}>
              {preview.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <Search aria-hidden />}
              Check bookings on this day
            </Button>
          </form>
        ) : (
          <div className="space-y-4">
            <p className="text-title">
              {doctorName} off on <span className="font-bold">{formatLongDate(review.date)}</span>
            </p>
            {review.affected.length === 0 ? (
              <p className="text-muted-foreground">No booked appointments on this day, so nobody needs to be told.</p>
            ) : (
              <div role="alert" className="space-y-3 rounded-lg border border-l-4 border-l-status-attention-edge bg-status-attention-bg p-3">
                <p className="flex items-center gap-2 font-semibold text-status-attention">
                  <TriangleAlert aria-hidden className="size-5" />
                  {review.affected.length} booked appointment{review.affected.length === 1 ? "" : "s"} will be cancelled
                </p>
                <p className="text-body-sm">
                  Patients who use Telegram get a message with the reason and a button to rebook. Call the others.
                </p>
                <AffectedList appointments={review.affected} />
                <Field orientation="horizontal">
                  <Checkbox id="confirm-affected" checked={acknowledged} onCheckedChange={(v) => setAcknowledged(v === true)} />
                  <FieldLabel htmlFor="confirm-affected">
                    I understand these {review.affected.length} appointment{review.affected.length === 1 ? "" : "s"} will be cancelled
                  </FieldLabel>
                </Field>
              </div>
            )}
            <InlineError error={create.error} title="The leave was not added" />
            <div className="flex flex-wrap gap-2">
              <Button
                variant={review.affected.length > 0 ? "destructive" : "default"}
                className={review.affected.length > 0 ? "bg-destructive text-destructive-foreground hover:bg-destructive/90" : undefined}
                disabled={create.isPending || (review.affected.length > 0 && !acknowledged)}
                onClick={() => create.mutate(review)}
              >
                {create.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <CalendarOff aria-hidden />}
                {review.affected.length > 0
                  ? `Cancel ${review.affected.length} appointment${review.affected.length === 1 ? "" : "s"} and add leave`
                  : "Add leave"}
              </Button>
              <Button
                variant="outline"
                disabled={create.isPending}
                onClick={() => {
                  setReview(null);
                  create.reset();
                }}
              >
                Change the day
              </Button>
            </div>
          </div>
        )}
      </section>

      <section aria-labelledby="leave-list" className="space-y-3">
        <h3 id="leave-list" className="text-title font-bold">
          Upcoming leave
        </h3>
        {leaves.isPending ? (
          <LoadingState label="Loading leave days" rows={2} />
        ) : leaves.isError ? (
          <ErrorState what="leave days" error={leaves.error} onRetry={() => leaves.refetch()} />
        ) : upcoming.length === 0 ? (
          <EmptyState icon={CalendarOff} title="No upcoming leave" description={`${doctorName} is available on all working days.`} />
        ) : (
          <ul className="divide-y rounded-xl border bg-card">
            {upcoming.map((leave) => (
              <li key={leave.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <div>
                  <p className="font-semibold">{formatLongDate(leave.date)}</p>
                  {leave.reason ? <p className="text-body-sm text-muted-foreground">{leave.reason}</p> : null}
                </div>
                <Button variant="ghost" size="sm" aria-label={`Remove leave on ${formatLongDate(leave.date)}`} onClick={() => setRemoving(leave)}>
                  <Trash2 aria-hidden />
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
        {past.length > 0 ? (
          <p className="text-caption text-muted-foreground">{past.length} past leave day{past.length === 1 ? "" : "s"} not shown.</p>
        ) : null}
      </section>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRemoving(null);
            remove.reset();
          }
        }}
        title="Remove this leave day?"
        description={
          <p>
            {removing ? formatLongDate(removing.date) : ""}: patients can book {doctorName} on this day again. Appointments
            already cancelled for this leave stay cancelled.
          </p>
        }
        confirmLabel="Remove leave"
        destructive
        pending={remove.isPending}
        error={remove.error}
        onConfirm={() => (removing ? remove.mutate(removing) : undefined)}
      />
    </div>
  );
}
