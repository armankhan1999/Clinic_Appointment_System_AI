import { describe, expect, it } from "vitest";

import { getFaqEntries, getStaffUsers } from "@/lib/api/endpoints";

import { jsonResponse, stubFetch, type StubbedCall } from "./helpers";

/* M4: the FAQ and staff lists must not stop silently at the API's 100-per-page maximum. */

function pagedResponder<T>(all: T[], pathPrefix: string) {
  return (call: StubbedCall) => {
    const url = new URL(call.url, "http://localhost");
    if (!url.pathname.startsWith(pathPrefix)) throw new Error(`unexpected ${call.url}`);
    const page = Number(url.searchParams.get("page"));
    const size = Number(url.searchParams.get("page_size"));
    return jsonResponse(200, { items: all.slice((page - 1) * size, page * size), page, page_size: size, total: all.length });
  };
}

const faq = (i: number) => ({ id: `f-${i}`, topic: `topic_${i}`, aliases: [], answer: "A", updated_at: "2030-01-09T04:00:00Z" });
const staff = (i: number) => ({ id: `u-${i}`, username: `user${i}`, display_name: `User ${i}`, role: "receptionist", active: true, locked_until: null });

describe("lists fetch every page", () => {
  it("FAQ: 150 entries over two pages", async () => {
    const { calls } = stubFetch(pagedResponder(Array.from({ length: 150 }, (_, i) => faq(i)), "/api/v1/faq"));
    const result = await getFaqEntries();
    expect(result.items).toHaveLength(150);
    expect(result.items[149].id).toBe("f-149");
    expect(calls.map((c) => new URL(c.url, "http://localhost").searchParams.get("page"))).toEqual(["1", "2"]);
  });

  it("staff users: 201 accounts over three pages", async () => {
    const { calls } = stubFetch(pagedResponder(Array.from({ length: 201 }, (_, i) => staff(i)), "/api/v1/staff-users"));
    const result = await getStaffUsers();
    expect(result.items).toHaveLength(201);
    expect(calls).toHaveLength(3);
  });

  it("a single page makes a single request", async () => {
    const { calls } = stubFetch(pagedResponder([faq(1), faq(2)], "/api/v1/faq"));
    expect((await getFaqEntries()).items).toHaveLength(2);
    expect(calls).toHaveLength(1);
  });

  it("stops if the server returns an empty page before reaching total (no endless loop)", async () => {
    const { calls } = stubFetch((call: StubbedCall) => {
      const page = Number(new URL(call.url, "http://localhost").searchParams.get("page"));
      return jsonResponse(200, { items: page === 1 ? [faq(1)] : [], page, page_size: 100, total: 500 });
    });
    expect((await getFaqEntries()).items).toHaveLength(1);
    expect(calls).toHaveLength(2);
  });
});
