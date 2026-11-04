import { z } from "zod";

import { ApiError } from "./errors";
import { sessionSchema, type Session } from "./schemas";

/*
 * Same-origin client for the staff API. The browser only ever calls the Next.js
 * origin; next.config rewrites /api/v1/* to FastAPI. The session lives in an
 * HttpOnly cookie that JavaScript cannot read; the CSRF token is kept in memory
 * only (never localStorage/sessionStorage) and re-read from GET /auth/me.
 */

export const API_BASE = "/api/v1";
const DEFAULT_TIMEOUT_MS = 15_000;
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: Method;
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** False for POST /auth/login, where 401 means wrong credentials rather than an expired session. */
  redirectOn401?: boolean;
  /** False for POST /auth/login, which happens before a CSRF token exists. */
  csrf?: boolean;
}

/*
 * Reads sent without user input in the last minute (the 30 s auto-refresh on an
 * unattended screen) are marked as background, so they do not keep the session's
 * 60-minute idle timeout from expiring.
 */
const BACKGROUND_AFTER_MS = 60_000;
let lastUserInput = Date.now();

export function noteUserInput(at: number = Date.now()): void {
  lastUserInput = at;
}

if (typeof window !== "undefined") {
  for (const type of ["pointerdown", "keydown", "wheel", "touchstart"] as const) {
    window.addEventListener(type, () => noteUserInput(), { capture: true, passive: true });
  }
}

let csrfToken: string | null = null;
let sessionRefresh: Promise<Session> | null = null;
let unauthenticatedHandler: (() => void) | null = null;
let sessionUserSource: (() => string | null) | null = null;
let sessionChangedHandler: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

/** Registers the app-wide reaction to a 401 (redirect to /login). Returns an unregister function. */
export function setUnauthenticatedHandler(handler: (() => void) | null): () => void {
  unauthenticatedHandler = handler;
  return () => {
    if (unauthenticatedHandler === handler) unauthenticatedHandler = null;
  };
}

/**
 * Tells the client which staff user the app is currently showing (the cached session in
 * lib/session.ts). Used so a CSRF retry never runs as a different user. Returns an unregister function.
 */
export function setSessionUserSource(source: (() => string | null) | null): () => void {
  sessionUserSource = source;
  return () => {
    if (sessionUserSource === source) sessionUserSource = null;
  };
}

/** Registers the app-wide reaction when the cookie now belongs to another user (clear and reload). */
export function setSessionChangedHandler(handler: (() => void) | null): () => void {
  sessionChangedHandler = handler;
  return () => {
    if (sessionChangedHandler === handler) sessionChangedHandler = null;
  };
}

const envelopeSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().nullish(),
    request_id: z.string().nullish(),
    details: z.record(z.string(), z.unknown()).nullish(),
  }),
});

const STATUS_FALLBACK_CODES: Record<number, string> = {
  400: "VALIDATION_ERROR",
  401: "UNAUTHENTICATED",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "CONFLICT",
  422: "VALIDATION_ERROR",
  423: "ACCOUNT_LOCKED",
  429: "RATE_LIMITED",
};

const UNREACHABLE_MESSAGE =
  "The clinic server isn't answering. Try again in a moment. If it keeps happening, ask your admin to check the server.";

export function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const search = params.toString();
  return `${API_BASE}${path}${search ? `?${search}` : ""}`;
}

export function errorFromResponse(status: number, payload: unknown, headerRequestId: string | null): ApiError {
  const parsed = envelopeSchema.safeParse(payload);
  if (parsed.success) {
    const { code, message, request_id, details } = parsed.data.error;
    return new ApiError({
      status,
      code,
      message,
      requestId: request_id ?? headerRequestId,
      details: details ?? null,
    });
  }
  const code = STATUS_FALLBACK_CODES[status] ?? "ERROR";
  return new ApiError({
    status,
    code,
    message: status >= 500 ? UNREACHABLE_MESSAGE : null,
    requestId: headerRequestId,
  });
}

function reportBadResponse(path: string, requestId: string | null, issues: z.core.$ZodIssue[]): void {
  // Paths and issue codes only: response values can contain patient names and phones.
  console.error("[api] response did not match the contract", {
    path,
    requestId,
    issues: issues.slice(0, 10).map((issue) => ({ path: issue.path.join("."), code: issue.code })),
  });
}

async function send(path: string, options: RequestOptions): Promise<{ response: Response; text: string }> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE_METHODS.has(method) && options.csrf !== false) {
    headers["X-CSRF-Token"] = csrfToken ?? (await refreshCsrfToken());
  }
  if (method === "GET" && Date.now() - lastUserInput > BACKGROUND_AFTER_MS) {
    headers["X-Background-Refresh"] = "1";
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const forwardAbort = () => controller.abort();
  options.signal?.addEventListener("abort", forwardAbort, { once: true });

  try {
    const response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
    const text = await response.text();
    return { response, text };
  } catch (error) {
    if (options.signal?.aborted) throw error;
    if (timedOut) throw new ApiError({ status: 0, code: "TIMEOUT" });
    throw new ApiError({ status: 0, code: "NETWORK_ERROR" });
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", forwardAbort);
  }
}

async function execute(path: string, options: RequestOptions, isRetry = false): Promise<{ payload: unknown; requestId: string | null; status: number }> {
  const method = options.method ?? "GET";
  const { response, text } = await send(path, options);
  const requestId = response.headers.get("X-Request-ID");

  let payload: unknown = undefined;
  let parsedJson = false;
  if (text) {
    try {
      payload = JSON.parse(text);
      parsedJson = true;
    } catch {
      payload = undefined;
    }
  }

  if (!response.ok) {
    const error = errorFromResponse(response.status, payload, requestId);
    if (response.status === 401 && options.redirectOn401 !== false) {
      setCsrfToken(null);
      unauthenticatedHandler?.();
    }
    // A stale CSRF token (e.g. after signing in again in another tab) yields 403 with reason "csrf".
    // The server rejected the write without acting, so refreshing the token and retrying once is safe.
    const staleToken = response.status === 403 && error.details?.reason === "csrf";
    if (staleToken && UNSAFE_METHODS.has(method) && options.csrf !== false && !isRetry) {
      setCsrfToken(null);
      const shownUserId = sessionUserSource?.() ?? null;
      const fresh = await refreshSession();
      // The cookie can belong to someone else now (another sign-in in another tab). Retrying would
      // run this write as that person while the screen still shows the first one, so stop instead.
      if (shownUserId !== null && fresh.user.id !== shownUserId) {
        setCsrfToken(null);
        sessionChangedHandler?.();
        throw new ApiError({
          status: 403,
          code: "SESSION_CHANGED",
          message: "Someone else signed in on this computer in another tab. Reloading to show their account; nothing was saved.",
          requestId,
        });
      }
      return execute(path, options, true);
    }
    throw error;
  }

  if (response.status !== 204 && !parsedJson) {
    throw new ApiError({ status: response.status, code: "BAD_RESPONSE", requestId });
  }
  return { payload, requestId, status: response.status };
}

/** Sends a request and validates the JSON response against `schema`. */
export async function apiRequest<T>(path: string, schema: z.ZodType<T>, options: RequestOptions = {}): Promise<T> {
  const { payload, requestId } = await execute(path, options);
  const result = schema.safeParse(payload);
  if (!result.success) {
    reportBadResponse(path, requestId, result.error.issues);
    throw new ApiError({ status: 200, code: "BAD_RESPONSE", requestId });
  }
  return result.data;
}

/** Sends a request whose success response has no body (204). */
export async function apiRequestNoContent(path: string, options: RequestOptions = {}): Promise<void> {
  await execute(path, options);
}

/** GET /auth/me; also stores the CSRF token for later writes. */
export async function fetchSession(signal?: AbortSignal): Promise<Session> {
  const session = await apiRequest("/auth/me", sessionSchema, { signal });
  setCsrfToken(session.csrf_token);
  return session;
}

/** One shared GET /auth/me at a time (several writes may need a token at once). */
function refreshSession(): Promise<Session> {
  sessionRefresh ??= fetchSession().finally(() => {
    sessionRefresh = null;
  });
  return sessionRefresh;
}

export function refreshCsrfToken(): Promise<string> {
  return refreshSession().then((session) => session.csrf_token);
}
