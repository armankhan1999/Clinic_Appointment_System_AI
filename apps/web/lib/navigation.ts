function looksUnsafe(value: string): boolean {
  return (
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(value)
  );
}

/**
 * Returns a same-origin path that is safe to redirect to after sign-in, or "/".
 * Rejects absolute URLs, protocol-relative ("//evil"), backslash and control-character
 * tricks (also when percent-encoded) and the login page itself, so `?next=` cannot be
 * used as an open redirect. `raw` is the already-decoded query value.
 */
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw) return "/";
  if (looksUnsafe(raw)) return "/";
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    return "/";
  }
  if (looksUnsafe(decoded)) return "/";
  const pathname = raw.split(/[?#]/, 1)[0];
  if (pathname === "/login" || pathname.startsWith("/login/")) return "/";
  return raw;
}

export function loginUrlFor(currentPath: string): string {
  const next = safeNextPath(currentPath);
  return next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`;
}
