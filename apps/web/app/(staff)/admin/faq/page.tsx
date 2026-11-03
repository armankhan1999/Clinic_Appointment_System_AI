import type { Metadata } from "next";

import { FaqEditor } from "@/features/admin/faq/faq-editor";

export const metadata: Metadata = { title: "Clinic answers" };

export default function FaqPage() {
  return <FaqEditor />;
}
