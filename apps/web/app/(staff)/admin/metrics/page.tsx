import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { WeeklyMetrics } from "@/features/admin/metrics/weekly-metrics";

export const metadata: Metadata = { title: "Weekly numbers" };

export default function MetricsPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading weekly numbers" rows={3} />}>
      <WeeklyMetrics />
    </Suspense>
  );
}
