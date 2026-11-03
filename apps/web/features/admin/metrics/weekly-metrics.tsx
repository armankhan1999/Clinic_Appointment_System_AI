"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getWeeklyMetrics } from "@/lib/api/endpoints";
import { addDays, formatShortDate, isIsoDate, mondayOf, todayIso } from "@/lib/dates";
import { queryKeys } from "@/lib/query";

const count = new Intl.NumberFormat("en-IN");
const percent = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 1 });

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <dt className="text-body-sm text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-display font-semibold tabular">{count.format(value)}</dd>
    </div>
  );
}

/** Weekly numbers (E6-S6). An empty week shows zeros; only real failures show an error (E6-S6-AC2). */
export function WeeklyMetrics() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const thisWeek = mondayOf(todayIso());
  const requested = searchParams.get("week");
  const weekStart = requested && isIsoDate(requested) ? mondayOf(requested) : thisWeek;

  const setWeek = (date: string) => {
    if (!isIsoDate(date)) return;
    const monday = mondayOf(date);
    router.replace(monday === thisWeek ? pathname : `${pathname}?week=${monday}`, { scroll: false });
  };

  const metrics = useQuery({
    queryKey: queryKeys.metrics(weekStart),
    queryFn: ({ signal }) => getWeeklyMetrics(weekStart, signal),
  });

  const data = metrics.data;
  const totalBookings = data ? data.bookings_by_source.bot + data.bookings_by_source.staff : 0;
  const isEmpty =
    data !== undefined &&
    totalBookings === 0 &&
    data.cancellations === 0 &&
    data.per_doctor.every((d) => d.completed === 0 && d.no_show === 0);

  return (
    <>
      <PageHeader
        title="Weekly numbers"
        description={
          <p>
            Week of {formatShortDate(weekStart)} to {formatShortDate(addDays(weekStart, 6))}
          </p>
        }
        actions={
          <div role="group" aria-label="Choose the week" className="flex items-center gap-1">
            <Button variant="outline" size="icon" aria-label="Previous week" onClick={() => setWeek(addDays(weekStart, -7))}>
              <ChevronLeft aria-hidden />
            </Button>
            <Input
              type="date"
              aria-label="Any day in the week"
              className="w-[11.5rem]"
              value={weekStart}
              onChange={(e) => setWeek(e.target.value)}
            />
            <Button variant="outline" size="icon" aria-label="Next week" onClick={() => setWeek(addDays(weekStart, 7))}>
              <ChevronRight aria-hidden />
            </Button>
            {weekStart !== thisWeek ? (
              <Button variant="ghost" onClick={() => setWeek(thisWeek)}>
                This week
              </Button>
            ) : null}
          </div>
        }
      />

      {metrics.isPending ? (
        <LoadingState label="Loading weekly numbers" rows={3} />
      ) : metrics.isError ? (
        <ErrorState what="the weekly numbers" error={metrics.error} onRetry={() => metrics.refetch()} />
      ) : (
        <div className="space-y-6">
          {isEmpty ? (
            <p role="status" className="rounded-lg border bg-card px-4 py-3 text-muted-foreground">
              No bookings, cancellations or attendance were recorded this week.
            </p>
          ) : null}
          <section aria-labelledby="bookings-heading" className="space-y-3">
            <h2 id="bookings-heading" className="text-title font-bold">
              Bookings and cancellations
            </h2>
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile label="Booked through Telegram" value={metrics.data.bookings_by_source.bot} />
              <StatTile label="Booked at the front desk" value={metrics.data.bookings_by_source.staff} />
              <StatTile label="All bookings" value={totalBookings} />
              <StatTile label="Cancellations" value={metrics.data.cancellations} />
            </dl>
          </section>

          <section aria-labelledby="attendance-heading" className="space-y-3">
            <h2 id="attendance-heading" className="text-title font-bold">
              Attendance by doctor
            </h2>
            <div className="overflow-x-auto rounded-xl border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Doctor</TableHead>
                    <TableHead className="text-right">Completed</TableHead>
                    <TableHead className="text-right">No-show</TableHead>
                    <TableHead className="text-right">No-show rate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {metrics.data.per_doctor.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} className="text-muted-foreground">
                        No doctors had appointments this week.
                      </TableCell>
                    </TableRow>
                  ) : (
                    metrics.data.per_doctor.map((d) => (
                      <TableRow key={d.doctor_id}>
                        <TableCell className="font-semibold">{d.name}</TableCell>
                        <TableCell className="text-right tabular">{count.format(d.completed)}</TableCell>
                        <TableCell className="text-right tabular">{count.format(d.no_show)}</TableCell>
                        <TableCell className="text-right tabular">{percent.format(d.no_show_rate)}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
            <p className="text-caption text-muted-foreground">
              No-show rate = no-shows ÷ (completed + no-shows); 0% when neither happened.
            </p>
          </section>
        </div>
      )}
    </>
  );
}
