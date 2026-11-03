import type { Metadata } from "next";

import { BookingFlow } from "@/features/booking/booking-flow";

export const metadata: Metadata = { title: "Book appointment" };

export default function BookPage() {
  return <BookingFlow />;
}
