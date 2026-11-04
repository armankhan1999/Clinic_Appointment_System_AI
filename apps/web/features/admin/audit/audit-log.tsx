"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Filter, ScrollText, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { Controller, useForm } from "react-hook-form";

import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AUDIT_PAGE_SIZE, getAuditLog, type AuditFilters } from "@/lib/api/endpoints";
import { formatUtcTimestamp } from "@/lib/dates";
import { queryKeys } from "@/lib/query";
import { auditFilterSchema, type AuditFilterForm } from "@/lib/validation/forms";

const ACTOR_LABELS: Record<string, string> = {
  agent: "Telegram assistant",
  staff: "Staff",
  system: "System",
  patient_button: "Patient (button)",
};
const ANY_ACTOR = "any";

function filtersFromParams(params: URLSearchParams): AuditFilters {
  const parsed = auditFilterSchema.safeParse({
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    actor_type: params.get("actor_type") ?? "",
    action: params.get("action") ?? "",
    patient_id: params.get("patient_id") ?? "",
  });
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  return parsed.success ? { ...parsed.data, page } : { page };
}

function toForm(filters: AuditFilters): AuditFilterForm {
  return {
    from: filters.from ?? "",
    to: filters.to ?? "",
    actor_type: filters.actor_type ?? "",
    action: filters.action ?? "",
    patient_id: filters.patient_id ?? "",
  };
}

function ArgsCell({ args }: { args: unknown }) {
  if (args === null || args === undefined || (typeof args === "object" && Object.keys(args as object).length === 0)) {
    return <span className="text-muted-foreground">None</span>;
  }
  return (
    <details>
      <summary className="cursor-pointer text-body-sm text-primary underline-offset-4 hover:underline">Show details</summary>
      <pre className="mt-2 max-h-48 max-w-md overflow-auto rounded-md bg-muted p-2 text-caption whitespace-pre-wrap">
        {JSON.stringify(args, null, 2)}
      </pre>
    </details>
  );
}

/** Read-only, admin-only audit log (E7-S2-AC3, IMP-03). Filters live in the URL so a view can be shared. */
export function AuditLog() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filters = filtersFromParams(new URLSearchParams(searchParams.toString()));
  const filterKey = JSON.stringify(filters);

  const form = useForm<AuditFilterForm>({ resolver: zodResolver(auditFilterSchema), defaultValues: toForm(filters) });
  useEffect(() => {
    form.reset(toForm(JSON.parse(filterKey) as AuditFilters));
  }, [filterKey, form]);

  const log = useQuery({
    queryKey: queryKeys.audit(filters),
    queryFn: ({ signal }) => getAuditLog(filters, signal),
    placeholderData: keepPreviousData,
  });

  const navigate = (next: AuditFilters) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value === "" || value === undefined || (key === "page" && value === 1)) continue;
      params.set(key, String(value));
    }
    const search = params.toString();
    router.replace(search ? `${pathname}?${search}` : pathname, { scroll: false });
  };

  const onApply = form.handleSubmit((values) => navigate({ ...values, page: 1 }));
  const errors = form.formState.errors;
  const totalPages = log.data ? Math.max(1, Math.ceil(log.data.total / AUDIT_PAGE_SIZE)) : 1;
  const hasFilters = Boolean(filters.from || filters.to || filters.actor_type || filters.action || filters.patient_id);

  return (
    <>
      <PageHeader title="Activity log" description="Every booking change and assistant action, newest first. Read-only." />

      <form noValidate onSubmit={onApply} className="mb-6 space-y-4 rounded-xl border bg-card p-4" aria-label="Filter the activity log">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Field data-invalid={!!errors.from}>
            <FieldLabel htmlFor="audit-from">From</FieldLabel>
            <Input id="audit-from" type="date" aria-invalid={!!errors.from} {...form.register("from")} />
            <FieldError errors={[errors.from]} />
          </Field>
          <Field data-invalid={!!errors.to}>
            <FieldLabel htmlFor="audit-to">To</FieldLabel>
            <Input id="audit-to" type="date" aria-invalid={!!errors.to} {...form.register("to")} />
            <FieldError errors={[errors.to]} />
          </Field>
          <Controller
            control={form.control}
            name="actor_type"
            render={({ field }) => (
              <Field>
                <FieldLabel htmlFor="audit-actor">Done by</FieldLabel>
                <Select value={field.value || ANY_ACTOR} onValueChange={(v) => field.onChange(v === ANY_ACTOR ? "" : v)}>
                  <SelectTrigger id="audit-actor" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ANY_ACTOR}>Anyone</SelectItem>
                    {Object.entries(ACTOR_LABELS).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            )}
          />
          <Field data-invalid={!!errors.action}>
            <FieldLabel htmlFor="audit-action">Action</FieldLabel>
            <Input id="audit-action" placeholder="appointment.cancel" spellCheck={false} aria-invalid={!!errors.action} {...form.register("action")} />
            <FieldError errors={[errors.action]} />
          </Field>
          <Field data-invalid={!!errors.patient_id}>
            <FieldLabel htmlFor="audit-patient">Patient ID</FieldLabel>
            <Input id="audit-patient" spellCheck={false} aria-invalid={!!errors.patient_id} {...form.register("patient_id")} />
            <FieldError errors={[errors.patient_id]} />
          </Field>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit">
            <Filter aria-hidden />
            Apply filters
          </Button>
          {hasFilters ? (
            <Button type="button" variant="ghost" onClick={() => navigate({ page: 1 })}>
              <X aria-hidden />
              Clear filters
            </Button>
          ) : null}
        </div>
      </form>

      {log.isPending ? (
        <LoadingState label="Loading the activity log" />
      ) : log.isError ? (
        <ErrorState what="the activity log" error={log.error} onRetry={() => log.refetch()} />
      ) : log.data.items.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title={hasFilters ? "Nothing matches these filters" : "No activity recorded yet"}
          description={hasFilters ? "Widen the dates or clear the filters." : undefined}
        />
      ) : (
        <div className="space-y-3" aria-busy={log.isFetching}>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When (UTC)</TableHead>
                  <TableHead>Done by</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead className="text-right">Time taken</TableHead>
                  <TableHead>Details</TableHead>
                  <TableHead>Reference</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {log.data.items.map((entry) => (
                  <TableRow key={String(entry.id)} className="align-top">
                    <TableCell className="whitespace-nowrap tabular">
                      <time dateTime={entry.ts}>{formatUtcTimestamp(entry.ts)}</time>
                    </TableCell>
                    <TableCell>
                      <span className="block">{ACTOR_LABELS[entry.actor_type] ?? entry.actor_type}</span>
                      {entry.actor_id ? <span className="block max-w-40 truncate text-caption text-muted-foreground" title={entry.actor_id}>{entry.actor_id}</span> : null}
                    </TableCell>
                    <TableCell className="font-medium">{entry.action}</TableCell>
                    <TableCell>{entry.result ?? <span className="text-muted-foreground">None</span>}</TableCell>
                    <TableCell className="text-right tabular">{entry.latency_ms === null ? "–" : `${entry.latency_ms} ms`}</TableCell>
                    <TableCell>
                      <ArgsCell args={entry.args} />
                    </TableCell>
                    <TableCell className="text-caption text-muted-foreground">
                      <span className="block max-w-40 truncate select-all" title={entry.request_id ?? undefined}>
                        {entry.request_id ?? "–"}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <nav aria-label="Activity log pages" className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-body-sm text-muted-foreground tabular">
              Page {log.data.page} of {totalPages}, {log.data.total} entries
            </p>
            <div className="flex gap-2">
              <Button variant="outline" disabled={filters.page <= 1 || log.isFetching} onClick={() => navigate({ ...filters, page: filters.page - 1 })}>
                <ChevronLeft aria-hidden />
                Newer
              </Button>
              <Button variant="outline" disabled={filters.page >= totalPages || log.isFetching} onClick={() => navigate({ ...filters, page: filters.page + 1 })}>
                Older
                <ChevronRight aria-hidden data-icon="inline-end" />
              </Button>
            </div>
          </nav>
        </div>
      )}
    </>
  );
}
