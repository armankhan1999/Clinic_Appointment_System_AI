"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Plus, Save, Trash2, Undo2 } from "lucide-react";
import { useEffect } from "react";
import {
  useFieldArray,
  useForm,
  useWatch,
  type Control,
  type FieldErrors,
  type UseFormRegister,
  type UseFormTrigger,
} from "react-hook-form";

import { ErrorState, InlineError, LoadingState, RefetchNotice } from "@/components/states";
import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getWeeklySchedule, saveWeeklySchedule } from "@/lib/api/endpoints";
import { queryKeys } from "@/lib/query";
import {
  MAX_SLOT_MINUTES,
  MIN_SLOT_MINUTES,
  WEEKDAYS,
  blocksToForm,
  emptyBlock,
  formToBlocks,
  leftoverMinutes,
  weeklyScheduleFormSchema,
  type WeeklyScheduleForm,
} from "@/lib/validation/schedule";
import { cn } from "cn";

function FieldMessage({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="text-body-sm text-destructive">
      {message}
    </p>
  );
}

function DayEditor({
  dayIndex,
  control,
  register,
  errors,
  trigger,
}: {
  dayIndex: number;
  control: Control<WeeklyScheduleForm>;
  register: UseFormRegister<WeeklyScheduleForm>;
  errors: FieldErrors<WeeklyScheduleForm>;
  trigger: UseFormTrigger<WeeklyScheduleForm>;
}) {
  const { fields, append, remove } = useFieldArray({ control, name: `days.${dayIndex}.blocks` });
  const blocks = useWatch({ control, name: `days.${dayIndex}.blocks` });
  const day = WEEKDAYS[dayIndex];
  const headingId = `day-${dayIndex}`;
  // An overlap error sits on the other block, so check the whole day whenever one field changes.
  const revalidateDay = () => void trigger(`days.${dayIndex}.blocks`);

  return (
    <section aria-labelledby={headingId} className="grid gap-3 border-b px-4 py-4 last:border-b-0 md:grid-cols-[9rem_1fr]">
      <div>
        <h3 id={headingId} className="font-bold">
          {day}
        </h3>
        <p className="text-caption text-muted-foreground">{fields.length === 0 ? "Not working" : `${fields.length} block${fields.length === 1 ? "" : "s"}`}</p>
      </div>
      <div className="space-y-3">
        {fields.map((field, blockIndex) => {
          const blockErrors = errors.days?.[dayIndex]?.blocks?.[blockIndex];
          const base = `d${dayIndex}-b${blockIndex}`;
          const leftover = blocks?.[blockIndex] ? leftoverMinutes(blocks[blockIndex]) : 0;
          return (
            <fieldset key={field.id} className="rounded-lg border bg-background/60 p-3">
              <legend className="sr-only">
                {day}, block {blockIndex + 1}
              </legend>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1">
                  <label htmlFor={`${base}-start`} className="text-body-sm font-medium">
                    Starts
                  </label>
                  <Input
                    id={`${base}-start`}
                    type="time"
                    className="w-32"
                    aria-invalid={!!blockErrors?.start}
                    aria-describedby={blockErrors?.start ? `${base}-start-error` : undefined}
                    {...register(`days.${dayIndex}.blocks.${blockIndex}.start`, { onBlur: revalidateDay })}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label htmlFor={`${base}-end`} className="text-body-sm font-medium">
                    Ends
                  </label>
                  <Input
                    id={`${base}-end`}
                    type="time"
                    className="w-32"
                    aria-invalid={!!blockErrors?.end}
                    aria-describedby={blockErrors?.end ? `${base}-end-error` : undefined}
                    {...register(`days.${dayIndex}.blocks.${blockIndex}.end`, { onBlur: revalidateDay })}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label htmlFor={`${base}-slot`} className="text-body-sm font-medium">
                    Slot length (minutes)
                  </label>
                  <Input
                    id={`${base}-slot`}
                    type="number"
                    inputMode="numeric"
                    min={MIN_SLOT_MINUTES}
                    max={MAX_SLOT_MINUTES}
                    step={5}
                    className="w-28"
                    aria-invalid={!!blockErrors?.slot_minutes}
                    aria-describedby={blockErrors?.slot_minutes ? `${base}-slot-error` : undefined}
                    {...register(`days.${dayIndex}.blocks.${blockIndex}.slot_minutes`, { valueAsNumber: true, onBlur: revalidateDay })}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  aria-label={`Remove ${day} block ${blockIndex + 1}`}
                  onClick={() => remove(blockIndex)}
                >
                  <Trash2 aria-hidden />
                  Remove
                </Button>
              </div>
              <div className="mt-2 space-y-1">
                <FieldMessage id={`${base}-start-error`} message={blockErrors?.start?.message} />
                <FieldMessage id={`${base}-end-error`} message={blockErrors?.end?.message} />
                <FieldMessage id={`${base}-slot-error`} message={blockErrors?.slot_minutes?.message} />
                {leftover > 0 && !blockErrors ? (
                  <p className="text-caption text-muted-foreground">
                    The last {leftover} minutes are too short for a full slot and won&apos;t be bookable.
                  </p>
                ) : null}
              </div>
            </fieldset>
          );
        })}
        <Button type="button" variant="outline" size="sm" onClick={() => append(emptyBlock())}>
          <Plus aria-hidden />
          {fields.length === 0 ? `Add hours on ${day}` : "Add another block"}
        </Button>
      </div>
    </section>
  );
}

/** Weekly hours editor (E6-S3-AC1/AC2). Breaks are the gaps between blocks. */
export function ScheduleEditor({ doctorId, doctorName }: { doctorId: string; doctorName: string }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const schedule = useQuery({
    queryKey: queryKeys.weeklySchedule(doctorId),
    queryFn: ({ signal }) => getWeeklySchedule(doctorId, signal),
    refetchOnWindowFocus: false,
  });

  const form = useForm<WeeklyScheduleForm>({
    resolver: zodResolver(weeklyScheduleFormSchema),
    defaultValues: blocksToForm([]),
    mode: "onBlur",
    reValidateMode: "onChange",
  });

  const loaded = schedule.data;
  useEffect(() => {
    // A later refresh must never overwrite hours the admin is still editing.
    if (loaded && !form.formState.isDirty) form.reset(blocksToForm(loaded.blocks));
  }, [loaded, form]);

  const { isDirty } = form.formState;
  useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isDirty]);

  const save = useMutation({
    mutationFn: (values: WeeklyScheduleForm) => saveWeeklySchedule(doctorId, formToBlocks(values)),
    onSuccess: async (saved) => {
      queryClient.setQueryData(queryKeys.weeklySchedule(doctorId), saved);
      form.reset(blocksToForm(saved.blocks));
      notify({ tone: "success", title: "Weekly hours saved", description: `New bookings for ${doctorName} use these hours.` });
      await queryClient.invalidateQueries({ queryKey: queryKeys.availabilityAll });
    },
  });

  if (schedule.isPending) return <LoadingState label="Loading weekly hours" rows={7} />;
  if (schedule.isLoadingError) return <ErrorState what="the weekly hours" error={schedule.error} onRetry={() => schedule.refetch()} />;

  const hasErrors = Object.keys(form.formState.errors).length > 0;

  return (
    <form noValidate onSubmit={form.handleSubmit((values) => save.mutate(values))} className="space-y-4">
      <RefetchNotice query={schedule} what="the weekly hours" />
      <p className="text-muted-foreground">
        Add one block per working stretch; a gap between blocks is a break. Slots must be {MIN_SLOT_MINUTES}–{MAX_SLOT_MINUTES} minutes (usually 15).
      </p>
      <div className="rounded-xl border bg-card">
        {WEEKDAYS.map((_, dayIndex) => (
          <DayEditor key={dayIndex} dayIndex={dayIndex} control={form.control} register={form.register}
            errors={form.formState.errors}
            trigger={form.trigger}
          />
        ))}
      </div>

      <div
        className={cn(
          "sticky bottom-0 z-10 -mx-1 space-y-3 rounded-xl border bg-card p-4 shadow-[var(--shadow-overlay)]",
          !isDirty && !save.error && "shadow-none",
        )}
      >
        {hasErrors ? (
          <p role="alert" className="text-body-sm text-destructive">
            Fix the highlighted times before saving.
          </p>
        ) : null}
        <InlineError error={save.error} title="The weekly hours were not saved" />
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!isDirty || save.isPending}>
            {save.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <Save aria-hidden />}
            Save weekly hours
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={!isDirty || save.isPending}
            onClick={() => {
              form.reset(blocksToForm(loaded?.blocks ?? []));
              save.reset();
            }}
          >
            <Undo2 aria-hidden />
            Discard changes
          </Button>
          <span className="text-body-sm text-muted-foreground" aria-live="polite">
            {isDirty ? "You have unsaved changes." : "All changes saved."}
          </span>
        </div>
      </div>
    </form>
  );
}
