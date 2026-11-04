import { z } from "zod";

import { isIsoDate, minutesOf } from "@/lib/dates";

/*
 * Form schemas. Limits mirror the contract (docs/api/staff-api.md) and, where the
 * contract is silent, the database CHECK constraints in
 * apps/backend/migrations/versions/0001_baseline.py, so mistakes surface next to
 * the field instead of as a round-trip error. The API remains the authority.
 */

const required = (label: string) => z.string().trim().min(1, { message: `Enter ${label}` });

export const loginSchema = z.object({
  username: required("your username"),
  password: z.string().min(1, { message: "Enter your password" }),
});
export type LoginForm = z.infer<typeof loginSchema>;

export const CANCEL_REASON_MAX = 200;
export const cancelSchema = z.object({
  reason: z
    .string()
    .trim()
    .min(1, { message: "Give a short reason so the patient knows why" })
    .max(CANCEL_REASON_MAX, { message: `Keep it under ${CANCEL_REASON_MAX} characters` }),
});
export type CancelForm = z.infer<typeof cancelSchema>;

const isoDate = z
  .string()
  .trim()
  .refine(isIsoDate, { message: "Pick a date" });

export function isPlausiblePhone(value: string): boolean {
  const trimmed = value.trim();
  if (!/^\+?[0-9\s().-]+$/.test(trimmed)) return false;
  const digits = trimmed.replace(/\D/g, "");
  return digits.length >= 7 && digits.length <= 15;
}

const phone = z
  .string()
  .trim()
  .min(1, { message: "Enter the phone number" })
  .refine(isPlausiblePhone, { message: "Enter a phone number with 7–15 digits, e.g. +91 98765 43210" });

export const phoneLookupSchema = z.object({ phone });
export type PhoneLookupForm = z.infer<typeof phoneLookupSchema>;

export const newPatientSchema = z.object({
  full_name: z
    .string()
    .trim()
    .min(2, { message: "Enter the patient's full name" })
    .max(60, { message: "Keep the name under 60 characters" })
    .refine((v) => !/[0-9]/.test(v), { message: "A name can't contain numbers" }),
  phone,
  verbal_consent: z.boolean().refine((v) => v, {
    message: "Ask the patient for consent before saving their details",
  }),
});
export type NewPatientForm = z.infer<typeof newPatientSchema>;

const doctorText = (label: string) =>
  z
    .string()
    .trim()
    .min(2, { message: `Enter the ${label} (at least 2 characters)` })
    .max(80, { message: `Keep the ${label} under 80 characters` });

export const doctorFormSchema = z.object({ name: doctorText("name"), specialty: doctorText("specialty") });
export type DoctorForm = z.infer<typeof doctorFormSchema>;

export const LEAVE_REASON_MAX = 200;
// The API requires a reason (LeaveIn, 1–200 characters): affected patients are sent it.
export const leaveFormSchema = z.object({
  date: isoDate,
  reason: z
    .string()
    .trim()
    .min(1, { message: "Give a reason. Patients whose appointments are cancelled are sent it." })
    .max(LEAVE_REASON_MAX, { message: `Keep it under ${LEAVE_REASON_MAX} characters` }),
});
export type LeaveForm = z.infer<typeof leaveFormSchema>;

export const FAQ_TOPIC_PATTERN = /^[a-z0-9_]{1,40}$/;
export const FAQ_ANSWER_MAX = 2000;

export function parseAliases(text: string): string[] {
  const seen = new Set<string>();
  const aliases: string[] = [];
  for (const part of text.split(/[,\n]/)) {
    const alias = part.trim();
    const key = alias.toLowerCase();
    if (alias && !seen.has(key)) {
      seen.add(key);
      aliases.push(alias);
    }
  }
  return aliases;
}

export const faqFormSchema = z.object({
  topic: z
    .string()
    .trim()
    .regex(FAQ_TOPIC_PATTERN, {
      message: "Use 1–40 lowercase letters, numbers or underscores, e.g. parking_info",
    }),
  aliasesText: z.string(),
  answer: z
    .string()
    .trim()
    .min(1, { message: "Write the answer patients will see" })
    .max(FAQ_ANSWER_MAX, { message: `Keep the answer under ${FAQ_ANSWER_MAX} characters` }),
});
export type FaqForm = z.infer<typeof faqFormSchema>;

export const STAFF_PASSWORD_MIN = 12;
const staffPassword = z
  .string()
  .min(STAFF_PASSWORD_MIN, { message: `Use at least ${STAFF_PASSWORD_MIN} characters` })
  .max(128, { message: "Keep the password under 128 characters" });
const passwordsMatch = {
  check: (v: { password: string; confirmPassword: string }) => v.password === v.confirmPassword,
  error: { path: ["confirmPassword"], message: "The two passwords don't match" },
};

export const staffPasswordResetSchema = z
  .object({ password: staffPassword, confirmPassword: z.string() })
  .refine(passwordsMatch.check, passwordsMatch.error);
export type StaffPasswordResetForm = z.infer<typeof staffPasswordResetSchema>;

export const staffCreateSchema = z
  .object({
    display_name: z.string().trim().min(1, { message: "Enter the person's name" }).max(80, { message: "Keep it under 80 characters" }),
    username: z
      .string()
      .trim()
      .min(3, { message: "Usernames need at least 3 characters" })
      .max(40, { message: "Keep the username under 40 characters" })
      .regex(/^\S+$/, { message: "Usernames can't contain spaces" }),
    role: z.enum(["receptionist", "admin"], { error: "Choose a role" }),
    password: staffPassword,
    confirmPassword: z.string(),
  })
  .refine(passwordsMatch.check, passwordsMatch.error);
export type StaffCreateForm = z.infer<typeof staffCreateSchema>;

export function isValidTimeZone(value: string): boolean {
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

const wholeNumber = (label: string, min: number, max: number) =>
  z
    .number({ error: `Enter ${label}` })
    .int({ message: "Use a whole number" })
    .min(min, { message: `Must be at least ${min}` })
    .max(max, { message: `Must be at most ${max}` });

const hhmm = z.string().refine((v) => minutesOf(v) !== null, { message: "Enter a time like 12:00" });

export const settingsFormSchema = z
  .object({
    clinic_name: required("the clinic name").max(120, { message: "Keep it under 120 characters" }),
    phone: required("the clinic phone number").max(40, { message: "Keep it under 40 characters" }),
    address: required("the address").max(400, { message: "Keep it under 400 characters" }),
    staff_hours_text: required("the front desk hours").max(400, { message: "Keep it under 400 characters" }),
    timezone: z.string().trim().refine(isValidTimeZone, { message: "Choose a valid time zone, e.g. Asia/Kolkata" }),
    emergency_number: required("the emergency number").max(40, { message: "Keep it under 40 characters" }),
    // Safety rule: with no phrases the assistant cannot detect emergencies (E5-S3), so never allow an empty list.
    emergencyPhrasesText: z.string().refine((text) => parsePhrases(text).length > 0, {
      message: "Add at least one phrase. Without phrases the assistant can't recognise emergencies.",
    }),
    cutoff_minutes: wholeNumber("the cut-off in minutes", 0, 10_080),
    booking_window_days: wholeNumber("the number of days", 1, 365),
    max_upcoming_per_patient: wholeNumber("a limit", 1, 50),
    max_per_doctor_per_day: wholeNumber("a limit", 1, 50),
    morning_end: hhmm,
    afternoon_end: hhmm,
  })
  .refine((v) => (minutesOf(v.morning_end) ?? 0) < (minutesOf(v.afternoon_end) ?? 0), {
    path: ["afternoon_end"],
    message: "Afternoon must end after morning ends",
  });
export type SettingsForm = z.infer<typeof settingsFormSchema>;

/** One phrase per line (phrases may contain commas); trims, drops blanks and case-insensitive duplicates. */
export function parsePhrases(text: string): string[] {
  const seen = new Set<string>();
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => {
      const key = line.toLowerCase();
      if (!line || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const auditFilterSchema = z
  .object({
    from: z.string().refine((v) => v === "" || isIsoDate(v), { message: "Pick a valid date" }),
    to: z.string().refine((v) => v === "" || isIsoDate(v), { message: "Pick a valid date" }),
    actor_type: z.enum(["", "agent", "staff", "system", "patient_button"]),
    action: z.string().trim().max(80, { message: "Keep it under 80 characters" }),
    patient_id: z
      .string()
      .trim()
      .refine((v) => v === "" || UUID_PATTERN.test(v), { message: "Paste the full patient ID" }),
  })
  .refine((v) => !v.from || !v.to || v.from <= v.to, { path: ["to"], message: "The end date must be on or after the start date" });
export type AuditFilterForm = z.infer<typeof auditFilterSchema>;
