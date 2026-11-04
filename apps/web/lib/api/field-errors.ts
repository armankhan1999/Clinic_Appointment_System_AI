import type { FieldPath, FieldValues, UseFormSetError } from "react-hook-form";

import { isApiError } from "./errors";

export const SERVER_FIELD_MESSAGE = "The clinic server didn't accept this. Check it and try again.";

/**
 * Form fields named by a 422 VALIDATION_ERROR. The API reports FastAPI locations such as
 * "body.patient.full_name" in details.fields; `map` translates API paths (without "body.")
 * to form field names. A mapped path also covers anything nested under it ("aliases.2").
 */
export function matchApiFields<F extends string>(error: unknown, map: Readonly<Record<string, F>>): F[] {
  if (!isApiError(error) || error.code !== "VALIDATION_ERROR") return [];
  const matched: F[] = [];
  for (const raw of error.fields) {
    const path = raw.replace(/^body\./, "");
    for (const [apiPath, field] of Object.entries(map)) {
      if ((path === apiPath || path.startsWith(`${apiPath}.`)) && !matched.includes(field)) matched.push(field);
    }
  }
  return matched;
}

/** Marks the fields a 422 named; returns true when at least one was marked. */
export function applyApiFieldErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  map: Readonly<Record<string, FieldPath<T>>>,
): boolean {
  const fields = matchApiFields(error, map);
  fields.forEach((field, index) => setError(field, { type: "server", message: SERVER_FIELD_MESSAGE }, { shouldFocus: index === 0 }));
  return fields.length > 0;
}
