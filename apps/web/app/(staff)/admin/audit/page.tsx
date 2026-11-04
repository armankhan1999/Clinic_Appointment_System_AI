import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { AuditLog } from "@/features/admin/audit/audit-log";

export const metadata: Metadata = { title: "Activity log" };
// Content appears after the browser confirms the session; see app/(staff)/layout.tsx.
export const instant = false;

export default function AuditPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading the activity log" />}>
      <AuditLog />
    </Suspense>
  );
}
