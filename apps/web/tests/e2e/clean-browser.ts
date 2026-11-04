import { test as base, expect } from "@playwright/test";

/*
 * Every E2E test also asserts that the browser stayed clean: no console errors or
 * warnings, no uncaught page errors, no 5xx responses and no failed requests.
 * Chrome's own "Failed to load resource" line for an intended 4xx (wrong password,
 * 409 slot taken) is left to the network checks, which allow 4xx.
 */
export const test = base.extend<{ cleanBrowser: void }>({
  cleanBrowser: [
    async ({ page }, use) => {
      const problems: string[] = [];
      page.on("console", (message) => {
        const kind = message.type();
        if ((kind === "error" || kind === "warning") && !message.text().startsWith("Failed to load resource")) {
          problems.push(`console.${kind}: ${message.text()}`);
        }
      });
      page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
      page.on("response", (response) => {
        if (response.status() >= 500) {
          problems.push(`HTTP ${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`);
        }
      });
      page.on("requestfailed", (request) => {
        const reason = request.failure()?.errorText ?? "unknown";
        // Navigation and React Query cancellations abort in-flight requests on purpose.
        if (!reason.includes("ERR_ABORTED")) {
          problems.push(`request failed: ${request.method()} ${new URL(request.url()).pathname} (${reason})`);
        }
      });
      await use();
      expect(problems, "the browser console and network stayed clean").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
