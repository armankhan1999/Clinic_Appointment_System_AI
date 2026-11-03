import {
  BellRing,
  CalendarClock,
  CheckCheck,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  ConciergeBell,
  MessageCircle,
  MinusCircle,
  PhoneCall,
  TriangleAlert,
  UserX,
  type LucideIcon,
} from "lucide-react";

import type { Appointment, AppointmentStatus, ReminderStatus } from "@/lib/api/schemas";
import { cn } from "cn";

/*
 * Status semantics (docs/design/design-system.md): every state has a text label
 * and an icon; colour is a third, redundant cue and never the only one.
 */

type Tone = "booked" | "completed" | "cancelled" | "no-show" | "attention" | "emergency" | "neutral";

const TONE_CLASSES: Record<Tone, string> = {
  booked: "bg-status-booked-bg text-status-booked border-status-booked-edge/40",
  completed: "bg-status-completed-bg text-status-completed border-status-completed-edge/40",
  cancelled: "bg-status-cancelled-bg text-status-cancelled border-status-cancelled-edge/50",
  "no-show": "bg-status-no-show-bg text-status-no-show border-status-no-show-edge/40",
  attention: "bg-status-attention-bg text-status-attention border-status-attention-edge/50",
  emergency: "bg-status-emergency-bg text-status-emergency border-status-emergency-edge/40",
  neutral: "bg-card text-muted-foreground border-border",
};

export const STATUS_EDGE: Record<AppointmentStatus, string> = {
  booked: "border-l-status-booked-edge",
  completed: "border-l-status-completed-edge",
  cancelled: "border-l-status-cancelled-edge",
  no_show: "border-l-status-no-show-edge",
};

export function Pill({ tone, icon: Icon, children, className }: { tone: Tone; icon?: LucideIcon; children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1 rounded-full border px-2 text-caption font-semibold whitespace-nowrap",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {Icon ? <Icon aria-hidden className="size-3.5 shrink-0" /> : null}
      {children}
    </span>
  );
}

const STATUS: Record<AppointmentStatus, { label: string; tone: Tone; icon: LucideIcon }> = {
  booked: { label: "Booked", tone: "booked", icon: CalendarClock },
  completed: { label: "Completed", tone: "completed", icon: CircleCheck },
  cancelled: { label: "Cancelled", tone: "cancelled", icon: CircleX },
  no_show: { label: "No-show", tone: "no-show", icon: UserX },
};

export function StatusPill({ status }: { status: AppointmentStatus }) {
  const s = STATUS[status];
  return (
    <Pill tone={s.tone} icon={s.icon}>
      {s.label}
    </Pill>
  );
}

export function SourcePill({ source }: { source: Appointment["source"] }) {
  return source === "bot" ? (
    <Pill tone="neutral" icon={MessageCircle}>
      <span className="sr-only">Booked via </span>Telegram
    </Pill>
  ) : (
    <Pill tone="neutral" icon={ConciergeBell}>
      <span className="sr-only">Booked at the </span>Front desk
    </Pill>
  );
}

const REMINDER: Record<NonNullable<ReminderStatus> | "none", { label: string; icon: LucideIcon; tone: Tone }> = {
  none: { label: "not due yet", icon: CircleDashed, tone: "neutral" },
  pending: { label: "queued", icon: Clock, tone: "neutral" },
  sent: { label: "sent", icon: BellRing, tone: "booked" },
  failed: { label: "failed", icon: TriangleAlert, tone: "attention" },
  skipped: { label: "skipped", icon: MinusCircle, tone: "neutral" },
};

export function ReminderPill({ window, status }: { window: "24h" | "2h"; status: ReminderStatus }) {
  const r = REMINDER[status ?? "none"];
  return (
    <Pill tone={r.tone} icon={r.icon} className="font-normal">
      <span>
        {window === "24h" ? "24 h" : "2 h"} reminder {r.label}
      </span>
    </Pill>
  );
}

export function ConfirmedPill() {
  return (
    <Pill tone="booked" icon={CheckCheck}>
      Patient confirmed
    </Pill>
  );
}

export function AttentionPill() {
  return (
    <Pill tone="attention" icon={PhoneCall}>
      Needs a call
    </Pill>
  );
}

const ATTENTION_REASONS: Record<string, string> = {
  notification_failed: "Couldn't deliver the Telegram message to the patient",
  reminder_failed: "Reminder couldn't be delivered",
};

const TICKET_REASONS: Record<string, string> = {
  patient_requested: "Patient asked to talk to a person",
  agent_failed: "The assistant couldn't help with the request",
  registration_conflict: "Problem registering the patient's phone number",
  change_within_cutoff: "Wants to change an appointment that is too close to change online",
  other: "Needs help from the front desk",
};

function humanize(code: string): string {
  const text = code.replace(/_/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "No reason given";
}

/** Plain-language text for reason codes; unknown codes are shown readably instead of hidden. */
export function attentionReasonText(reason: string): string {
  return ATTENTION_REASONS[reason] ?? humanize(reason);
}

export function ticketReasonText(reason: string): string {
  return TICKET_REASONS[reason] ?? humanize(reason);
}
