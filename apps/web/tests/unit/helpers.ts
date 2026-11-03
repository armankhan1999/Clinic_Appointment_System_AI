import { vi } from "vitest";

export type StubbedCall = { url: string; method: string; headers: Record<string, string>; body: unknown };

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function errorEnvelope(code: string, message: string, extra: { request_id?: string; details?: unknown } = {}) {
  return { error: { code, message, request_id: extra.request_id ?? "req-123", details: extra.details ?? {} } };
}

/**
 * Stubs global fetch with a queue of responses (or a router function) and records
 * every call so tests can assert on method, URL, headers and body.
 */
export function stubFetch(responder: Response[] | ((call: StubbedCall) => Response | Promise<Response>)) {
  const calls: StubbedCall[] = [];
  const queue = Array.isArray(responder) ? [...responder] : null;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key.toLowerCase()] = value;
    });
    const call: StubbedCall = {
      url: String(input),
      method: init?.method ?? "GET",
      headers,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    if (queue) {
      const next = queue.shift();
      if (!next) throw new Error(`Unexpected fetch: ${call.method} ${call.url}`);
      return next;
    }
    return (responder as (c: StubbedCall) => Response | Promise<Response>)(call);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export const sessionBody = (role: "receptionist" | "admin" = "receptionist", csrf = "csrf-1") => ({
  user: { id: "u-1", username: "desk1", display_name: "Asha Desk", role, active: true },
  csrf_token: csrf,
});
