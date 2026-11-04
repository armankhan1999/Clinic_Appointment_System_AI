import { describe, expect, it } from "vitest";

import { addDays, formatRelative, formatUtcTimestamp, isIsoDate, mondayOf, toHourMinute, todayIso } from "@/lib/dates";
import { loginUrlFor, safeNextPath } from "@/lib/navigation";
import {
  auditFilterSchema,
  cancelSchema,
  faqFormSchema,
  isPlausiblePhone,
  leaveFormSchema,
  newPatientSchema,
  parseAliases,
  parsePhrases,
  settingsFormSchema,
  staffCreateSchema,
  staffPasswordResetSchema,
} from "@/lib/validation/forms";

describe("safeNextPath (open-redirect guard)", () => {
  it.each([
    ["/admin/audit?page=2", "/admin/audit?page=2"],
    ["/book", "/book"],
  ])("keeps same-origin path %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "/%2F%2Fevil.example",
    "/%5Cevil.example",
    "javascript:alert(1)",
    "/login",
    "/login?next=/x",
    "",
    null,
  ])("rejects %s", (input) => {
    expect(safeNextPath(input)).toBe("/");
  });

  it("builds a login URL that keeps the intended path", () => {
    expect(loginUrlFor("/admin/faq")).toBe("/login?next=%2Fadmin%2Ffaq");
    expect(loginUrlFor("/")).toBe("/login");
  });
});

describe("dates", () => {
  it("validates calendar dates", () => {
    expect(isIsoDate("2030-02-28")).toBe(true);
    expect(isIsoDate("2030-02-30")).toBe(false);
    expect(isIsoDate("30-02-2030")).toBe(false);
  });

  it("does calendar arithmetic across month and year ends", () => {
    expect(addDays("2030-12-31", 1)).toBe("2031-01-01");
    expect(addDays("2030-03-01", -1)).toBe("2030-02-28");
  });

  it("finds the Monday of a week", () => {
    expect(mondayOf("2026-11-05")).toBe("2026-11-02");
    expect(mondayOf("2026-11-08")).toBe("2026-11-02");
    expect(mondayOf("2026-11-02")).toBe("2026-11-02");
  });

  it("formats UTC instants explicitly in UTC", () => {
    expect(formatUtcTimestamp("2030-01-09T04:00:05Z")).toMatch(/04:00:05.*UTC/);
  });

  it("formats elapsed time without time zones", () => {
    const now = new Date("2030-01-09T04:30:00Z");
    expect(formatRelative("2030-01-09T04:20:00Z", now)).toBe("10 minutes ago");
    expect(formatRelative("2030-01-09T04:29:50Z", now)).toBe("just now");
    expect(formatRelative("2030-01-09T04:42:00Z", now)).toBe("in 12 minutes");
  });

  it("returns today's local date as YYYY-MM-DD", () => {
    expect(todayIso(new Date(2030, 0, 9, 10, 0))).toBe("2030-01-09");
  });

  it("normalises HH:MM:SS to HH:MM", () => {
    expect(toHourMinute("09:30:00")).toBe("09:30");
    expect(toHourMinute("09:30")).toBe("09:30");
  });
});

describe("form schemas", () => {
  it("requires a cancel reason of 1–200 characters", () => {
    expect(cancelSchema.safeParse({ reason: "  " }).success).toBe(false);
    expect(cancelSchema.safeParse({ reason: "x".repeat(201) }).success).toBe(false);
    expect(cancelSchema.safeParse({ reason: "Doctor unwell" }).success).toBe(true);
  });

  it("validates phone numbers loosely (the API normalises)", () => {
    expect(isPlausiblePhone("+91 98765 43210")).toBe(true);
    expect(isPlausiblePhone("(022) 2345-6789")).toBe(true);
    expect(isPlausiblePhone("12345")).toBe(false);
    expect(isPlausiblePhone("call me")).toBe(false);
  });

  it("requires verbal consent for a new patient", () => {
    const base = { full_name: "Meera Iyer", phone: "+91 98765 43210" };
    const refused = newPatientSchema.safeParse({ ...base, verbal_consent: false });
    expect(refused.success).toBe(false);
    expect(refused.error?.issues[0].path).toEqual(["verbal_consent"]);
    expect(newPatientSchema.safeParse({ ...base, verbal_consent: true }).success).toBe(true);
    expect(newPatientSchema.safeParse({ ...base, full_name: "R2D2", verbal_consent: true }).success).toBe(false);
  });

  it.each([
    ["parking_info", true],
    ["fees2", true],
    ["Parking", false],
    ["parking-info", false],
    ["", false],
    ["a".repeat(41), false],
  ])("FAQ topic %s valid=%s", (topic, valid) => {
    expect(faqFormSchema.safeParse({ topic, aliasesText: "", answer: "Yes" }).success).toBe(valid);
  });

  it("limits FAQ answers to 1–2000 characters", () => {
    expect(faqFormSchema.safeParse({ topic: "t", aliasesText: "", answer: "" }).success).toBe(false);
    expect(faqFormSchema.safeParse({ topic: "t", aliasesText: "", answer: "x".repeat(2001) }).success).toBe(false);
    expect(faqFormSchema.safeParse({ topic: "t", aliasesText: "", answer: "x".repeat(2000) }).success).toBe(true);
  });

  it("parses aliases and emergency phrases into clean lists", () => {
    expect(parseAliases("car park, Parking ,\nparking lot,,")).toEqual(["car park", "Parking", "parking lot"]);
    expect(parsePhrases("chest pain\nCan't breathe, help\n\nchest pain")).toEqual(["chest pain", "Can't breathe, help"]);
  });

  it("requires staff passwords of at least 12 characters that match", () => {
    const base = { display_name: "Asha", username: "asha", role: "receptionist" as const };
    expect(staffCreateSchema.safeParse({ ...base, password: "short-pass1", confirmPassword: "short-pass1" }).success).toBe(false);
    const mismatch = staffCreateSchema.safeParse({ ...base, password: "long-enough-pass", confirmPassword: "long-enough-pas" });
    expect(mismatch.error?.issues[0].path).toEqual(["confirmPassword"]);
    expect(staffCreateSchema.safeParse({ ...base, password: "long-enough-pass", confirmPassword: "long-enough-pass" }).success).toBe(true);
  });

  it("applies the same password rules to a reset", () => {
    expect(staffPasswordResetSchema.safeParse({ password: "short-pass1", confirmPassword: "short-pass1" }).success).toBe(false);
    const mismatch = staffPasswordResetSchema.safeParse({ password: "long-enough-pass", confirmPassword: "long-enough-pas" });
    expect(mismatch.error?.issues[0].path).toEqual(["confirmPassword"]);
    expect(staffPasswordResetSchema.safeParse({ password: "long-enough-pass", confirmPassword: "long-enough-pass" }).success).toBe(true);
  });

  it("requires a leave reason of 1–200 characters (POST /doctors/{id}/leaves refuses an empty one)", () => {
    expect(leaveFormSchema.safeParse({ date: "2030-01-09", reason: "   " }).success).toBe(false);
    expect(leaveFormSchema.safeParse({ date: "2030-01-09", reason: "x".repeat(201) }).success).toBe(false);
    expect(leaveFormSchema.safeParse({ date: "2030-01-09", reason: "Conference" }).success).toBe(true);
  });

  it("checks the settings time zone and part-of-day order", () => {
    const valid = {
      clinic_name: "Clinic",
      phone: "+91 1",
      address: "Road",
      staff_hours_text: "9-5",
      timezone: "Asia/Kolkata",
      emergency_number: "112",
      emergencyPhrasesText: "chest pain",
      cutoff_minutes: 120,
      booking_window_days: 30,
      max_upcoming_per_patient: 3,
      max_per_doctor_per_day: 1,
      morning_end: "12:00",
      afternoon_end: "17:00",
    };
    expect(settingsFormSchema.safeParse(valid).success).toBe(true);
    expect(settingsFormSchema.safeParse({ ...valid, timezone: "Mars/Olympus" }).success).toBe(false);
    expect(settingsFormSchema.safeParse({ ...valid, afternoon_end: "11:00" }).error?.issues[0].path).toEqual(["afternoon_end"]);
  });

  it("validates audit filters", () => {
    const base = { from: "", to: "", actor_type: "" as const, action: "", patient_id: "" };
    expect(auditFilterSchema.safeParse(base).success).toBe(true);
    expect(auditFilterSchema.safeParse({ ...base, from: "2030-01-10", to: "2030-01-01" }).success).toBe(false);
    expect(auditFilterSchema.safeParse({ ...base, patient_id: "123" }).success).toBe(false);
  });
});
