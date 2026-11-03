import { StaffGate } from "@/components/gates";

export default function StaffLayout({ children }: { children: React.ReactNode }) {
  return <StaffGate>{children}</StaffGate>;
}
