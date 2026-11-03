import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import {
  apiRequest,
  buildUrl,
  errorFromResponse,
  fetchSession,
  getCsrfToken,
  setCsrfToken,
  setUnauthenticatedHandler,
} from "@/lib/api/client";
import { cancelAppointment, login, logout } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";

import { errorEnvelope, jsonResponse, sessionBody, stubFetch } from "./helpers";

const okSchema = z.object({ ok: z.boolean() });

describe("buildUrl", () => {
  it("prefixes the API base and skips empty query values", () => {
    expect(buildUrl("/audit", { page: 2, action: "", actor_type: undefined, patient_id: null, from: "2030-01-01" })).toBe(
      "/api/v1/audit?page=2&from=2030-01-01",
    );
  });
});

describe("error envelope parsing", () => {
  it("turns the contract envelope into a typed ApiError with request id and details", () => {
    const error = errorFromResponse(
      409,
      errorEnvelope("SLOT_TAKEN", "That slot was just taken", { request_id: "abc-123", details: { slot: "x" } }),
      "header-id",
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.code).toBe("SLOT_TAKEN");
    expect(error.message).toBe("That slot was just taken");
    expect(error.requestId).toBe("abc-123");
    expect(error.details).toEqual({ slot: "x" });
  });

  it("exposes validation field paths and lockout time", () => {
    const validation = errorFromResponse(422, errorEnvelope("VALIDATION_ERROR", "bad", { details: { fields: ["body.reason"] } }), null);
    expect(validation.fields).toEqual(["body.reason"]);

    const locked = errorFromResponse(423, errorEnvelope("ACCOUNT_LOCKED", "locked", { details: { locked_until: "2030-01-01T04:15:00Z" } }), null);
    expect(locked.lockedUntil).toBe("2030-01-01T04:15:00Z");
  });

  it("falls back to a status-based code and the header request id when the body is not an envelope", () => {
    const error = errorFromResponse(429, "<html>Too many</html>", "hdr-1");
    expect(error.code).toBe("RATE_LIMITED");
    expect(error.requestId).toBe("hdr-1");
    expect(error.message).toMatch(/too many attempts/i);
  });

  it("explains an unreachable server when a 5xx has no envelope (API process down behind the rewrite)", () => {
    const error = errorFromResponse(500, undefined, null);
    expect(error.code).toBe("ERROR");
    expect(error.message).toMatch(/isn't answering/);
  });

  it("uses the server message, or a friendly default when the message is blank", () => {
    expect(errorFromResponse(403, errorEnvelope("FORBIDDEN", ""), null).message).toMatch(/isn't allowed/);
  });
});

describe("apiRequest", () => {
  it("returns schema-validated data for a 2xx JSON response", async () => {
    const { calls } = stubFetch([jsonResponse(200, { ok: true })]);
    await expect(apiRequest("/thing", okSchema)).resolves.toEqual({ ok: true });
    expect(calls[0].url).toBe("/api/v1/thing");
    expect(calls[0].headers["x-csrf-token"]).toBeUndefined();
  });

  it("throws BAD_RESPONSE without logging response values when the body breaks the contract", async () => {
    stubFetch([jsonResponse(200, { ok: "Priya Sharma +919876543210" }, { "X-Request-ID": "rid-9" })]);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const error = await apiRequest("/patients", okSchema, { query: { phone: "+919876543210" } }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("BAD_RESPONSE");
    expect((error as ApiError).requestId).toBe("rid-9");
    const logged = JSON.stringify(consoleError.mock.calls);
    expect(logged).not.toContain("Priya");
    expect(logged).not.toContain("9876543210");
  });

  it("maps a network failure to NETWORK_ERROR", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(apiRequest("/thing", okSchema)).rejects.toMatchObject({ code: "NETWORK_ERROR", status: 0 });
  });

  it("aborts slow requests with a TIMEOUT error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
      ),
    );
    await expect(apiRequest("/slow", okSchema, { timeoutMs: 10 })).rejects.toMatchObject({ code: "TIMEOUT" });
  });

  it("calls the unauthenticated handler on 401 and clears the CSRF token", async () => {
    setCsrfToken("old");
    const handler = vi.fn();
    setUnauthenticatedHandler(handler);
    stubFetch([jsonResponse(401, errorEnvelope("UNAUTHENTICATED", "Session expired"))]);
    await expect(apiRequest("/schedule", okSchema)).rejects.toMatchObject({ code: "UNAUTHENTICATED" });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(getCsrfToken()).toBeNull();
  });
});

describe("CSRF handling", () => {
  it("sends X-CSRF-Token on writes, fetching it from /auth/me first when missing", async () => {
    const { calls } = stubFetch([jsonResponse(200, sessionBody("receptionist", "tok-A")), jsonResponse(200, appointmentFixture())]);
    await cancelAppointment("apt-1", "Doctor unwell");
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["GET /api/v1/auth/me", "POST /api/v1/appointments/apt-1/cancel"]);
    expect(calls[1].headers["x-csrf-token"]).toBe("tok-A");
    expect(calls[1].headers["content-type"]).toBe("application/json");
    expect(calls[1].body).toEqual({ reason: "Doctor unwell" });
  });

  it("does not send a CSRF token on GET requests", async () => {
    setCsrfToken("tok-A");
    const { calls } = stubFetch([jsonResponse(200, { ok: true })]);
    await apiRequest("/attention", okSchema);
    expect(calls[0].headers["x-csrf-token"]).toBeUndefined();
  });

  it("refreshes a stale token once after a 403 and retries the write", async () => {
    setCsrfToken("stale");
    const { calls } = stubFetch([
      jsonResponse(403, errorEnvelope("FORBIDDEN", "CSRF token missing or invalid")),
      jsonResponse(200, sessionBody("receptionist", "fresh")),
      jsonResponse(200, appointmentFixture()),
    ]);
    await cancelAppointment("apt-1", "Clinic closed");
    expect(calls.map((c) => c.headers["x-csrf-token"] ?? "-")).toEqual(["stale", "-", "fresh"]);
  });

  it("surfaces FORBIDDEN when the retry is also refused (wrong role)", async () => {
    setCsrfToken("tok");
    const { calls } = stubFetch([
      jsonResponse(403, errorEnvelope("FORBIDDEN", "Admins only")),
      jsonResponse(200, sessionBody("receptionist", "tok2")),
      jsonResponse(403, errorEnvelope("FORBIDDEN", "Admins only", { request_id: "r-final" })),
    ]);
    await expect(cancelAppointment("apt-1", "x")).rejects.toMatchObject({ code: "FORBIDDEN", requestId: "r-final" });
    expect(calls).toHaveLength(3);
  });

  it("login sends no CSRF token, stores the returned one, and treats 401 as wrong credentials (no redirect)", async () => {
    const handler = vi.fn();
    setUnauthenticatedHandler(handler);
    const { calls } = stubFetch([
      jsonResponse(401, errorEnvelope("UNAUTHENTICATED", "Invalid username or password")),
      jsonResponse(200, sessionBody("admin", "tok-login")),
    ]);
    await expect(login("desk1", "wrong")).rejects.toMatchObject({ code: "UNAUTHENTICATED" });
    expect(handler).not.toHaveBeenCalled();
    await login("desk1", "right-password");
    expect(calls[1].headers["x-csrf-token"]).toBeUndefined();
    expect(getCsrfToken()).toBe("tok-login");
  });

  it("fetchSession stores the CSRF token and logout clears it after a 204", async () => {
    const { calls } = stubFetch([jsonResponse(200, sessionBody("admin", "tok-me")), new Response(null, { status: 204 })]);
    await fetchSession();
    expect(getCsrfToken()).toBe("tok-me");
    await logout();
    expect(calls[1].headers["x-csrf-token"]).toBe("tok-me");
    expect(getCsrfToken()).toBeNull();
  });
});

function appointmentFixture() {
  return {
    id: "apt-1",
    reference: "APT-000123",
    doctor_id: "d-1",
    doctor_name: "Dr Rao",
    start: "2030-01-09T04:00:00Z",
    end: "2030-01-09T04:15:00Z",
    date: "2030-01-09",
    time_label: "9:30 AM",
    status: "cancelled",
    source: "bot",
    patient: { id: "p-1", full_name: "Test Patient", phone: "+910000000000" },
    reminders: { "24h": null, "2h": null },
    patient_confirmed: false,
    staff_attention: null,
    can_mark_attendance: false,
  };
}
