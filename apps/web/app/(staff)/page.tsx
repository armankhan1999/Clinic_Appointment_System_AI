import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { TodayView } from "@/features/today/today-view";

export const metadata: Metadata = { title: "Today" };
// Content appears after the browser confirms the session; see app/(staff)/layout.tsx.
export const instant = false;

export default function TodayPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading the schedule" />}>
      <TodayView />
    </Suspense>
  );
}
