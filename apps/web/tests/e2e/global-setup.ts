import type { FullConfig } from "@playwright/test";

import { REQUIRED_ENV } from "./support";

/**
 * Fails fast, with instructions, when the stack these specs need is not running.
 * These tests are never faked: no backend means no run.
 */
export default async function globalSetup(config: FullConfig): Promise<void> {
  const missing = REQUIRED_ENV.filter((key) => !process.env[key]);
  if (missing.length > 0) {
    throw new Error(
      `E2E specs need real staff accounts in the dev database. Set: ${missing.join(", ")}. See apps/web/README.md.`,
    );
  }

  const baseURL = String(config.projects[0]?.use.baseURL ?? "http://localhost:3000");
  let status = 0;
  let body: unknown = null;
  try {
    const res = await fetch(`${baseURL}/api/v1/auth/me`, { headers: { Accept: "application/json" } });
    status = res.status;
    body = await res.json().catch(() => null);
  } catch (error) {
    throw new Error(`Dashboard not reachable at ${baseURL} (${String(error)}). Start it with "npm run dev" or "npm run start".`);
  }

  const isEnvelope = typeof body === "object" && body !== null && "error" in body;
  if (status !== 401 || !isEnvelope) {
    throw new Error(
      `Expected GET ${baseURL}/api/v1/auth/me to return the API's 401 error envelope (proving the /api/v1 rewrite reaches FastAPI), got HTTP ${status}. ` +
        "Start the API (apps/backend: uv run clinic-api) and check API_PORT matches.",
    );
  }
}
