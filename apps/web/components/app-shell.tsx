"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  CalendarPlus,
  ChartColumn,
  LoaderCircle,
  LogOut,
  Menu,
  MessageSquareText,
  ScrollText,
  Settings,
  Stethoscope,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { logout } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { StaffUser } from "@/lib/api/schemas";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: LucideIcon };

const DAILY: NavItem[] = [
  { href: "/", label: "Today", icon: CalendarDays },
  { href: "/book", label: "Book appointment", icon: CalendarPlus },
];

const ADMIN: NavItem[] = [
  { href: "/admin/doctors", label: "Doctors and hours", icon: Stethoscope },
  { href: "/admin/faq", label: "Clinic answers", icon: MessageSquareText },
  { href: "/admin/metrics", label: "Weekly numbers", icon: ChartColumn },
  { href: "/admin/audit", label: "Activity log", icon: ScrollText },
  { href: "/admin/staff", label: "Staff accounts", icon: Users },
  { href: "/admin/settings", label: "Clinic settings", icon: Settings },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function NavLinks({ user, onNavigate }: { user: StaffUser; onNavigate?: () => void }) {
  const pathname = usePathname();
  const renderItem = (item: NavItem) => {
    const active = isActive(pathname, item.href);
    return (
      <li key={item.href}>
        <Link
          href={item.href}
          onClick={onNavigate}
          aria-current={active ? "page" : undefined}
          className={cn(
            "flex min-h-11 items-center gap-3 rounded-md border-l-4 px-3 py-2 text-body-sm font-medium transition-colors",
            active
              ? "border-l-primary bg-primary-soft text-primary"
              : "border-l-transparent text-foreground hover:bg-muted",
          )}
        >
          <item.icon aria-hidden className="size-5 shrink-0" />
          {item.label}
        </Link>
      </li>
    );
  };

  return (
    <nav aria-label="Main" className="flex flex-col gap-6">
      <ul className="flex flex-col gap-1">{DAILY.map(renderItem)}</ul>
      {user.role === "admin" ? (
        <div className="flex flex-col gap-2">
          <p id="admin-nav-heading" className="px-3 text-caption font-semibold text-muted-foreground">
            Clinic admin
          </p>
          <ul aria-labelledby="admin-nav-heading" className="flex flex-col gap-1">
            {ADMIN.map(renderItem)}
          </ul>
        </div>
      ) : null}
    </nav>
  );
}

function SignOut({ user }: { user: StaffUser }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const mutation = useMutation({
    mutationFn: logout,
    onSettled: (_data, error) => {
      // 401 means the session had already ended, which is what signing out wants anyway.
      if (error && !(isApiError(error) && error.status === 401)) {
        notify({
          tone: "error",
          title: "Couldn't sign out",
          description: "Check the connection and try again.",
          requestId: isApiError(error) ? error.requestId : null,
        });
        return;
      }
      queryClient.clear();
      window.location.replace("/login");
    },
  });

  return (
    <div className="flex flex-col gap-2 border-t pt-4">
      <div className="px-3">
        <p className="font-semibold">{user.display_name}</p>
        <p className="text-caption text-muted-foreground">{user.role === "admin" ? "Clinic admin" : "Receptionist"}</p>
      </div>
      <Button variant="ghost" className="justify-start" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
        {mutation.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <LogOut aria-hidden />}
        Sign out
      </Button>
    </div>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2 rounded-md px-3 py-1">
      <span aria-hidden className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground">
        <CalendarDays className="size-5" />
      </span>
      <span className="leading-tight">
        <span className="block text-title font-bold">Front Desk</span>
        <span className="block text-caption text-muted-foreground">Clinic appointments</span>
      </span>
    </Link>
  );
}

export function AppShell({ user, children }: { user: StaffUser; children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-card px-4 py-2 focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>

      <aside className="hidden border-r bg-sidebar lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col lg:justify-between lg:gap-6 lg:overflow-y-auto lg:p-4">
        <div className="flex flex-col gap-6">
          <Brand />
          <NavLinks user={user} />
        </div>
        <SignOut user={user} />
      </aside>

      <div className="sticky top-0 z-40 flex items-center justify-between border-b bg-sidebar px-4 py-2 lg:hidden">
        <Brand />
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" size="icon" aria-label="Open menu">
              <Menu aria-hidden />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="flex w-72 flex-col justify-between gap-6 overflow-y-auto p-4">
            <div className="flex flex-col gap-6">
              <SheetHeader className="p-0">
                <SheetTitle>Menu</SheetTitle>
                <SheetDescription className="sr-only">Pages you can open</SheetDescription>
              </SheetHeader>
              <NavLinks user={user} onNavigate={() => setMenuOpen(false)} />
            </div>
            <SignOut user={user} />
          </SheetContent>
        </Sheet>
      </div>

      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl px-4 py-6 outline-none md:px-8 md:py-8">
        {children}
      </main>
    </div>
  );
}
