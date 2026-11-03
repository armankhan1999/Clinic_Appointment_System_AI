import { NextResponse, type NextRequest } from "next/server";

/** Must match the cookie name set by the API (docs/api/staff-api.md, Conventions). */
export const SESSION_COOKIE = "clinic_session";

/**
 * Optimistic redirect only: if there is no session cookie at all, send the user to
 * /login and remember where they were going. Whether the cookie is valid, and what
 * the user may do, is decided by the API on every request.
 */
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();

  const { pathname, search } = request.nextUrl;
  const loginUrl = new URL("/login", request.url);
  if (pathname !== "/") loginUrl.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    {
      // Everything except the login page, the API rewrite, Next internals and static files.
      source: "/((?!login|api/|_next/static|_next/image|favicon\\.ico|.*\\.(?:svg|png|ico|webp|woff2?)$).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
