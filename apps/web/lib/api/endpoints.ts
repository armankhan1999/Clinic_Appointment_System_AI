import type { z } from "zod";

import { apiRequest, apiRequestNoContent, setCsrfToken } from "./client";
import {
  alertAcknowledgedSchema,
  appointmentSchema,
  attentionSchema,
  clinicTodaySchema,
  auditEntrySchema,
  availabilitySchema,
  clinicSettingsSchema,
  dayScheduleSchema,
  doctorListSchema,
  doctorSchema,
  faqEntrySchema,
  leaveCreatedSchema,
  leaveListSchema,
  leavePreviewSchema,
  pageOf,
  patientLookupSchema,
  sessionSchema,
  staffUserSchema,
  ticketResolvedSchema,
  weeklyMetricsSchema,
  weeklyScheduleSchema,
  type ActorType,
  type ClinicSettings,
  type Role,
  type ScheduleBlock,
} from "./schemas";

/* Auth (E6-S1) */

export async function login(username: string, password: string) {
  const session = await apiRequest("/auth/login", sessionSchema, {
    method: "POST",
    body: { username, password },
    csrf: false,
    redirectOn401: false,
  });
  setCsrfToken(session.csrf_token);
  return session;
}

export async function logout() {
  await apiRequestNoContent("/auth/logout", { method: "POST" });
  setCsrfToken(null);
}

/* Daily work */

export const getDaySchedule = (date: string, signal?: AbortSignal) =>
  apiRequest("/schedule", dayScheduleSchema, { query: { date }, signal });

export const getClinicToday = (signal?: AbortSignal) => apiRequest("/clinic/today", clinicTodaySchema, { signal });

export const getAttention = (signal?: AbortSignal) => apiRequest("/attention", attentionSchema, { signal });

export const getDoctors = (filter: { active?: boolean } = {}, signal?: AbortSignal) =>
  apiRequest("/doctors", doctorListSchema, { query: { active: filter.active }, signal });

export const getAvailability = (doctorId: string, date: string, signal?: AbortSignal) =>
  apiRequest("/availability", availabilitySchema, { query: { doctor_id: doctorId, date }, signal });

/** The phone number goes in a POST body so it never appears in a URL that proxies or browsers may log. */
export const findPatientsByPhone = (phone: string, signal?: AbortSignal) =>
  apiRequest("/patients/lookup", patientLookupSchema, { method: "POST", body: { phone }, signal });

export type NewAppointmentPatient = { id: string } | { full_name: string; phone: string; verbal_consent: true };

export const createAppointment = (input: { doctor_id: string; start: string; patient: NewAppointmentPatient }) =>
  apiRequest("/appointments", appointmentSchema, { method: "POST", body: input });

export const cancelAppointment = (id: string, reason: string) =>
  apiRequest(`/appointments/${encodeURIComponent(id)}/cancel`, appointmentSchema, {
    method: "POST",
    body: { reason },
  });

export const markAttendance = (id: string, status: "completed" | "no_show") =>
  apiRequest(`/appointments/${encodeURIComponent(id)}/attendance`, appointmentSchema, {
    method: "POST",
    body: { status },
  });

export const clearAttention = (id: string) =>
  apiRequest(`/appointments/${encodeURIComponent(id)}/clear-attention`, appointmentSchema, { method: "POST" });

export const resolveTicket = (id: string) =>
  apiRequest(`/tickets/${encodeURIComponent(id)}/resolve`, ticketResolvedSchema, { method: "POST" });

export const acknowledgeAlert = (id: string) =>
  apiRequest(`/alerts/${encodeURIComponent(id)}/acknowledge`, alertAcknowledgedSchema, { method: "POST" });

/* Administration: doctors, schedules, leave */

export const createDoctor = (input: { name: string; specialty: string }) =>
  apiRequest("/doctors", doctorSchema, { method: "POST", body: input });

export const updateDoctor = (id: string, input: { name?: string; specialty?: string; active?: boolean }) =>
  apiRequest(`/doctors/${encodeURIComponent(id)}`, doctorSchema, { method: "PATCH", body: input });

export const getWeeklySchedule = (doctorId: string, signal?: AbortSignal) =>
  apiRequest(`/doctors/${encodeURIComponent(doctorId)}/schedule`, weeklyScheduleSchema, { signal });

export const saveWeeklySchedule = (doctorId: string, blocks: ScheduleBlock[]) =>
  apiRequest(`/doctors/${encodeURIComponent(doctorId)}/schedule`, weeklyScheduleSchema, {
    method: "PUT",
    body: { blocks },
  });

export const getLeaves = (doctorId: string, signal?: AbortSignal) =>
  apiRequest(`/doctors/${encodeURIComponent(doctorId)}/leaves`, leaveListSchema, { signal });

export const previewLeave = (doctorId: string, date: string) =>
  apiRequest(`/doctors/${encodeURIComponent(doctorId)}/leaves/preview`, leavePreviewSchema, {
    method: "POST",
    body: { date },
  });

export const createLeave = (doctorId: string, input: { date: string; reason: string; confirm_affected: boolean }) =>
  apiRequest(`/doctors/${encodeURIComponent(doctorId)}/leaves`, leaveCreatedSchema, {
    method: "POST",
    body: input,
  });

export const deleteLeave = (doctorId: string, leaveId: string) =>
  apiRequestNoContent(`/doctors/${encodeURIComponent(doctorId)}/leaves/${encodeURIComponent(leaveId)}`, {
    method: "DELETE",
  });

/* Administration: FAQ, settings, audit, metrics, staff */

export const MAX_PAGE_SIZE = 100;
/** Safety stop for whole-list reads: 5,000 rows is far beyond one clinic's FAQ or staff list. */
const MAX_LIST_PAGES = 50;

/**
 * Reads every page of a small paginated list (FAQ entries, staff accounts) so nothing past
 * the API's 100-per-page maximum is silently dropped. Stops at `total`, on an empty page, or
 * at MAX_LIST_PAGES.
 */
async function getAllPages<S extends z.ZodType>(path: string, item: S, signal?: AbortSignal) {
  const schema = pageOf(item);
  const items: z.infer<S>[] = [];
  let total = 0;
  for (let page = 1; page <= MAX_LIST_PAGES; page += 1) {
    const result = await apiRequest(path, schema, { query: { page, page_size: MAX_PAGE_SIZE }, signal });
    items.push(...result.items);
    total = result.total;
    if (result.items.length === 0 || items.length >= total) break;
  }
  return { items, total };
}

export const getFaqEntries = (signal?: AbortSignal) => getAllPages("/faq", faqEntrySchema, signal);

export type FaqInput = { topic: string; aliases: string[]; answer: string };

export const createFaqEntry = (input: FaqInput) =>
  apiRequest("/faq", faqEntrySchema, { method: "POST", body: input });

export const updateFaqEntry = (id: string, input: Partial<FaqInput>) =>
  apiRequest(`/faq/${encodeURIComponent(id)}`, faqEntrySchema, { method: "PATCH", body: input });

export const deleteFaqEntry = (id: string) =>
  apiRequestNoContent(`/faq/${encodeURIComponent(id)}`, { method: "DELETE" });

export const getSettings = (signal?: AbortSignal) => apiRequest("/settings", clinicSettingsSchema, { signal });

export const updateSettings = (changes: Partial<ClinicSettings>) =>
  apiRequest("/settings", clinicSettingsSchema, { method: "PATCH", body: changes });

export type AuditFilters = {
  from?: string;
  to?: string;
  actor_type?: ActorType | "";
  action?: string;
  patient_id?: string;
  page: number;
};

export const AUDIT_PAGE_SIZE = 50;

export const getAuditLog = (filters: AuditFilters, signal?: AbortSignal) =>
  apiRequest("/audit", pageOf(auditEntrySchema), {
    query: { ...filters, page_size: AUDIT_PAGE_SIZE },
    signal,
  });

export const getWeeklyMetrics = (weekStart: string, signal?: AbortSignal) =>
  apiRequest("/metrics/weekly", weeklyMetricsSchema, { query: { week_start: weekStart }, signal });

export const getStaffUsers = (signal?: AbortSignal) =>
  getAllPages("/staff-users", staffUserSchema, signal);

export const createStaffUser = (input: { username: string; display_name: string; role: Role; password: string }) =>
  apiRequest("/staff-users", staffUserSchema, { method: "POST", body: input });

/** A `password` resets it and signs the user out everywhere (IMP-04). */
export const updateStaffUser = (id: string, input: { display_name?: string; role?: Role; active?: boolean; password?: string }) =>
  apiRequest(`/staff-users/${encodeURIComponent(id)}`, staffUserSchema, { method: "PATCH", body: input });

export const unlockStaffUser = (id: string) =>
  apiRequest(`/staff-users/${encodeURIComponent(id)}/unlock`, staffUserSchema, { method: "POST" });
