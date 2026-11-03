"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/toaster";
import {
  acknowledgeAlert,
  cancelAppointment,
  clearAttention,
  markAttendance,
  resolveTicket,
} from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/query";

/** Mutations used on the Today screen. Every success refreshes the schedule and the attention panel. */
export function useDayActions() {
  const queryClient = useQueryClient();
  const notify = useToast();

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.scheduleAll }),
      queryClient.invalidateQueries({ queryKey: queryKeys.attention }),
    ]);

  // Someone else changed the same record; show fresh data behind the still-open dialog.
  const refreshOnConflict = (error: unknown) => {
    if (isApiError(error) && ["ALREADY_CANCELLED", "CONFLICT", "NOT_FOUND"].includes(error.code)) void refresh();
  };

  const cancel = useMutation({
    mutationFn: (input: { id: string; reason: string }) => cancelAppointment(input.id, input.reason),
    onSuccess: async (appointment) => {
      notify({
        tone: "success",
        title: "Appointment cancelled",
        description: `${appointment.time_label} with ${appointment.doctor_name}. Patients who use Telegram get a message.`,
      });
      await refresh();
    },
    onError: refreshOnConflict,
  });

  const attendance = useMutation({
    mutationFn: (input: { id: string; status: "completed" | "no_show" }) => markAttendance(input.id, input.status),
    onSuccess: async (appointment) => {
      notify({
        tone: "success",
        title: appointment.status === "completed" ? "Marked as completed" : "Marked as no-show",
        description: `${appointment.time_label} with ${appointment.doctor_name}`,
      });
      await refresh();
    },
    onError: refreshOnConflict,
  });

  const clear = useMutation({
    mutationFn: (id: string) => clearAttention(id),
    onSuccess: async () => {
      notify({ tone: "success", title: "Call flag cleared" });
      await refresh();
    },
    onError: refreshOnConflict,
  });

  const resolve = useMutation({
    mutationFn: (id: string) => resolveTicket(id),
    onSuccess: async () => {
      notify({ tone: "success", title: "Request marked as resolved" });
      await refresh();
    },
    onError: refreshOnConflict,
  });

  const acknowledge = useMutation({
    mutationFn: (id: string) => acknowledgeAlert(id),
    onSuccess: async () => {
      notify({ tone: "success", title: "Emergency alert acknowledged" });
      await refresh();
    },
    onError: refreshOnConflict,
  });

  return { cancel, attendance, clear, resolve, acknowledge };
}
