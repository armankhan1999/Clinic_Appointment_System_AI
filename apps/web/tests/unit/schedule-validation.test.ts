import { describe, expect, it } from "vitest";

import {
  blocksToForm,
  dayFormSchema,
  formToBlocks,
  leftoverMinutes,
  weeklyScheduleFormSchema,
  type BlockForm,
} from "@/lib/validation/schedule";

const block = (start: string, end: string, slot_minutes = 15): BlockForm => ({ start, end, slot_minutes });

function issuesFor(blocks: BlockForm[]) {
  const result = dayFormSchema.safeParse({ blocks });
  return result.success ? [] : result.error.issues.map((i) => ({ path: i.path.join("."), message: i.message }));
}

describe("schedule block rules (E6-S3-AC2)", () => {
  it("accepts a morning and afternoon block with a lunch break", () => {
    expect(issuesFor([block("09:00", "13:00"), block("14:00", "17:30", 20)])).toEqual([]);
  });

  it("accepts blocks that touch end-to-start", () => {
    expect(issuesFor([block("09:00", "12:00"), block("12:00", "13:00")])).toEqual([]);
  });

  it("rejects an end time equal to the start time", () => {
    expect(issuesFor([block("09:00", "09:00")])).toEqual([
      { path: "blocks.0.end", message: "End time must be after the start time" },
    ]);
  });

  it("rejects an end time before the start time", () => {
    expect(issuesFor([block("17:00", "09:00")])[0]).toMatchObject({ path: "blocks.0.end" });
  });

  it("rejects overlapping blocks on the same day and points at the later block", () => {
    expect(issuesFor([block("13:00", "17:00"), block("09:00", "13:30")])).toEqual([
      { path: "blocks.0.start", message: "Overlaps the 09:00–13:30 block" },
    ]);
  });

  it("rejects a block fully inside another", () => {
    expect(issuesFor([block("09:00", "17:00"), block("10:00", "11:00")])).toEqual([
      { path: "blocks.1.start", message: "Overlaps the 09:00–17:00 block" },
    ]);
  });

  it("reports each overlapping block once", () => {
    const issues = issuesFor([block("09:00", "12:00"), block("10:00", "13:00"), block("11:00", "14:00")]);
    expect(issues.map((i) => i.path)).toEqual(["blocks.1.start", "blocks.2.start"]);
  });

  it.each([
    [4, "Slots must be at least 5 minutes"],
    [121, "Slots can be at most 120 minutes"],
    [7.5, "Use whole minutes"],
  ])("rejects a slot length of %s minutes", (minutes, message) => {
    expect(issuesFor([block("09:00", "12:00", minutes)])).toEqual([{ path: "blocks.0.slot_minutes", message }]);
  });

  it("accepts the slot length bounds 5 and 120", () => {
    expect(issuesFor([block("09:00", "12:00", 5), block("13:00", "17:00", 120)])).toEqual([]);
  });

  it("rejects malformed times", () => {
    expect(issuesFor([block("9am", "12:00")])).toEqual([{ path: "blocks.0.start", message: "Enter a time like 09:00" }]);
  });

  it("does not compare blocks across different weekdays", () => {
    const days = Array.from({ length: 7 }, () => ({ blocks: [] as BlockForm[] }));
    days[0].blocks.push(block("09:00", "12:00"));
    days[1].blocks.push(block("10:00", "11:00"));
    expect(weeklyScheduleFormSchema.safeParse({ days }).success).toBe(true);
  });
});

describe("API ↔ editor conversion", () => {
  it("groups blocks by weekday (0 = Monday), sorts them and trims seconds", () => {
    const form = blocksToForm([
      { weekday: 0, start: "14:00:00", end: "17:00:00", slot_minutes: 15 },
      { weekday: 0, start: "09:00", end: "13:00", slot_minutes: 15 },
      { weekday: 6, start: "10:00", end: "12:00", slot_minutes: 30 },
    ]);
    expect(form.days).toHaveLength(7);
    expect(form.days[0].blocks.map((b) => b.start)).toEqual(["09:00", "14:00"]);
    expect(form.days[6].blocks).toEqual([{ start: "10:00", end: "12:00", slot_minutes: 30 }]);
    expect(form.days[3].blocks).toEqual([]);
  });

  it("round-trips back to API blocks", () => {
    const blocks = [
      { weekday: 0, start: "09:00", end: "13:00", slot_minutes: 15 },
      { weekday: 2, start: "10:00", end: "12:00", slot_minutes: 20 },
    ];
    expect(formToBlocks(blocksToForm(blocks))).toEqual(blocks);
  });

  it("reports minutes left over that cannot fit a whole slot", () => {
    expect(leftoverMinutes(block("09:00", "10:00", 25))).toBe(10);
    expect(leftoverMinutes(block("09:00", "10:00", 15))).toBe(0);
  });
});
