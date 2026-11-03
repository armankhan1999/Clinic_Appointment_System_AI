import { z } from "zod";

import type { ScheduleBlock } from "@/lib/api/schemas";
import { minutesOf, toHourMinute } from "@/lib/dates";

/*
 * Client-side mirror of PUT /doctors/{id}/schedule validation (E6-S3-AC1/AC2):
 * end > start, no overlapping blocks on the same weekday, slot length 5–120 minutes.
 * Blocks that touch (09:00–12:00 and 12:00–13:00) do not overlap; a gap is a break.
 * The API stays the authority; this only gives earlier, field-level feedback.
 */

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;
export const MIN_SLOT_MINUTES = 5;
export const MAX_SLOT_MINUTES = 120;
export const DEFAULT_SLOT_MINUTES = 15;

const timeField = z
  .string()
  .trim()
  .refine((value) => minutesOf(value) !== null, { message: "Enter a time like 09:00" });

export const blockFormSchema = z
  .object({
    start: timeField,
    end: timeField,
    slot_minutes: z
      .number({ error: "Enter the slot length in minutes" })
      .int({ message: "Use whole minutes" })
      .min(MIN_SLOT_MINUTES, { message: `Slots must be at least ${MIN_SLOT_MINUTES} minutes` })
      .max(MAX_SLOT_MINUTES, { message: `Slots can be at most ${MAX_SLOT_MINUTES} minutes` }),
  })
  .superRefine((block, ctx) => {
    const start = minutesOf(block.start);
    const end = minutesOf(block.end);
    if (start !== null && end !== null && end <= start) {
      ctx.addIssue({ code: "custom", path: ["end"], message: "End time must be after the start time" });
    }
  });

export type BlockForm = z.infer<typeof blockFormSchema>;

export const dayFormSchema = z.object({ blocks: z.array(blockFormSchema) }).superRefine((day, ctx) => {
  const ranges = day.blocks
    .map((block, index) => ({ index, start: minutesOf(block.start), end: minutesOf(block.end), block }))
    .filter((r): r is typeof r & { start: number; end: number } => r.start !== null && r.end !== null && r.end > r.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);

  const reported = new Set<number>();
  for (let i = 0; i < ranges.length; i += 1) {
    for (let j = i + 1; j < ranges.length; j += 1) {
      const a = ranges[i];
      const b = ranges[j];
      if (b.start >= a.end) break;
      if (reported.has(b.index)) continue;
      reported.add(b.index);
      ctx.addIssue({
        code: "custom",
        path: ["blocks", b.index, "start"],
        message: `Overlaps the ${a.block.start}–${a.block.end} block`,
      });
    }
  }
});

export const weeklyScheduleFormSchema = z.object({ days: z.array(dayFormSchema).length(7) });
export type WeeklyScheduleForm = z.infer<typeof weeklyScheduleFormSchema>;

export function emptyBlock(): BlockForm {
  return { start: "09:00", end: "13:00", slot_minutes: DEFAULT_SLOT_MINUTES };
}

/** API blocks (weekday 0 = Monday, as in the backend's `date.weekday()`) → editor rows per day. */
export function blocksToForm(blocks: ScheduleBlock[]): WeeklyScheduleForm {
  const days: WeeklyScheduleForm["days"] = WEEKDAYS.map(() => ({ blocks: [] }));
  for (const block of blocks) {
    if (block.weekday < 0 || block.weekday > 6) continue;
    days[block.weekday].blocks.push({
      start: toHourMinute(block.start),
      end: toHourMinute(block.end),
      slot_minutes: block.slot_minutes,
    });
  }
  for (const day of days) day.blocks.sort((a, b) => (minutesOf(a.start) ?? 0) - (minutesOf(b.start) ?? 0));
  return { days };
}

export function formToBlocks(form: WeeklyScheduleForm): ScheduleBlock[] {
  return form.days.flatMap((day, weekday) =>
    day.blocks
      .map((block) => ({ weekday, start: block.start.trim(), end: block.end.trim(), slot_minutes: block.slot_minutes }))
      .sort((a, b) => (minutesOf(a.start) ?? 0) - (minutesOf(b.start) ?? 0)),
  );
}

/** Minutes at the end of a block too short for a whole slot (the backend drops partial slots). */
export function leftoverMinutes(block: BlockForm): number {
  const start = minutesOf(block.start);
  const end = minutesOf(block.end);
  if (start === null || end === null || end <= start || !Number.isInteger(block.slot_minutes) || block.slot_minutes <= 0) {
    return 0;
  }
  return (end - start) % block.slot_minutes;
}
