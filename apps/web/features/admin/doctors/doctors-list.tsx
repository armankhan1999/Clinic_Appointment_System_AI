"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, LoaderCircle, Pencil, Plus, Power, Stethoscope } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, InlineError, LoadingState } from "@/components/states";
import { Pill } from "@/components/status";
import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { createDoctor, getDoctors, updateDoctor } from "@/lib/api/endpoints";
import type { Doctor } from "@/lib/api/schemas";
import { queryKeys } from "@/lib/query";
import { doctorFormSchema, type DoctorForm } from "@/lib/validation/forms";

function DoctorFormDialog({
  open,
  onOpenChange,
  doctor,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  doctor: Doctor | null;
}) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const form = useForm<DoctorForm>({ resolver: zodResolver(doctorFormSchema), defaultValues: { name: "", specialty: "" } });

  useEffect(() => {
    if (open) form.reset({ name: doctor?.name ?? "", specialty: doctor?.specialty ?? "" });
  }, [open, doctor, form]);

  const save = useMutation({
    mutationFn: (values: DoctorForm) =>
      doctor ? updateDoctor(doctor.id, values) : createDoctor({ name: values.name, specialty: values.specialty }),
    onSuccess: async (saved) => {
      notify({ tone: "success", title: doctor ? "Doctor updated" : "Doctor added", description: saved.name });
      await queryClient.invalidateQueries({ queryKey: queryKeys.doctorsAll });
      onOpenChange(false);
    },
  });

  const errors = form.formState.errors;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (save.isPending) return;
        if (!next) save.reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <form noValidate onSubmit={form.handleSubmit((values) => save.mutate(values))} className="space-y-5">
          <DialogHeader>
            <DialogTitle>{doctor ? "Edit doctor" : "Add a doctor"}</DialogTitle>
            <DialogDescription>
              {doctor ? "Patients see the new name and specialty in the Telegram assistant." : "Set the weekly hours next, so patients can book."}
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field data-invalid={!!errors.name}>
              <FieldLabel htmlFor="doctor-name">Name</FieldLabel>
              <Input id="doctor-name" placeholder="Dr Anil Rao" aria-invalid={!!errors.name} {...form.register("name")} />
              <FieldError errors={[errors.name]} />
            </Field>
            <Field data-invalid={!!errors.specialty}>
              <FieldLabel htmlFor="doctor-specialty">Specialty</FieldLabel>
              <Input id="doctor-specialty" placeholder="General physician" aria-invalid={!!errors.specialty} {...form.register("specialty")} />
              <FieldError errors={[errors.specialty]} />
            </Field>
          </FieldGroup>
          <InlineError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" disabled={save.isPending} onClick={() => onOpenChange(false)}>
              Close without saving
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : null}
              {doctor ? "Save changes" : "Add doctor"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function DoctorsList() {
  const queryClient = useQueryClient();
  const notify = useToast();
  const doctors = useQuery({ queryKey: queryKeys.doctors("all"), queryFn: ({ signal }) => getDoctors({}, signal) });
  const [editing, setEditing] = useState<Doctor | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [toggling, setToggling] = useState<Doctor | null>(null);

  const toggle = useMutation({
    mutationFn: (doctor: Doctor) => updateDoctor(doctor.id, { active: !doctor.active }),
    onSuccess: async (saved) => {
      notify({ tone: "success", title: saved.active ? "Doctor reactivated" : "Doctor deactivated", description: saved.name });
      await queryClient.invalidateQueries({ queryKey: queryKeys.doctorsAll });
      await queryClient.invalidateQueries({ queryKey: queryKeys.scheduleAll });
      setToggling(null);
    },
  });

  const openForm = (doctor: Doctor | null) => {
    setEditing(doctor);
    setFormOpen(true);
  };

  return (
    <>
      <PageHeader
        title="Doctors and hours"
        description="Add doctors, set their weekly hours and leave days."
        actions={
          <Button onClick={() => openForm(null)}>
            <Plus aria-hidden />
            Add doctor
          </Button>
        }
      />

      {doctors.isPending ? (
        <LoadingState label="Loading doctors" />
      ) : doctors.isError ? (
        <ErrorState what="doctors" error={doctors.error} onRetry={() => doctors.refetch()} />
      ) : doctors.data.items.length === 0 ? (
        <EmptyState
          icon={Stethoscope}
          title="No doctors yet"
          description="Add the first doctor, then set their weekly hours so patients can book."
          action={<Button onClick={() => openForm(null)}>Add doctor</Button>}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Doctor</TableHead>
                <TableHead>Specialty</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {doctors.data.items.map((doctor) => (
                <TableRow key={doctor.id}>
                  <TableCell className="font-semibold">{doctor.name}</TableCell>
                  <TableCell>{doctor.specialty}</TableCell>
                  <TableCell>
                    {doctor.active ? <Pill tone="booked">Active</Pill> : <Pill tone="cancelled">Inactive</Pill>}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap justify-end gap-2">
                      <Button variant="outline" size="sm" asChild>
                        <Link href={`/admin/doctors/${encodeURIComponent(doctor.id)}`}>
                          <CalendarClock aria-hidden />
                          Hours and leave
                        </Link>
                      </Button>
                      <Button variant="ghost" size="sm" aria-label={`Edit ${doctor.name}`} onClick={() => openForm(doctor)}>
                        <Pencil aria-hidden />
                        Edit
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setToggling(doctor)}>
                        <Power aria-hidden />
                        {doctor.active ? "Deactivate" : "Reactivate"}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <DoctorFormDialog open={formOpen} onOpenChange={setFormOpen} doctor={editing} />

      <ConfirmDialog
        open={toggling !== null}
        onOpenChange={(open) => {
          if (!open) {
            setToggling(null);
            toggle.reset();
          }
        }}
        title={toggling?.active ? `Deactivate ${toggling.name}?` : `Reactivate ${toggling?.name ?? ""}?`}
        description={
          toggling?.active ? (
            <p>
              Patients can no longer book this doctor, and the daily schedule only lists active doctors. Cancel any upcoming
              appointments with this doctor first, so no patient is left without a notice.
            </p>
          ) : (
            <p>Patients can book this doctor again within their weekly hours.</p>
          )
        }
        confirmLabel={toggling?.active ? "Deactivate" : "Reactivate"}
        destructive={toggling?.active ?? false}
        pending={toggle.isPending}
        error={toggle.error}
        onConfirm={() => (toggling ? toggle.mutate(toggling) : undefined)}
      />
    </>
  );
}
