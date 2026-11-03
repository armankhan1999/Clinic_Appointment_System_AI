import type { Metadata } from "next";

import { StaffAccounts } from "@/features/admin/staff/staff-accounts";

export const metadata: Metadata = { title: "Staff accounts" };

export default function StaffPage() {
  return <StaffAccounts />;
}
