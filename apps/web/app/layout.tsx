import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible_Next } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

// Atkinson Hyperlegible separates look-alike characters (0/O, 1/l/I), which matters for phone numbers and references.
const atkinson = Atkinson_Hyperlegible_Next({
  subsets: ["latin", "latin-ext"],
  display: "swap",
  variable: "--font-atkinson",
  // Next.js has no metric overrides for this family; fall back to the system UI font.
  adjustFontFallback: false,
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

export const metadata: Metadata = {
  title: { template: "%s | Front Desk", default: "Front Desk" },
  description: "Clinic front desk: today's appointments, walk-in booking and clinic administration.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#1d5c4e",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${atkinson.variable} ${atkinson.className}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
