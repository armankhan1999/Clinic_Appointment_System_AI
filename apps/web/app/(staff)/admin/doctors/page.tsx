import type { Metadata } from "next";

import { DoctorsList } from "@/features/admin/doctors/doctors-list";

export const metadata: Metadata = { title: "Doctors and hours" };
// Content appears after the browser confirms the session; see app/(staff)/layout.tsx.
export const instant = false;

export default function DoctorsPage() {
  return <DoctorsList />;
}
