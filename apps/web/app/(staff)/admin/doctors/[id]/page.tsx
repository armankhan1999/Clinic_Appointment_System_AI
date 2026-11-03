import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { DoctorDetail } from "@/features/admin/doctors/doctor-detail";

export const metadata: Metadata = { title: "Doctor hours and leave" };

export default function DoctorPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading doctor" />}>
      <DoctorDetail />
    </Suspense>
  );
}
