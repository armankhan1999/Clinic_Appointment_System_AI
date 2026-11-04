"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, KeyRound, LoaderCircle, Lock, LockOpen, Power, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, InlineError, LoadingState, RefetchNotice } from "@/components/states";
import { Pill } from "@/components/status";
import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { createStaffUser, getStaffUsers, unlockStaffUser, updateStaffUser } from "@/lib/api/endpoints";
import { applyApiFieldErrors, matchApiFields } from "@/lib/api/field-errors";
import type { StaffUser } from "@/lib/api/schemas";
import { queryKeys } from "@/lib/query";
import { useSession } from "@/lib/session";
import {
  STAFF_PASSWORD_MIN,
  staffCreateSchema,
  staffPasswordResetSchema,
  type StaffCreateForm,
  type StaffPasswordResetForm,
} from "@/lib/validation/forms";

const ROLE_LABEL = { receptionist: "Receptionist", admin: "Clinic admin" } as const;

const STAFF_API_FIELDS = { username: "username", display_name: "display_name", role: "role", password: "password" } as const;

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
    onError: (error) => applyApiFieldErrors(error, form.setError, STAFF_API_FIELDS),
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
          <InlineError
            error={create.error}
            title="The account was not created"
            fieldsMarked={matchApiFields(create.error, STAFF_API_FIELDS).length > 0}
          />
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

function ResetPasswordDialog({ user, onClose }: { user: StaffUser | null; onClose: () => void }) {
  const notify = useToast();
  const [showPassword, setShowPassword] = useState(false);
  const empty: StaffPasswordResetForm = { password: "", confirmPassword: "" };
  const form = useForm<StaffPasswordResetForm>({ resolver: zodResolver(staffPasswordResetSchema), defaultValues: empty });

  const reset = useMutation({
    mutationFn: (values: StaffPasswordResetForm) => updateStaffUser(user?.id ?? "", { password: values.password }),
    onSuccess: (updated) => {
      notify({ tone: "success", title: "Password changed", description: `${updated.display_name} is signed out everywhere and must use the new password.` });
      form.reset(empty);
      onClose();
    },
    onError: (error) => applyApiFieldErrors(error, form.setError, { password: "password" }),
  });

  const e = form.formState.errors;
  return (
    <Dialog
      open={user !== null}
      onOpenChange={(next) => {
        if (reset.isPending || next) return;
        reset.reset();
        form.reset(empty);
        setShowPassword(false);
        onClose();
      }}
    >
      <DialogContent>
        <form noValidate onSubmit={form.handleSubmit((values) => reset.mutate(values))} className="space-y-5">
          <DialogHeader>
            <DialogTitle>Set a new password for {user?.display_name}</DialogTitle>
            <DialogDescription>
              They are signed out on every device and must sign in with the new password. Give it to them in person, not by message.
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field data-invalid={!!e.password}>
              <FieldLabel htmlFor="reset-password">New password</FieldLabel>
              <div className="relative">
                <Input
                  id="reset-password"
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
              <FieldDescription>At least {STAFF_PASSWORD_MIN} characters.</FieldDescription>
              <FieldError errors={[e.password]} />
            </Field>
            <Field data-invalid={!!e.confirmPassword}>
              <FieldLabel htmlFor="reset-password-confirm">Type the new password again</FieldLabel>
              <Input
                id="reset-password-confirm"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                aria-invalid={!!e.confirmPassword}
                {...form.register("confirmPassword")}
              />
              <FieldError errors={[e.confirmPassword]} />
            </Field>
          </FieldGroup>
          <InlineError
            error={reset.error}
            title="The password was not changed"
            fieldsMarked={matchApiFields(reset.error, { password: "password" }).length > 0}
          />
          <DialogFooter>
            <Button type="button" variant="outline" disabled={reset.isPending} onClick={onClose}>
              Close without saving
            </Button>
            <Button type="submit" disabled={reset.isPending}>
              {reset.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <KeyRound aria-hidden />}
              Set new password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type PendingAction = { kind: "toggle" | "unlock"; user: StaffUser } | null;

/** Whole minutes until a lockout ends, or null when the account is not locked (E6-S1-AC3). */
export function lockMinutesLeft(user: StaffUser, now: Date = new Date()): number | null {
  if (!user.locked_until) return null;
  const until = new Date(user.locked_until).getTime();
  if (Number.isNaN(until) || until <= now.getTime()) return null;
  return Math.max(1, Math.ceil((until - now.getTime()) / 60_000));
}

function StatusCell({ user }: { user: StaffUser }) {
  if (!user.active) return <Pill tone="cancelled">Deactivated</Pill>;
  const minutes = lockMinutesLeft(user);
  if (minutes === null) return <Pill tone="booked">Active</Pill>;
  return (
    <span className="flex flex-col gap-1">
      <Pill tone="attention" icon={Lock}>
        Locked
      </Pill>
      <span className="text-caption text-muted-foreground">
        Too many wrong passwords; unlocks by itself in about {minutes} minute{minutes === 1 ? "" : "s"}
      </span>
    </span>
  );
}

export function StaffAccounts() {
  const queryClient = useQueryClient();
  const notify = useToast();
  const session = useSession();
  const me = session.data?.user.id;
  const users = useQuery({ queryKey: queryKeys.staffUsers, queryFn: ({ signal }) => getStaffUsers(signal) });
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState<PendingAction>(null);
  const [resetting, setResetting] = useState<StaffUser | null>(null);

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
      <RefetchNotice query={users} what="staff accounts" />
      {users.isPending ? (
        <LoadingState label="Loading staff accounts" />
      ) : users.isLoadingError ? (
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
                  <TableCell>
                    <StatusCell user={user} />
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap justify-end gap-2">
                      {user.active && lockMinutesLeft(user) !== null ? (
                        <Button
                          variant="outline"
                          size="sm"
                          aria-label={`Unlock ${user.display_name}`}
                          onClick={() => setPending({ kind: "unlock", user })}
                        >
                          <LockOpen aria-hidden />
                          Unlock
                        </Button>
                      ) : null}
                      {user.active && user.id !== me ? (
                        <Button
                          variant="outline"
                          size="sm"
                          aria-label={`Set a new password for ${user.display_name}`}
                          onClick={() => setResetting(user)}
                        >
                          <KeyRound aria-hidden />
                          New password
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
      <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />

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
