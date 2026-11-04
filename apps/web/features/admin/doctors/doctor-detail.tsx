"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState, RefetchNotice } from "@/components/states";
import { Pill } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getDoctors } from "@/lib/api/endpoints";
import { queryKeys } from "@/lib/query";

import { LeaveManager } from "./leave-manager";
import { ScheduleEditor } from "./schedule-editor";

export function DoctorDetail() {
  const [tab, setTab] = useState("hours");
  const params = useParams<{ id: string }>();
  const id = params.id;
  // The contract has no GET /doctors/{id}; the full list is small and already cached by the list page.
  const doctors = useQuery({ queryKey: queryKeys.doctors("all"), queryFn: ({ signal }) => getDoctors({}, signal) });
  const doctor = doctors.data?.items.find((d) => d.id === id);

  const back = (
    <Button variant="ghost" asChild className="-ml-3 mb-2">
      <Link href="/admin/doctors">
        <ChevronLeft aria-hidden />
        All doctors
      </Link>
    </Button>
  );

  if (doctors.isPending) return <LoadingState label="Loading doctor" />;
  if (doctors.isLoadingError) return <ErrorState what="this doctor" error={doctors.error} onRetry={() => doctors.refetch()} />;
  if (!doctor) {
    return (
      <>
        {back}
        <EmptyState title="Doctor not found" description="They may have been removed, or the link is wrong." />
      </>
    );
  }

  return (
    <>
      {back}
      <RefetchNotice query={doctors} what="this doctor" />
      <PageHeader
        title={doctor.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {doctor.specialty}
            {doctor.active ? <Pill tone="booked">Active</Pill> : <Pill tone="cancelled">Inactive</Pill>}
          </span>
        }
      />
      <Tabs value={tab} onValueChange={setTab} className="gap-4">
        <TabsList>
          <TabsTrigger value="hours">Weekly hours</TabsTrigger>
          <TabsTrigger value="leave">Leave days</TabsTrigger>
        </TabsList>
        {/* Both panels stay mounted so switching tabs never discards unsaved hours or a leave in progress. */}
        <TabsContent value="hours" forceMount hidden={tab !== "hours"}>
          <ScheduleEditor doctorId={doctor.id} doctorName={doctor.name} />
        </TabsContent>
        <TabsContent value="leave" forceMount hidden={tab !== "leave"}>
          <LeaveManager doctorId={doctor.id} doctorName={doctor.name} />
        </TabsContent>
      </Tabs>
    </>
  );
}
