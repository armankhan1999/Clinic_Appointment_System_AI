/*
 * Date helpers. Appointment times always come from the API's clinic-time labels
 * (`time_label`, `date`); nothing here converts between time zones. Calendar
 * dates (YYYY-MM-DD) are handled as UTC midnight purely for arithmetic.
 */

export const APP_LOCALE = "en-IN";

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function isIsoDate(value: string): boolean {
  const match = ISO_DATE.exec(value);
  if (!match) return false;
  const [, y, m, d] = match.map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

function toUtcDate(iso: string): Date {
  if (!isIsoDate(iso)) throw new RangeError(`Not a calendar date: ${iso}`);
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function fromUtcDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Today's calendar date on this computer (the front-desk PC runs in clinic time). */
export function todayIso(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function addDays(iso: string, days: number): string {
  const date = toUtcDate(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return fromUtcDate(date);
}

/** Monday of the ISO week containing `iso`. */
export function mondayOf(iso: string): string {
  const date = toUtcDate(iso);
  const offset = (date.getUTCDay() + 6) % 7;
  return addDays(iso, -offset);
}

const longDate = new Intl.DateTimeFormat(APP_LOCALE, {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const shortDate = new Intl.DateTimeFormat(APP_LOCALE, {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

/** "Tuesday, 3 November 2026" for a YYYY-MM-DD calendar date. */
export function formatLongDate(iso: string): string {
  return isIsoDate(iso) ? longDate.format(toUtcDate(iso)) : iso;
}

/** "Tue, 3 Nov" for a YYYY-MM-DD calendar date. */
export function formatShortDate(iso: string): string {
  return isIsoDate(iso) ? shortDate.format(toUtcDate(iso)) : iso;
}

const utcTimestamp = new Intl.DateTimeFormat(APP_LOCALE, {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
  timeZoneName: "short",
});

/** Formats a UTC instant explicitly in UTC (no browser time-zone conversion). */
export function formatUtcTimestamp(isoInstant: string): string {
  const date = new Date(isoInstant);
  return Number.isNaN(date.getTime()) ? isoInstant : utcTimestamp.format(date);
}

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "5 minutes ago" / "in 12 minutes": an elapsed duration, so no time zone is involved. */
export function formatRelative(isoInstant: string, now: Date = new Date()): string {
  const then = new Date(isoInstant).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((then - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return seconds <= 0 ? "just now" : "in a few seconds";
  if (abs < 45 * 60) return relative.format(Math.round(seconds / 60), "minute");
  if (abs < 22 * 3600) return relative.format(Math.round(seconds / 3600), "hour");
  return relative.format(Math.round(seconds / 86400), "day");
}

/** Normalises "09:30" or "09:30:00" to "09:30"; returns the input unchanged if it is neither. */
export function toHourMinute(value: string): string {
  const match = /^(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/.exec(value);
  return match ? `${match[1]}:${match[2]}` : value;
}

/** Minutes since midnight for "HH:MM", or null if malformed. */
export function minutesOf(value: string): number | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value);
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}
