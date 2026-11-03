import type { Metadata } from "next";

import { SettingsPageView } from "@/features/admin/settings/settings-form";

export const metadata: Metadata = { title: "Clinic settings" };

export default function SettingsPage() {
  return <SettingsPageView />;
}
