import type { Metadata } from "next";

import { SettingsPageView } from "@/features/admin/settings/settings-form";

export const metadata: Metadata = { title: "Clinic settings" };
// Content appears after the browser confirms the session; see app/(staff)/layout.tsx.
export const instant = false;

export default function SettingsPage() {
  return <SettingsPageView />;
}
