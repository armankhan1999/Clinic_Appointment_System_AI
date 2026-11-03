import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { AuditLog } from "@/features/admin/audit/audit-log";

export const metadata: Metadata = { title: "Activity log" };

export default function AuditPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading the activity log" />}>
      <AuditLog />
    </Suspense>
  );
}
