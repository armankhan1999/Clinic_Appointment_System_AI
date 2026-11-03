/** Error codes from the contract's error envelope, plus client-side transport codes. */
export type ApiErrorCode =
  | "VALIDATION_ERROR"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "SLOT_TAKEN"
  | "SLOT_UNAVAILABLE"
  | "LIMIT_REACHED"
  | "ALREADY_CANCELLED"
  | "CONFLICT"
  | "ACCOUNT_LOCKED"
  | "RATE_LIMITED"
  | "ERROR"
  | "NETWORK_ERROR"
  | "TIMEOUT"
  | "BAD_RESPONSE"
  | (string & {});

const DEFAULT_MESSAGES: Record<string, string> = {
  VALIDATION_ERROR: "Some details aren't valid. Check the highlighted fields and try again.",
  UNAUTHENTICATED: "Your session has ended. Please sign in again.",
  FORBIDDEN: "Your account isn't allowed to do this.",
  NOT_FOUND: "We couldn't find that. It may have been removed.",
  SLOT_TAKEN: "That time was just booked by someone else. Pick another time.",
  SLOT_UNAVAILABLE: "That time is no longer available. Pick another time.",
  LIMIT_REACHED: "This patient has reached their booking limit.",
  ALREADY_CANCELLED: "This appointment was already cancelled.",
  CONFLICT: "This change conflicts with something that changed meanwhile. Refresh and try again.",
  ACCOUNT_LOCKED: "This account is locked after too many failed sign-ins.",
  RATE_LIMITED: "Too many attempts. Wait a minute, then try again.",
  ERROR: "Something went wrong on the clinic server. Try again in a moment.",
  NETWORK_ERROR: "Can't reach the clinic server. Check the connection and try again.",
  TIMEOUT: "The clinic server took too long to answer. Try again.",
  BAD_RESPONSE: "The clinic server sent an answer this screen doesn't understand.",
};

export function defaultMessageFor(code: string): string {
  return DEFAULT_MESSAGES[code] ?? DEFAULT_MESSAGES.ERROR;
}

export interface ApiErrorInit {
  status: number;
  code: ApiErrorCode;
  message?: string | null;
  requestId?: string | null;
  details?: Record<string, unknown> | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(init: ApiErrorInit) {
    super(init.message?.trim() || defaultMessageFor(init.code));
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId ?? null;
    this.details = init.details ?? {};
  }

  /** Field paths reported by VALIDATION_ERROR (`details.fields`). */
  get fields(): string[] {
    const fields = this.details.fields;
    return Array.isArray(fields) ? fields.filter((f): f is string => typeof f === "string") : [];
  }

  /** ISO timestamp from ACCOUNT_LOCKED `details.locked_until`. */
  get lockedUntil(): string | null {
    const value = this.details.locked_until;
    return typeof value === "string" ? value : null;
  }

  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/** Wraps anything thrown into an ApiError so UI code handles one error type. */
export function toApiError(value: unknown): ApiError {
  if (isApiError(value)) return value;
  return new ApiError({ status: 0, code: "ERROR" });
}
