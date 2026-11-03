import type { Metadata } from "next";

import { DoctorsList } from "@/features/admin/doctors/doctors-list";

export const metadata: Metadata = { title: "Doctors and hours" };

export default function DoctorsPage() {
  return <DoctorsList />;
}
