import type { NextConfig } from "next";

/**
 * Port of the FastAPI process on this machine. The browser never talks to it directly:
 * /api/v1/* is rewritten to it, so the dashboard and API share one origin (no CORS).
 * The original dev PC uses API_PORT=8010 because another program holds 8000 (D-27).
 */
function apiPort(): string {
  const raw = process.env.API_PORT ?? "8000";
  const port = Number(raw);
  if (!/^\d+$/.test(raw) || port < 1 || port > 65_535) {
    throw new Error(`API_PORT must be a TCP port number (1-65535), got "${raw}"`);
  }
  return raw;
}

const isDev = process.env.NODE_ENV === "development";

/*
 * Static CSP set via headers() ("without nonces" in the Next.js CSP guide). Next.js
 * inlines its RSC payload scripts, so script-src needs 'unsafe-inline' unless every
 * page is rendered per request with a nonce. 'unsafe-eval' is development-only
 * (React uses eval for dev error overlays). upgrade-insecure-requests and HSTS are
 * left to the HTTPS terminator: the laptop deployment serves plain HTTP (D-05).
 */
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
  },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `http://127.0.0.1:${apiPort()}/api/v1/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        // API responses keep the API's own security headers.
        source: "/((?!api/).*)",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
