import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StaffAccounts } from "@/features/admin/staff/staff-accounts";

import { errorEnvelope, jsonResponse, sessionBody, stubFetch, type StubbedCall } from "./helpers";
import { renderWithProviders } from "./render";

/* IMP-04: an admin resets a staff member's password (PATCH /staff-users/{id} { password }). */

const ME = { id: "u-1", username: "desk1", display_name: "Asha Desk", role: "admin", active: true, locked_until: null };
const RAVI = { id: "u-2", username: "ravi", display_name: "Ravi", role: "receptionist", active: true, locked_until: null };

function stubStaffApi(onPatch: (call: StubbedCall) => Response) {
  return stubFetch((call: StubbedCall) => {
    if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
    if (call.url.startsWith("/api/v1/staff-users?")) return jsonResponse(200, { items: [ME, RAVI], page: 1, page_size: 100, total: 2 });
    if (call.url === "/api/v1/staff-users/u-2" && call.method === "PATCH") return onPatch(call);
    throw new Error(`unexpected ${call.method} ${call.url}`);
  });
}

async function openReset() {
  renderWithProviders(<StaffAccounts />);
  fireEvent.click(await screen.findByRole("button", { name: "Reset password for Ravi" }));
  return screen.findByRole("dialog", { name: "Reset password for Ravi" });
}

function fill(dialog: HTMLElement, password: string, again: string) {
  fireEvent.change(within(dialog).getByLabelText("New password"), { target: { value: password } });
  fireEvent.change(within(dialog).getByLabelText("Type the new password again"), { target: { value: again } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Reset password" }));
}

describe("staff password reset (IMP-04)", () => {
  it("checks length and confirmation, then PATCHes only the new password", async () => {
    const { calls } = stubStaffApi(() => jsonResponse(200, RAVI));
    const dialog = await openReset();
    expect(dialog.textContent).toContain("signed out on every computer");

    fill(dialog, "too-short", "too-short");
    expect(await within(dialog).findByText("Use at least 12 characters")).toBeTruthy();
    fill(dialog, "a-long-enough-password", "a-long-enough-passwordX");
    expect(await within(dialog).findByText("The two passwords don't match")).toBeTruthy();
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);

    fill(dialog, "a-long-enough-password", "a-long-enough-password");
    expect(await screen.findByText("Password reset")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({ password: "a-long-enough-password" });
    expect(patch?.headers["x-csrf-token"]).toBe("csrf-1");
  });

  it("keeps the dialog open with the API's refusal on the password field", async () => {
    stubStaffApi(() =>
      jsonResponse(422, errorEnvelope("VALIDATION_ERROR", "Please check these fields: body.password", { details: { fields: ["body.password"] } })),
    );
    const dialog = await openReset();
    fill(dialog, "a-long-enough-password", "a-long-enough-password");
    expect(await within(dialog).findByText("The clinic server didn't accept this. Check it and try again.")).toBeTruthy();
    expect(within(dialog).getByLabelText("New password").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("dialog", { name: "Reset password for Ravi" })).toBeTruthy();
  });

  it("offers no reset for the signed-in admin's own account, which would sign them out", async () => {
    stubStaffApi(() => jsonResponse(200, RAVI));
    renderWithProviders(<StaffAccounts />);
    expect(await screen.findByRole("button", { name: "Reset password for Ravi" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reset password for Asha Desk" })).toBeNull();
  });
});
