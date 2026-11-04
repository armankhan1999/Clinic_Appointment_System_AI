import type { Metadata } from "next";

import { FaqEditor } from "@/features/admin/faq/faq-editor";

export const metadata: Metadata = { title: "Clinic answers" };
// Content appears after the browser confirms the session; see app/(staff)/layout.tsx.
export const instant = false;

export default function FaqPage() {
  return <FaqEditor />;
}
