import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils";

describe("cn (class-name merging)", () => {
  it("lets a later Tailwind utility override a conflicting earlier one", () => {
    expect(cn("px-2 py-1", "px-4")).toBe("py-1 px-4");
    expect(cn("text-sm text-red-500", "text-blue-600")).toBe("text-sm text-blue-600");
  });

  it("drops falsy values and flattens arrays and objects", () => {
    const disabled = false;
    expect(cn("rounded", disabled && "opacity-50", ["font-bold", { underline: true, italic: false }])).toBe(
      "rounded font-bold underline",
    );
  });
});
