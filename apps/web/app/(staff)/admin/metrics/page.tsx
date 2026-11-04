import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { WeeklyMetrics } from "@/features/admin/metrics/weekly-metrics";

export const metadata: Metadata = { title: "Weekly numbers" };
// Content appears after the browser confirms the session; see app/(staff)/layout.tsx.
export const instant = false;

export default function MetricsPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading weekly numbers" rows={3} />}>
      <WeeklyMetrics />
    </Suspense>
  );
}
