import type { Metadata } from "next";

import { StaffAccounts } from "@/features/admin/staff/staff-accounts";

export const metadata: Metadata = { title: "Staff accounts" };
// Content appears after the browser confirms the session; see app/(staff)/layout.tsx.
export const instant = false;

export default function StaffPage() {
  return <StaffAccounts />;
}
