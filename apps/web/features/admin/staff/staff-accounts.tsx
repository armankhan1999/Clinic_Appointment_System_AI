"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, LoaderCircle, LockOpen, Power, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, InlineError, LoadingState } from "@/components/states";
import { Pill } from "@/components/status";
import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { createStaffUser, getStaffUsers, unlockStaffUser, updateStaffUser } from "@/lib/api/endpoints";
import type { StaffUser } from "@/lib/api/schemas";
import { queryKeys } from "@/lib/query";
import { useSession } from "@/lib/session";
import { STAFF_PASSWORD_MIN, staffCreateSchema, type StaffCreateForm } from "@/lib/validation/forms";

const ROLE_LABEL = { receptionist: "Receptionist", admin: "Clinic admin" } as const;

function CreateStaffDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const [showPassword, setShowPassword] = useState(false);
  const empty: StaffCreateForm = { display_name: "", username: "", role: "receptionist", password: "", confirmPassword: "" };
  const form = useForm<StaffCreateForm>({ resolver: zodResolver(staffCreateSchema), defaultValues: empty });

  const create = useMutation({
    mutationFn: (values: StaffCreateForm) =>
      createStaffUser({ username: values.username.trim(), display_name: values.display_name.trim(), role: values.role, password: values.password }),
    onSuccess: async (user) => {
      notify({ tone: "success", title: "Account created", description: `${user.display_name} can sign in as "${user.username}".` });
      await queryClient.invalidateQueries({ queryKey: queryKeys.staffUsers });
      form.reset(empty);
      onOpenChange(false);
    },
  });

  const e = form.formState.errors;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (create.isPending) return;
        if (!next) {
          create.reset();
          form.reset(empty);
          setShowPassword(false);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <form noValidate onSubmit={form.handleSubmit((values) => create.mutate(values))} className="space-y-5">
          <DialogHeader>
            <DialogTitle>Add a staff account</DialogTitle>
            <DialogDescription>Give the person their username and password in person, not by message.</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field data-invalid={!!e.display_name}>
              <FieldLabel htmlFor="staff-name">Name</FieldLabel>
              <Input id="staff-name" autoComplete="off" aria-invalid={!!e.display_name} {...form.register("display_name")} />
              <FieldError errors={[e.display_name]} />
            </Field>
            <Field data-invalid={!!e.username}>
              <FieldLabel htmlFor="staff-username">Username</FieldLabel>
              <Input id="staff-username" autoComplete="off" autoCapitalize="none" spellCheck={false} aria-invalid={!!e.username} {...form.register("username")} />
              <FieldError errors={[e.username]} />
            </Field>
            <Controller
              control={form.control}
              name="role"
              render={({ field }) => (
                <Field data-invalid={!!e.role}>
                  <FieldLabel htmlFor="staff-role">Role</FieldLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="staff-role" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="receptionist">Receptionist: schedule and bookings</SelectItem>
                      <SelectItem value="admin">Clinic admin: everything, including settings</SelectItem>
                    </SelectContent>
                  </Select>
                  <FieldError errors={[e.role]} />
                </Field>
              )}
            />
            <Field data-invalid={!!e.password}>
              <FieldLabel htmlFor="staff-password">Password</FieldLabel>
              <div className="relative">
                <Input
                  id="staff-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  className="pr-12"
                  aria-invalid={!!e.password}
                  {...form.register("password")}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  className="absolute top-0.5 right-0.5"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  onClick={() => setShowPassword((v) => !v)}
                >
                  {showPassword ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
                </Button>
              </div>
              <FieldDescription>At least {STAFF_PASSWORD_MIN} characters. A short sentence is easy to remember.</FieldDescription>
              <FieldError errors={[e.password]} />
            </Field>
            <Field data-invalid={!!e.confirmPassword}>
              <FieldLabel htmlFor="staff-password-confirm">Type the password again</FieldLabel>
              <Input
                id="staff-password-confirm"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                aria-invalid={!!e.confirmPassword}
                {...form.register("confirmPassword")}
              />
              <FieldError errors={[e.confirmPassword]} />
            </Field>
          </FieldGroup>
          <InlineError error={create.error} title="The account was not created" />
          <DialogFooter>
            <Button type="button" variant="outline" disabled={create.isPending} onClick={() => onOpenChange(false)}>
              Close without saving
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <UserPlus aria-hidden />}
              Create account
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type PendingAction = { kind: "toggle" | "unlock"; user: StaffUser } | null;

export function StaffAccounts() {
  const queryClient = useQueryClient();
  const notify = useToast();
  const session = useSession();
  const me = session.data?.user.id;
  const users = useQuery({ queryKey: queryKeys.staffUsers, queryFn: ({ signal }) => getStaffUsers(signal) });
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState<PendingAction>(null);

  const act = useMutation({
    mutationFn: (action: NonNullable<PendingAction>) =>
      action.kind === "unlock" ? unlockStaffUser(action.user.id) : updateStaffUser(action.user.id, { active: !action.user.active }),
    onSuccess: async (user, action) => {
      notify({
        tone: "success",
        title: action.kind === "unlock" ? "Account unlocked" : user.active ? "Account reactivated" : "Account deactivated",
        description: user.display_name,
      });
      setPending(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.staffUsers });
    },
  });

  const list = [...(users.data?.items ?? [])].sort((a, b) => Number(b.active) - Number(a.active) || a.display_name.localeCompare(b.display_name));

  return (
    <>
      <PageHeader
        title="Staff accounts"
        description="Who can sign in to Front Desk."
        actions={
          <Button onClick={() => setCreating(true)}>
            <UserPlus aria-hidden />
            Add staff account
          </Button>
        }
      />
      {users.isPending ? (
        <LoadingState label="Loading staff accounts" />
      ) : users.isError ? (
        <ErrorState what="staff accounts" error={users.error} onRetry={() => users.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState icon={Users} title="No staff accounts" action={<Button onClick={() => setCreating(true)}>Add staff account</Button>} />
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Username</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((user) => (
                <TableRow key={user.id}>
                  <TableCell className="font-semibold">
                    {user.display_name}
                    {user.id === me ? <span className="ml-2 text-caption font-normal text-muted-foreground">(you)</span> : null}
                  </TableCell>
                  <TableCell className="tabular">{user.username}</TableCell>
                  <TableCell>{ROLE_LABEL[user.role]}</TableCell>
                  <TableCell>{user.active ? <Pill tone="booked">Active</Pill> : <Pill tone="cancelled">Deactivated</Pill>}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap justify-end gap-2">
                      {user.active ? (
                        <Button variant="outline" size="sm" onClick={() => setPending({ kind: "unlock", user })}>
                          <LockOpen aria-hidden />
                          Unlock
                        </Button>
                      ) : null}
                      {user.id !== me ? (
                        <Button variant="ghost" size="sm" onClick={() => setPending({ kind: "toggle", user })}>
                          <Power aria-hidden />
                          {user.active ? "Deactivate" : "Reactivate"}
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateStaffDialog open={creating} onOpenChange={setCreating} />

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPending(null);
            act.reset();
          }
        }}
        title={
          pending?.kind === "unlock"
            ? `Unlock ${pending.user.display_name}?`
            : pending?.user.active
              ? `Deactivate ${pending.user.display_name}?`
              : `Reactivate ${pending?.user.display_name ?? ""}?`
        }
        description={
          pending?.kind === "unlock" ? (
            <p>Clears the lock after too many wrong passwords so they can try again now. Only do this if you know it was them.</p>
          ) : pending?.user.active ? (
            <p>They can no longer sign in. Their past actions stay in the activity log.</p>
          ) : (
            <p>They can sign in again with their existing password.</p>
          )
        }
        confirmLabel={pending?.kind === "unlock" ? "Unlock account" : pending?.user.active ? "Deactivate" : "Reactivate"}
        destructive={pending?.kind === "toggle" && pending.user.active}
        pending={act.isPending}
        error={act.error}
        onConfirm={() => (pending ? act.mutate(pending) : undefined)}
      />
    </>
  );
}
