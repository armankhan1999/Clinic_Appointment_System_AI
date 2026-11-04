"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Save, TriangleAlert, Undo2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useForm, useWatch, type FieldError as RhfFieldError } from "react-hook-form";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { ErrorState, InlineError, LoadingState, RefetchNotice } from "@/components/states";
import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { getSettings, updateSettings } from "@/lib/api/endpoints";
import { applyApiFieldErrors, matchApiFields } from "@/lib/api/field-errors";
import type { ClinicSettings } from "@/lib/api/schemas";
import { formatRelative, formatUtcTimestamp, toHourMinute } from "@/lib/dates";
import { queryKeys } from "@/lib/query";
import { parsePhrases, settingsFormSchema, type SettingsForm } from "@/lib/validation/forms";

const SETTINGS_API_FIELDS = {
  clinic_name: "clinic_name",
  phone: "phone",
  address: "address",
  staff_hours_text: "staff_hours_text",
  timezone: "timezone",
  emergency_number: "emergency_number",
  emergency_phrases: "emergencyPhrasesText",
  cutoff_minutes: "cutoff_minutes",
  booking_window_days: "booking_window_days",
  max_upcoming_per_patient: "max_upcoming_per_patient",
  max_per_doctor_per_day: "max_per_doctor_per_day",
  morning_end: "morning_end",
  afternoon_end: "afternoon_end",
} as const;

const NUMBER_FIELDS = ["cutoff_minutes", "booking_window_days", "max_upcoming_per_patient", "max_per_doctor_per_day"] as const;

function toForm(s: ClinicSettings): SettingsForm {
  return {
    clinic_name: s.clinic_name,
    phone: s.phone,
    address: s.address,
    staff_hours_text: s.staff_hours_text,
    timezone: s.timezone,
    emergency_number: s.emergency_number,
    emergencyPhrasesText: s.emergency_phrases.join("\n"),
    cutoff_minutes: s.cutoff_minutes,
    booking_window_days: s.booking_window_days,
    max_upcoming_per_patient: s.max_upcoming_per_patient,
    max_per_doctor_per_day: s.max_per_doctor_per_day,
    morning_end: toHourMinute(s.morning_end),
    afternoon_end: toHourMinute(s.afternoon_end),
  };
}

/** Only the fields the admin changed ("any subset of the clinic settings fields"). */
export function changedSettings(original: SettingsForm, values: SettingsForm): Partial<ClinicSettings> {
  const changes: Partial<ClinicSettings> = {};
  const textKeys = ["clinic_name", "phone", "address", "staff_hours_text", "timezone", "emergency_number", "morning_end", "afternoon_end"] as const;
  for (const key of textKeys) {
    const value = values[key].trim();
    if (value !== original[key].trim()) changes[key] = value;
  }
  for (const key of NUMBER_FIELDS) {
    if (values[key] !== original[key]) changes[key] = values[key];
  }
  const phrases = parsePhrases(values.emergencyPhrasesText);
  if (phrases.join("\n") !== parsePhrases(original.emergencyPhrasesText).join("\n")) changes.emergency_phrases = phrases;
  return changes;
}

function Group({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  const id = `settings-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="grid gap-4 border-b p-5 last:border-b-0 lg:grid-cols-[16rem_1fr]">
      <div className="space-y-1">
        <h2 id={id} className="text-title font-bold">
          {title}
        </h2>
        {description ? <p className="text-body-sm text-muted-foreground">{description}</p> : null}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function Row({ id, label, help, error, wide, children }: { id: string; label: string; help?: string; error?: RhfFieldError; wide?: boolean; children: ReactNode }) {
  return (
    <Field data-invalid={!!error} className={wide ? "sm:col-span-2" : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {children}
      {help ? <FieldDescription>{help}</FieldDescription> : null}
      <FieldError errors={[error]} />
    </Field>
  );
}

export function SettingsFormView() {
  const settings = useQuery({ queryKey: queryKeys.settings, queryFn: ({ signal }) => getSettings(signal), refetchOnWindowFocus: false });
  if (settings.isPending) return <LoadingState label="Loading clinic settings" rows={6} />;
  if (settings.isLoadingError) return <ErrorState what="clinic settings" error={settings.error} onRetry={() => settings.refetch()} />;
  return (
    <div className="space-y-4">
      <RefetchNotice query={settings} what="clinic settings" />
      <SettingsEditor settings={settings.data} />
    </div>
  );
}

function SettingsEditor({ settings }: { settings: ClinicSettings }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const original = useMemo(() => toForm(settings), [settings]);
  const form = useForm<SettingsForm>({ resolver: zodResolver(settingsFormSchema), defaultValues: original });
  const timezone = useWatch({ control: form.control, name: "timezone" });
  const timezones = useMemo(() => Intl.supportedValuesOf("timeZone"), []);

  const save = useMutation({
    mutationFn: (changes: Partial<ClinicSettings>) => updateSettings(changes),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.settings, saved);
      form.reset(toForm(saved));
      notify({ tone: "success", title: "Clinic settings saved" });
    },
    onError: (error) => applyApiFieldErrors(error, form.setError, SETTINGS_API_FIELDS),
  });

  // A time-zone change moves every slot and appointment label, so it is confirmed separately.
  const [timezoneChange, setTimezoneChange] = useState<Partial<ClinicSettings> | null>(null);

  const e = form.formState.errors;
  const { isDirty } = form.formState;
  const onSubmit = form.handleSubmit((values) => {
    const changes = changedSettings(original, values);
    if (Object.keys(changes).length === 0) {
      form.reset(original);
      return;
    }
    if (changes.timezone !== undefined) {
      setTimezoneChange(changes);
      return;
    }
    save.mutate(changes);
  });

  return (
    <form noValidate onSubmit={onSubmit} className="space-y-4">
      <ConfirmDialog
        open={timezoneChange !== null}
        onOpenChange={(open) => {
          if (!open) {
            setTimezoneChange(null);
            save.reset();
          }
        }}
        title={`Change the clinic time zone to ${timezoneChange?.timezone ?? ""}?`}
        description={
          <>
            <p>
              Free slots will be worked out in the new time zone. Existing appointments are stored as a moment in time and keep
              it, so the times shown for them will change.
            </p>
            <p>Only do this if the clinic&apos;s location really changed.</p>
          </>
        }
        confirmLabel="Change time zone"
        cancelLabel={`Keep ${original.timezone}`}
        destructive
        pending={save.isPending}
        error={save.error}
        onConfirm={() => (timezoneChange ? save.mutate(timezoneChange, { onSuccess: () => setTimezoneChange(null) }) : undefined)}
      />
      <div className="rounded-xl border bg-card">
        <Group title="Clinic details" description="Shown to patients by the Telegram assistant.">
          <Row id="clinic_name" label="Clinic name" error={e.clinic_name}>
            <Input id="clinic_name" aria-invalid={!!e.clinic_name} {...form.register("clinic_name")} />
          </Row>
          <Row id="phone" label="Clinic phone" error={e.phone}>
            <Input id="phone" type="tel" aria-invalid={!!e.phone} {...form.register("phone")} />
          </Row>
          <Row id="address" label="Address" error={e.address} wide>
            <Textarea id="address" rows={2} aria-invalid={!!e.address} {...form.register("address")} />
          </Row>
          <Row id="staff_hours_text" label="Front desk hours" help="As patients should read it, e.g. Mon–Sat 9 AM–6 PM." error={e.staff_hours_text} wide>
            <Input id="staff_hours_text" aria-invalid={!!e.staff_hours_text} {...form.register("staff_hours_text")} />
          </Row>
        </Group>

        <Group title="Emergencies" description="Messages containing these phrases get the fixed emergency reply and an alert on the Today screen.">
          <Row id="emergency_number" label="Emergency number" error={e.emergency_number}>
            <Input id="emergency_number" type="tel" aria-invalid={!!e.emergency_number} {...form.register("emergency_number")} />
          </Row>
          <Row id="emergencyPhrasesText" label="Emergency phrases" help="One phrase per line." error={e.emergencyPhrasesText} wide>
            <Textarea id="emergencyPhrasesText" rows={5} {...form.register("emergencyPhrasesText")} />
          </Row>
        </Group>

        <Group title="Booking rules" description="Limits for bookings made through the Telegram assistant.">
          <Row id="cutoff_minutes" label="Online cut-off (minutes before the appointment)" error={e.cutoff_minutes}>
            <Input id="cutoff_minutes" type="number" inputMode="numeric" min={0} aria-invalid={!!e.cutoff_minutes} {...form.register("cutoff_minutes", { valueAsNumber: true })} />
          </Row>
          <Row id="booking_window_days" label="How far ahead patients can book (days)" error={e.booking_window_days}>
            <Input id="booking_window_days" type="number" inputMode="numeric" min={1} aria-invalid={!!e.booking_window_days} {...form.register("booking_window_days", { valueAsNumber: true })} />
          </Row>
          <Row id="max_upcoming_per_patient" label="Upcoming appointments per patient" error={e.max_upcoming_per_patient}>
            <Input id="max_upcoming_per_patient" type="number" inputMode="numeric" min={1} aria-invalid={!!e.max_upcoming_per_patient} {...form.register("max_upcoming_per_patient", { valueAsNumber: true })} />
          </Row>
          <Row id="max_per_doctor_per_day" label="Appointments per patient with one doctor per day" error={e.max_per_doctor_per_day}>
            <Input id="max_per_doctor_per_day" type="number" inputMode="numeric" min={1} aria-invalid={!!e.max_per_doctor_per_day} {...form.register("max_per_doctor_per_day", { valueAsNumber: true })} />
          </Row>
        </Group>

        <Group title="Time" description="Used to build slots and to understand “morning” or “afternoon” in patient messages.">
          <Row id="timezone" label="Clinic time zone" help="IANA name, e.g. Asia/Kolkata." error={e.timezone} wide>
            <Input id="timezone" list="timezone-options" autoComplete="off" spellCheck={false} aria-invalid={!!e.timezone} {...form.register("timezone")} />
            <datalist id="timezone-options">
              {timezones.map((tz) => (
                <option key={tz} value={tz} />
              ))}
            </datalist>
          </Row>
          {timezone && timezone.trim() !== original.timezone ? (
            <p role="alert" className="flex gap-2 rounded-lg border border-l-4 border-l-status-attention-edge bg-status-attention-bg p-3 text-body-sm text-status-attention sm:col-span-2">
              <TriangleAlert aria-hidden className="size-5 shrink-0" />
              Changing the time zone moves every slot and appointment label. Only change it if the clinic&apos;s location changed.
            </p>
          ) : null}
          <Row id="morning_end" label="Morning ends at" error={e.morning_end}>
            <Input id="morning_end" type="time" aria-invalid={!!e.morning_end} {...form.register("morning_end")} />
          </Row>
          <Row id="afternoon_end" label="Afternoon ends at" error={e.afternoon_end}>
            <Input id="afternoon_end" type="time" aria-invalid={!!e.afternoon_end} {...form.register("afternoon_end")} />
          </Row>
        </Group>
      </div>

      <div className="sticky bottom-0 z-10 space-y-3 rounded-xl border bg-card p-4 shadow-[var(--shadow-overlay)]">
        <InlineError
          error={save.error}
          title="The settings were not saved"
          fieldsMarked={matchApiFields(save.error, SETTINGS_API_FIELDS).length > 0}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!isDirty || save.isPending}>
            {save.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <Save aria-hidden />}
            Save settings
          </Button>
          <Button type="button" variant="ghost" disabled={!isDirty || save.isPending} onClick={() => { form.reset(original); save.reset(); }}>
            <Undo2 aria-hidden />
            Discard changes
          </Button>
          {settings.updated_at ? (
            <span className="text-body-sm text-muted-foreground">
              Last changed{" "}
              <time dateTime={settings.updated_at} title={formatUtcTimestamp(settings.updated_at)}>
                {formatRelative(settings.updated_at)}
              </time>
            </span>
          ) : null}
        </div>
      </div>
    </form>
  );
}

export function SettingsPageView() {
  return (
    <>
      <PageHeader title="Clinic settings" description="Details and rules the Telegram assistant and the booking service use." />
      <SettingsFormView />
    </>
  );
}
