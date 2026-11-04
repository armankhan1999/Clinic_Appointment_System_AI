import { z } from "zod";

/*
 * Response shapes from docs/api/staff-api.md (v1). Responses are parsed, not
 * trusted: a contract drift fails loudly as BAD_RESPONSE instead of rendering
 * undefined fields. Unknown extra keys are ignored so additive API changes are safe.
 */

export const roleSchema = z.enum(["receptionist", "admin"]);
export type Role = z.infer<typeof roleSchema>;

export const staffUserSchema = z.object({
  id: z.string(),
  username: z.string(),
  display_name: z.string(),
  role: roleSchema,
  active: z.boolean(),
  /** Present on admin staff-user responses; null when not locked. Absent from /auth/me. */
  locked_until: z.string().nullish(),
});
export type StaffUser = z.infer<typeof staffUserSchema>;

export const clinicTodaySchema = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  timezone: z.string().min(1),
});
export type ClinicToday = z.infer<typeof clinicTodaySchema>;

export const sessionSchema = z.object({
  user: staffUserSchema,
  csrf_token: z.string().min(1),
});
export type Session = z.infer<typeof sessionSchema>;

export const patientRefSchema = z.object({
  id: z.string(),
  full_name: z.string(),
  phone: z.string().nullable(),
});
export type PatientRef = z.infer<typeof patientRefSchema>;

export const reminderStatusSchema = z.enum(["pending", "sent", "failed", "skipped"]).nullable();
export type ReminderStatus = z.infer<typeof reminderStatusSchema>;

export const appointmentStatusSchema = z.enum(["booked", "cancelled", "completed", "no_show"]);
export type AppointmentStatus = z.infer<typeof appointmentStatusSchema>;

export const appointmentSchema = z.object({
  id: z.string(),
  reference: z.string(),
  doctor_id: z.string(),
  doctor_name: z.string(),
  start: z.string(),
  end: z.string(),
  date: z.string(),
  time_label: z.string(),
  status: appointmentStatusSchema,
  source: z.enum(["bot", "staff"]),
  patient: patientRefSchema,
  reminders: z.object({ "24h": reminderStatusSchema, "2h": reminderStatusSchema }),
  patient_confirmed: z.boolean(),
  staff_attention: z.object({ reason: z.string(), at: z.string() }).nullable(),
  can_mark_attendance: z.boolean(),
});
export type Appointment = z.infer<typeof appointmentSchema>;

export const slotSchema = z.object({ start: z.string(), time_label: z.string() });
export type Slot = z.infer<typeof slotSchema>;

export const dayScheduleSchema = z.object({
  date: z.string(),
  doctors: z.array(
    z.object({
      doctor_id: z.string(),
      name: z.string(),
      specialty: z.string(),
      appointments: z.array(appointmentSchema),
    }),
  ),
});
export type DaySchedule = z.infer<typeof dayScheduleSchema>;

export const ticketSchema = z.object({
  id: z.string(),
  reason: z.string(),
  created_at: z.string(),
  patient: patientRefSchema,
});
export type Ticket = z.infer<typeof ticketSchema>;

export const emergencyAlertSchema = z.object({
  id: z.string(),
  created_at: z.string(),
  patient: patientRefSchema.nullable(),
  telegram_user_id: z.number().nullable(),
});
export type EmergencyAlert = z.infer<typeof emergencyAlertSchema>;

export const attentionSchema = z.object({
  tickets: z.array(ticketSchema),
  alerts: z.array(emergencyAlertSchema),
  flagged: z.array(appointmentSchema),
});
export type Attention = z.infer<typeof attentionSchema>;

export const doctorSchema = z.object({
  id: z.string(),
  name: z.string(),
  specialty: z.string(),
  active: z.boolean(),
});
export type Doctor = z.infer<typeof doctorSchema>;

export const doctorListSchema = z.object({ items: z.array(doctorSchema) });

export const availabilitySchema = z.object({ date: z.string(), slots: z.array(slotSchema) });
export type Availability = z.infer<typeof availabilitySchema>;

export const patientLookupSchema = z.object({ items: z.array(patientRefSchema) });

export const ticketResolvedSchema = z.object({
  id: z.string(),
  status: z.literal("resolved"),
  resolved_by: z.string(),
  resolved_at: z.string(),
});

export const alertAcknowledgedSchema = z.object({
  id: z.string(),
  acknowledged_by: z.string(),
  acknowledged_at: z.string(),
});

export const scheduleBlockSchema = z.object({
  weekday: z.number().int().min(0).max(6),
  start: z.string(),
  end: z.string(),
  slot_minutes: z.number().int(),
});
export type ScheduleBlock = z.infer<typeof scheduleBlockSchema>;

export const weeklyScheduleSchema = z.object({ blocks: z.array(scheduleBlockSchema) });
export type WeeklySchedule = z.infer<typeof weeklyScheduleSchema>;

export const leaveSchema = z.object({ id: z.string(), date: z.string(), reason: z.string() });
export type Leave = z.infer<typeof leaveSchema>;

export const leaveListSchema = z.object({ items: z.array(leaveSchema) });
export const leavePreviewSchema = z.object({ affected: z.array(appointmentSchema) });
export const leaveCreatedSchema = z.object({ leave: leaveSchema, cancelled: z.array(appointmentSchema) });

export const faqEntrySchema = z.object({
  id: z.string(),
  topic: z.string(),
  aliases: z.array(z.string()),
  answer: z.string(),
  updated_at: z.string(),
});
export type FaqEntry = z.infer<typeof faqEntrySchema>;

export function pageOf<T extends z.ZodType>(item: T) {
  return z.object({
    items: z.array(item),
    page: z.number().int(),
    page_size: z.number().int(),
    total: z.number().int(),
  });
}
export type Page<T> = { items: T[]; page: number; page_size: number; total: number };

/*
 * The contract says "settings object"; field names follow the clinic_settings
 * table (apps/backend/src/clinic/db/models.py, IMP-05). Times are accepted as
 * HH:MM or HH:MM:SS because Python serialises `time` with seconds.
 */
export const clinicSettingsSchema = z.object({
  clinic_name: z.string(),
  phone: z.string(),
  address: z.string(),
  staff_hours_text: z.string(),
  timezone: z.string(),
  emergency_number: z.string(),
  emergency_phrases: z.array(z.string()),
  cutoff_minutes: z.number().int(),
  booking_window_days: z.number().int(),
  max_upcoming_per_patient: z.number().int(),
  max_per_doctor_per_day: z.number().int(),
  morning_end: z.string(),
  afternoon_end: z.string(),
  updated_at: z.string().nullish(),
});
export type ClinicSettings = z.infer<typeof clinicSettingsSchema>;

export const actorTypeSchema = z.enum(["agent", "staff", "system", "patient_button"]);
export type ActorType = z.infer<typeof actorTypeSchema>;

export const auditEntrySchema = z.object({
  id: z.union([z.string(), z.number()]),
  ts: z.string(),
  actor_type: z.string(),
  actor_id: z.string().nullable(),
  patient_id: z.string().nullable(),
  action: z.string(),
  args: z.unknown(),
  result: z.string().nullable(),
  latency_ms: z.number().nullable(),
  request_id: z.string().nullable(),
});
export type AuditEntry = z.infer<typeof auditEntrySchema>;

export const weeklyMetricsSchema = z.object({
  week_start: z.string(),
  bookings_by_source: z.object({ bot: z.number(), staff: z.number() }),
  cancellations: z.number(),
  per_doctor: z.array(
    z.object({
      doctor_id: z.string(),
      name: z.string(),
      completed: z.number(),
      no_show: z.number(),
      no_show_rate: z.number(),
    }),
  ),
});
export type WeeklyMetrics = z.infer<typeof weeklyMetricsSchema>;
