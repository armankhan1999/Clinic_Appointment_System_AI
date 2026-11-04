"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarPlus, ChevronLeft, ChevronRight, RefreshCw, Stethoscope } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState, RefetchNotice } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getDaySchedule } from "@/lib/api/endpoints";
import type { DaySchedule } from "@/lib/api/schemas";
import { addDays, formatLongDate, isIsoDate, todayIso } from "@/lib/dates";
import { LIVE_REFRESH_MS, queryKeys } from "@/lib/query";
import { useIsAdmin } from "@/lib/session";
import { cn } from "cn";

import { AppointmentRow } from "./appointment-row";
import { AttentionPanel } from "./attention-panel";

function DoctorDay({ doctor, isAdmin }: { doctor: DaySchedule["doctors"][number]; isAdmin: boolean }) {
  const active = doctor.appointments.filter((a) => a.status !== "cancelled").length;
  const headingId = `doctor-${doctor.doctor_id}`;
  return (
    <section aria-labelledby={headingId} className="overflow-hidden rounded-xl border bg-card shadow-[var(--shadow-panel)]">
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b bg-muted/60 px-4 py-3">
        <h2 id={headingId} className="text-title font-bold">
          {doctor.name}
          <span className="ml-2 text-body-sm font-normal text-muted-foreground">{doctor.specialty}</span>
        </h2>
        <p className="text-body-sm text-muted-foreground tabular">
          {active} {active === 1 ? "appointment" : "appointments"}
          {doctor.appointments.length > active ? `, ${doctor.appointments.length - active} cancelled` : ""}
        </p>
      </header>
      {doctor.appointments.length === 0 ? (
        <p className="px-4 py-4 text-muted-foreground">No appointments on this day.</p>
      ) : (
        <ol className="divide-y">
          {doctor.appointments.map((appointment) => (
            <AppointmentRow key={appointment.id} appointment={appointment} isAdmin={isAdmin} />
          ))}
        </ol>
      )}
    </section>
  );
}

export function TodayView() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isAdmin = useIsAdmin();
  const today = todayIso();
  const requested = searchParams.get("date");
  const date = requested && isIsoDate(requested) ? requested : today;

  const setDate = (next: string) => {
    if (!isIsoDate(next)) return;
    router.replace(next === today ? pathname : `${pathname}?date=${next}`, { scroll: false });
  };

  const schedule = useQuery({
    queryKey: queryKeys.schedule(date),
    queryFn: ({ signal }) => getDaySchedule(date, signal),
    refetchInterval: LIVE_REFRESH_MS,
  });

  const shownDate = schedule.data?.date ?? date;

  return (
    <>
      <PageHeader
        title={date === today ? "Today" : "Schedule"}
        description={<p className="text-title text-foreground">{formatLongDate(shownDate)}</p>}
        actions={
          <>
            <div role="group" aria-label="Choose the day" className="flex items-center gap-1">
              <Button variant="outline" size="icon" aria-label="Previous day" onClick={() => setDate(addDays(date, -1))}>
                <ChevronLeft aria-hidden />
              </Button>
              <Input
                type="date"
                aria-label="Day to show"
                className="w-[11.5rem]"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
              <Button variant="outline" size="icon" aria-label="Next day" onClick={() => setDate(addDays(date, 1))}>
                <ChevronRight aria-hidden />
              </Button>
            </div>
            {date !== today ? (
              <Button variant="ghost" onClick={() => setDate(today)}>
                Back to today
              </Button>
            ) : null}
            <Button variant="outline" onClick={() => schedule.refetch()} disabled={schedule.isFetching}>
              <RefreshCw aria-hidden className={cn(schedule.isFetching && "animate-spin")} />
              Refresh
            </Button>
            <Button asChild>
              <Link href="/book">
                <CalendarPlus aria-hidden />
                Book appointment
              </Link>
            </Button>
          </>
        }
      />

      <div className="space-y-6">
        <AttentionPanel />

        <p className="text-caption text-muted-foreground">New bookings, including ones made through Telegram, appear automatically every 30 seconds.</p>

        <RefetchNotice query={schedule} what="the schedule" />

        {schedule.isPending ? (
          <LoadingState label="Loading the schedule" />
        ) : schedule.isLoadingError ? (
          <ErrorState what="the schedule" error={schedule.error} onRetry={() => schedule.refetch()} />
        ) : schedule.data.doctors.length === 0 ? (
          <EmptyState
            icon={Stethoscope}
            title="No doctors are working"
            description={
              isAdmin ? "Add a doctor or reactivate one under Doctors and hours." : "Ask the clinic admin to add the doctors' schedules."
            }
            action={
              isAdmin ? (
                <Button asChild variant="outline">
                  <Link href="/admin/doctors">Open Doctors and hours</Link>
                </Button>
              ) : null
            }
          />
        ) : (
          <div className="space-y-6">
            {schedule.data.doctors.map((doctor) => (
              <DoctorDay key={doctor.doctor_id} doctor={doctor} isAdmin={isAdmin} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
