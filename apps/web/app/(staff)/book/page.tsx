import type { Metadata } from "next";

import { BookingFlow } from "@/features/booking/booking-flow";

export const metadata: Metadata = { title: "Book appointment" };
// Content appears after the browser confirms the session; see app/(staff)/layout.tsx.
export const instant = false;

export default function BookPage() {
  return <BookingFlow />;
}
