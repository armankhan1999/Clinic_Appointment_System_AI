import { StaffGate } from "@/components/gates";

// Staff pages render only after the browser has confirmed the session (GET /auth/me), so their
// content can never be part of a prerendered shell. Opt this subtree out of instant-navigation
// and static-shell validation; /login stays validated.
export const instant = false;

export default function StaffLayout({ children }: { children: React.ReactNode }) {
  return <StaffGate>{children}</StaffGate>;
}
