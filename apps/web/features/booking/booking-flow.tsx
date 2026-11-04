"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CalendarX, LoaderCircle, Search, UserPlus } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";

import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, InlineError } from "@/components/states";
import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { createAppointment, findPatientsByPhone, getAvailability, getDoctors, type NewAppointmentPatient } from "@/lib/api/endpoints";
import { isApiError, toApiError } from "@/lib/api/errors";
import type { Appointment, PatientRef, Slot } from "@/lib/api/schemas";
import { formatLongDate, isIsoDate, todayIso } from "@/lib/dates";
import { queryKeys } from "@/lib/query";
import { newPatientSchema, phoneLookupSchema, type NewPatientForm, type PhoneLookupForm } from "@/lib/validation/forms";
import { cn } from "cn";

const SLOT_GONE_CODES = new Set(["SLOT_TAKEN", "SLOT_UNAVAILABLE"]);

function Step({ id, title, hint, children }: { id: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-4 rounded-xl border bg-card p-5 shadow-[var(--shadow-panel)]">
      <div className="space-y-1">
        <h2 id={id} tabIndex={-1} className="text-title font-bold outline-none">
          {title}
        </h2>
        {hint ? <p className="text-body-sm text-muted-foreground">{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

function SlotPicker({
  doctorId,
  date,
  selected,
  onSelect,
}: {
  doctorId: string;
  date: string;
  selected: Slot | null;
  onSelect: (slot: Slot) => void;
}) {
  const query = useQuery({
    queryKey: queryKeys.availability(doctorId, date),
    queryFn: ({ signal }) => getAvailability(doctorId, date, signal),
  });

  if (query.isPending) {
    return (
      <div role="status" className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-6">
        <span className="sr-only">Loading free times</span>
        {Array.from({ length: 12 }, (_, i) => (
          <Skeleton key={i} className="h-11 rounded-lg" />
        ))}
      </div>
    );
  }
  if (query.isError) return <ErrorState what="free times" error={query.error} onRetry={() => query.refetch()} />;
  if (query.data.slots.length === 0) {
    return (
      <EmptyState
        icon={CalendarX}
        title="No free times on this day"
        description="The doctor may be fully booked, on leave or not working. Try another date."
      />
    );
  }

  return (
    <fieldset>
      <legend className="sr-only">Free times on {formatLongDate(query.data.date)}</legend>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-6">
        {query.data.slots.map((slot) => {
          const checked = selected?.start === slot.start;
          return (
            <label
              key={slot.start}
              className={cn(
                "relative flex h-11 cursor-pointer items-center justify-center rounded-lg border text-base font-semibold tabular transition-colors has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring",
                checked ? "border-primary bg-primary text-primary-foreground" : "border-input bg-card hover:bg-primary-soft",
              )}
            >
              <input
                type="radio"
                name="slot"
                value={slot.start}
                checked={checked}
                onChange={() => onSelect(slot)}
                className="sr-only"
              />
              {slot.time_label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function PatientPicker({
  selected,
  onSelectExisting,
  onRegisteringChange,
  newPatient,
}: {
  selected: PatientRef | null;
  onSelectExisting: (patient: PatientRef | null) => void;
  onRegisteringChange: (registering: boolean) => void;
  newPatient: ReturnType<typeof useForm<NewPatientForm>>;
}) {
  const [phone, setPhone] = useState<string | null>(null);
  const lookupForm = useForm<PhoneLookupForm>({ resolver: zodResolver(phoneLookupSchema), defaultValues: { phone: "" } });
  const lookup = useQuery({
    queryKey: queryKeys.patientsByPhone(phone ?? ""),
    queryFn: ({ signal }) => findPatientsByPhone(phone ?? "", signal),
    enabled: phone !== null,
    staleTime: 0,
  });

  const matches = phone !== null && lookup.isSuccess ? lookup.data.items : null;
  useEffect(() => {
    onRegisteringChange(matches !== null && matches.length === 0);
    // One exact phone match is the usual case: select it so the receptionist only has to confirm.
    if (matches?.length === 1) onSelectExisting(matches[0]);
  }, [matches, onRegisteringChange, onSelectExisting]);

  const onLookup = lookupForm.handleSubmit(({ phone: value }) => {
    onSelectExisting(null);
    onRegisteringChange(false);
    newPatient.reset({ full_name: "", phone: value, verbal_consent: false });
    setPhone(value);
  });

  const errors = lookupForm.formState.errors;
  const np = newPatient.formState.errors;

  return (
    <div className="space-y-4">
      <form noValidate onSubmit={onLookup} className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <Field data-invalid={!!errors.phone} className="sm:max-w-sm">
          <FieldLabel htmlFor="lookup-phone">Patient&apos;s phone number</FieldLabel>
          <Input
            id="lookup-phone"
            type="tel"
            inputMode="tel"
            autoComplete="off"
            placeholder="+91 98765 43210"
            aria-invalid={!!errors.phone}
            {...lookupForm.register("phone")}
          />
          <FieldError errors={[errors.phone]} />
        </Field>
        <Button type="submit" variant="outline" className="sm:mt-7" disabled={lookup.isFetching}>
          {lookup.isFetching ? <LoaderCircle aria-hidden className="animate-spin" /> : <Search aria-hidden />}
          Find patient
        </Button>
      </form>

      {phone !== null && lookup.isError ? (
        <ErrorState what="patients" error={lookup.error} onRetry={() => lookup.refetch()} />
      ) : null}

      {phone !== null && lookup.isSuccess && lookup.data.items.length > 0 ? (
        <fieldset className="space-y-2">
          <legend className="mb-2 text-body-sm font-semibold">Patient with this number</legend>
          {lookup.data.items.map((patient) => {
            const checked = selected?.id === patient.id;
            return (
              <label
                key={patient.id}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-lg border p-3 has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring",
                  checked ? "border-primary bg-primary-soft" : "hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name="patient"
                  className="size-4 accent-[var(--primary)]"
                  checked={checked}
                  onChange={() => onSelectExisting(patient)}
                />
                <span>
                  <span className="block font-semibold">{patient.full_name}</span>
                  <span className="tabular text-body-sm text-muted-foreground">{patient.phone ?? "No phone on file"}</span>
                </span>
              </label>
            );
          })}
        </fieldset>
      ) : null}

      {phone !== null && lookup.isSuccess && lookup.data.items.length === 0 ? (
        <div className="space-y-4 rounded-lg border border-dashed p-4">
          <p className="flex items-center gap-2 font-semibold">
            <UserPlus aria-hidden className="size-5 text-primary" />
            No patient with this number yet. Register them:
          </p>
          <FieldGroup>
            <Field data-invalid={!!np.full_name}>
              <FieldLabel htmlFor="new-full-name">Full name</FieldLabel>
              <Input id="new-full-name" autoComplete="off" aria-invalid={!!np.full_name} {...newPatient.register("full_name")} />
              <FieldError errors={[np.full_name]} />
            </Field>
            <Field data-invalid={!!np.phone}>
              <FieldLabel htmlFor="new-phone">Phone number</FieldLabel>
              <Input id="new-phone" type="tel" inputMode="tel" autoComplete="off" aria-invalid={!!np.phone} {...newPatient.register("phone")} />
              <FieldError errors={[np.phone]} />
            </Field>
            <Controller
              control={newPatient.control}
              name="verbal_consent"
              render={({ field }) => (
                <Field orientation="horizontal" data-invalid={!!np.verbal_consent}>
                  <Checkbox
                    id="new-consent"
                    checked={field.value}
                    onCheckedChange={(v) => field.onChange(v === true)}
                    aria-invalid={!!np.verbal_consent}
                    aria-describedby="new-consent-help"
                  />
                  <div className="space-y-1">
                    <FieldLabel htmlFor="new-consent">The patient gave verbal consent</FieldLabel>
                    <FieldDescription id="new-consent-help">
                      Ask: &ldquo;May we store your name and phone number to manage your appointments?&rdquo;
                    </FieldDescription>
                    <FieldError errors={[np.verbal_consent]} />
                  </div>
                </Field>
              )}
            />
          </FieldGroup>
        </div>
      ) : null}
    </div>
  );
}

function BookedConfirmation({ appointment, onBookAnother }: { appointment: Appointment; onBookAnother: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), []);
  return (
    <section aria-labelledby="booked-heading" className="space-y-4 rounded-xl border border-l-4 border-l-status-booked-edge bg-card p-6">
      <CalendarCheck aria-hidden className="size-8 text-status-booked" />
      <div className="space-y-1">
        <h2 id="booked-heading" ref={headingRef} tabIndex={-1} className="text-heading font-bold outline-none">
          Appointment booked
        </h2>
        <p className="text-title">
          {appointment.patient.full_name} with {appointment.doctor_name}, {formatLongDate(appointment.date)} at {appointment.time_label}
        </p>
        <p className="text-muted-foreground">
          Reference <span className="tabular font-semibold text-foreground">{appointment.reference}</span>. Tell the patient this
          reference in case they need to change the booking.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={onBookAnother}>Book another</Button>
        <Button variant="outline" asChild>
          <Link href={`/?date=${appointment.date}`}>See the day&apos;s schedule</Link>
        </Button>
      </div>
    </section>
  );
}

/** Walk-in and phone booking (E6-S4): doctor → date → free slot → patient → book. */
export function BookingFlow() {
  const queryClient = useQueryClient();
  const notify = useToast();
  const today = todayIso();
  const [doctorId, setDoctorId] = useState("");
  const [date, setDate] = useState(today);
  const [slot, setSlot] = useState<Slot | null>(null);
  const [existing, setExisting] = useState<PatientRef | null>(null);
  const [slotNotice, setSlotNotice] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const [flowKey, setFlowKey] = useState(0);

  const newPatient = useForm<NewPatientForm>({
    resolver: zodResolver(newPatientSchema),
    defaultValues: { full_name: "", phone: "", verbal_consent: false },
  });

  const doctors = useQuery({
    queryKey: queryKeys.doctors("active"),
    queryFn: ({ signal }) => getDoctors({ active: true }, signal),
  });

  const book = useMutation({
    mutationFn: (patient: NewAppointmentPatient) => {
      if (!slot) throw new Error("No slot selected");
      return createAppointment({ doctor_id: doctorId, start: slot.start, patient });
    },
    onSuccess: async (appointment) => {
      notify({ tone: "success", title: "Appointment booked", description: `${appointment.reference}, ${appointment.time_label}` });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.scheduleAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.availabilityAll }),
      ]);
    },
    onError: async (error) => {
      if (isApiError(error) && SLOT_GONE_CODES.has(error.code)) {
        // E6-S4-AC2: the bot (or a colleague) took the slot first; show it and reload the free times.
        setSlotNotice(
          `${slot?.time_label ?? "That time"} was just booked by someone else, possibly through the Telegram assistant. The free times below are updated; please pick another.`,
        );
        setSlot(null);
        await queryClient.invalidateQueries({ queryKey: queryKeys.availability(doctorId, date) });
        document.getElementById("step-time")?.focus();
      }
    },
  });

  const bookError = book.error && !(isApiError(book.error) && SLOT_GONE_CODES.has(book.error.code)) ? book.error : null;
  const doctor = doctors.data?.items.find((d) => d.id === doctorId);

  const reset = () => {
    setSlot(null);
    setExisting(null);
    setRegistering(false);
    setSlotNotice(null);
    newPatient.reset({ full_name: "", phone: "", verbal_consent: false });
    book.reset();
    setFlowKey((k) => k + 1);
  };

  const submit = () => {
    if (!slot) return;
    setSlotNotice(null);
    if (existing) {
      book.mutate({ id: existing.id });
      return;
    }
    if (!registering) return;
    void newPatient.handleSubmit((values) =>
      book.mutate({ full_name: values.full_name.trim(), phone: values.phone.trim(), verbal_consent: true }),
    )();
  };

  if (book.isSuccess) {
    return (
      <>
        <PageHeader title="Book an appointment" />
        <BookedConfirmation appointment={book.data} onBookAnother={reset} />
      </>
    );
  }

  const missing = [!doctorId && "a doctor", !slot && "a time", !existing && !registering && "a patient"].filter(Boolean);

  return (
    <>
      <PageHeader title="Book an appointment" description="For patients at the desk or on the phone." />
      <div className="space-y-6">
        <Step id="step-doctor" title="Doctor and day">
          {doctors.isError ? (
            <ErrorState what="doctors" error={doctors.error} onRetry={() => doctors.refetch()} />
          ) : doctors.isSuccess && doctors.data.items.length === 0 ? (
            <EmptyState title="No active doctors" description="A clinic admin needs to add or reactivate a doctor first." />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="doctor">Doctor</FieldLabel>
                <Select
                  value={doctorId}
                  disabled={doctors.isPending}
                  onValueChange={(value) => {
                    setDoctorId(value);
                    setSlot(null);
                    setSlotNotice(null);
                  }}
                >
                  <SelectTrigger id="doctor" className="w-full">
                    <SelectValue placeholder={doctors.isPending ? "Loading doctors…" : "Choose a doctor"} />
                  </SelectTrigger>
                  <SelectContent>
                    {doctors.data?.items.map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name}, {d.specialty}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel htmlFor="booking-date">Day</FieldLabel>
                <Input
                  id="booking-date"
                  type="date"
                  min={today}
                  value={date}
                  onChange={(e) => {
                    if (!isIsoDate(e.target.value)) return;
                    setDate(e.target.value);
                    setSlot(null);
                    setSlotNotice(null);
                  }}
                />
                <FieldDescription>{formatLongDate(date)}</FieldDescription>
              </Field>
            </div>
          )}
        </Step>

        <Step id="step-time" title="Time" hint={doctor ? `Free times for ${doctor.name}` : "Choose a doctor first."}>
          {slotNotice ? (
            <div role="alert" className="rounded-lg border border-l-4 border-l-status-attention-edge bg-status-attention-bg p-3 text-status-attention">
              <p className="font-semibold">That time is no longer free</p>
              <p className="text-body-sm">{slotNotice}</p>
            </div>
          ) : null}
          {doctorId ? <SlotPicker doctorId={doctorId} date={date} selected={slot} onSelect={setSlot} /> : null}
        </Step>

        <Step id="step-patient" title="Patient" hint="Search by the exact phone number. New patients are registered here.">
          <PatientPicker
            key={flowKey}
            selected={existing}
            onSelectExisting={setExisting}
            onRegisteringChange={setRegistering}
            newPatient={newPatient}
          />
        </Step>

        <div className="space-y-3 rounded-xl border bg-card p-5">
          {doctor && slot ? (
            <p className="text-title">
              {doctor.name}, {formatLongDate(date)} at <span className="font-bold">{slot.time_label}</span>
              {existing ? ` for ${existing.full_name}` : ""}
            </p>
          ) : null}
          <InlineError error={bookError} title="The appointment was not booked" />
          <div className="flex flex-wrap items-center gap-3">
            <Button size="lg" disabled={missing.length > 0 || book.isPending} onClick={submit}>
              {book.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <CalendarCheck aria-hidden />}
              Book appointment
            </Button>
            {missing.length > 0 ? (
              <p className="text-body-sm text-muted-foreground" aria-live="polite">
                Choose {missing.join(", ")} to continue.
              </p>
            ) : null}
          </div>
          {bookError && toApiError(bookError).code === "LIMIT_REACHED" ? (
            <p className="text-body-sm text-muted-foreground">
              The clinic limits how many upcoming appointments one patient can hold. Cancel one of theirs first, or ask an admin.
            </p>
          ) : null}
        </div>
      </div>
    </>
  );
}
