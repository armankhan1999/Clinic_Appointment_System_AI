"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Eye, EyeOff, LoaderCircle, LockKeyhole } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { RequestReference } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { login } from "@/lib/api/endpoints";
import { ApiError, toApiError } from "@/lib/api/errors";
import { safeNextPath } from "@/lib/navigation";
import { queryKeys } from "@/lib/query";
import { loginSchema, type LoginForm as LoginValues } from "@/lib/validation/forms";

/** Turns a failed sign-in into a message a receptionist can act on, without revealing which part was wrong. */
export function loginErrorMessage(error: ApiError, now: Date = new Date()): { title: string; body: string; showReference: boolean } {
  switch (error.code) {
    case "UNAUTHENTICATED":
      return {
        title: "Username or password is incorrect",
        body: "Check both and try again. After 5 wrong tries the account is locked for 15 minutes.",
        showReference: false,
      };
    case "ACCOUNT_LOCKED": {
      const until = error.lockedUntil ? new Date(error.lockedUntil).getTime() : Number.NaN;
      const minutes = Number.isNaN(until) ? null : Math.max(1, Math.ceil((until - now.getTime()) / 60_000));
      return {
        title: "This account is locked",
        body: `Too many wrong passwords were tried. ${
          minutes ? `Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}` : "Try again later"
        }, or ask a clinic admin to unlock it.`,
        showReference: false,
      };
    }
    case "RATE_LIMITED":
      return {
        title: "Too many sign-in attempts",
        body: "Sign-in is paused for this computer. Wait a minute, then try again.",
        showReference: false,
      };
    default:
      return { title: "Couldn't sign in", body: error.message, showReference: true };
  }
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [showPassword, setShowPassword] = useState(false);

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
  });

  const mutation = useMutation({
    mutationFn: (values: LoginValues) => login(values.username.trim(), values.password),
    onSuccess: (session) => {
      queryClient.setQueryData(queryKeys.session, session);
      router.replace(safeNextPath(searchParams.get("next")));
    },
    onError: () => {
      form.resetField("password");
      form.setFocus("password");
    },
  });

  const failure = mutation.error ? loginErrorMessage(toApiError(mutation.error)) : null;
  const { errors } = form.formState;

  return (
    <form noValidate onSubmit={form.handleSubmit((values) => mutation.mutate(values))} className="flex flex-col gap-5">
      {failure ? (
        <div role="alert" className="flex gap-3 rounded-lg border border-l-4 border-l-destructive bg-card p-3">
          {mutation.error && toApiError(mutation.error).code === "ACCOUNT_LOCKED" ? (
            <LockKeyhole aria-hidden className="mt-0.5 size-5 shrink-0 text-destructive" />
          ) : (
            <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0 text-destructive" />
          )}
          <div className="space-y-1">
            <p className="font-semibold">{failure.title}</p>
            <p className="text-body-sm text-muted-foreground">{failure.body}</p>
            {failure.showReference ? <RequestReference requestId={toApiError(mutation.error).requestId} /> : null}
          </div>
        </div>
      ) : null}

      <FieldGroup>
        <Field data-invalid={!!errors.username}>
          <FieldLabel htmlFor="username">Username</FieldLabel>
          <Input
            id="username"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            aria-invalid={!!errors.username}
            aria-describedby={errors.username ? "username-error" : undefined}
            {...form.register("username")}
          />
          <FieldError id="username-error" errors={[errors.username]} />
        </Field>

        <Field data-invalid={!!errors.password}>
          <FieldLabel htmlFor="password">Password</FieldLabel>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              className="pr-12"
              aria-invalid={!!errors.password}
              aria-describedby={errors.password ? "password-error" : undefined}
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
          <FieldError id="password-error" errors={[errors.password]} />
        </Field>
      </FieldGroup>

      <Button type="submit" size="lg" disabled={mutation.isPending || mutation.isSuccess}>
        {mutation.isPending || mutation.isSuccess ? <LoaderCircle aria-hidden className="animate-spin" /> : null}
        {mutation.isSuccess ? "Opening today's schedule…" : "Sign in"}
      </Button>
    </form>
  );
}
