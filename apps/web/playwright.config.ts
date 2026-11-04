import { defineConfig, devices } from "@playwright/test";

/*
 * End-to-end tests against the REAL stack: Next.js dashboard + FastAPI + the dev
 * database with the seed loaded. Nothing is mocked. Start the stack first
 * (see apps/web/README.md), then: npm run test:e2e
 */
export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  // The app waits up to 15 s per request (lib/api/client.ts). Raise this only where the database is
  // far from the API (risk R-LAT-01), so assertions wait as long as the app itself would.
  expect: { timeout: Number(process.env.E2E_EXPECT_TIMEOUT_MS ?? 5_000) },
  timeout: Number(process.env.E2E_TEST_TIMEOUT_MS ?? 30_000),
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "tablet-chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 820, height: 1180 } } },
  ],
});
