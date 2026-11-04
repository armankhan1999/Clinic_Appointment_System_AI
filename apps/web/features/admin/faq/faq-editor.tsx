"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, MessageSquareText, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, InlineError, LoadingState, RefetchNotice } from "@/components/states";
import { useToast } from "@/components/toaster";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { createFaqEntry, deleteFaqEntry, getFaqEntries, updateFaqEntry } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { FaqEntry } from "@/lib/api/schemas";
import { formatRelative, formatUtcTimestamp } from "@/lib/dates";
import { queryKeys } from "@/lib/query";
import { FAQ_ANSWER_MAX, faqFormSchema, parseAliases, type FaqForm } from "@/lib/validation/forms";

function FaqDialog({ open, onOpenChange, entry }: { open: boolean; onOpenChange: (open: boolean) => void; entry: FaqEntry | null }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const form = useForm<FaqForm>({ resolver: zodResolver(faqFormSchema), defaultValues: { topic: "", aliasesText: "", answer: "" } });
  const answer = useWatch({ control: form.control, name: "answer" }) ?? "";

  useEffect(() => {
    if (open) form.reset({ topic: entry?.topic ?? "", aliasesText: entry?.aliases.join(", ") ?? "", answer: entry?.answer ?? "" });
  }, [open, entry, form]);

  const save = useMutation({
    mutationFn: (values: FaqForm) => {
      const input = { topic: values.topic, aliases: parseAliases(values.aliasesText), answer: values.answer };
      return entry ? updateFaqEntry(entry.id, input) : createFaqEntry(input);
    },
    onSuccess: async (saved) => {
      notify({ tone: "success", title: entry ? "Answer updated" : "Answer added", description: saved.topic });
      await queryClient.invalidateQueries({ queryKey: queryKeys.faq });
      onOpenChange(false);
    },
    onError: (error) => {
      // The API answers a duplicate topic with 409 CONFLICT; show it on the field that caused it.
      if (isApiError(error) && error.code === "CONFLICT") {
        form.setError("topic", { message: "Another answer already uses this topic name. Choose a different one or edit that answer." }, { shouldFocus: true });
      }
    },
  });

  const saveError = save.error && !(isApiError(save.error) && save.error.code === "CONFLICT") ? save.error : null;
  const errors = form.formState.errors;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (save.isPending) return;
        if (!next) save.reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <form noValidate onSubmit={form.handleSubmit((values) => save.mutate(values))} className="space-y-5">
          <DialogHeader>
            <DialogTitle>{entry ? "Edit clinic answer" : "Add a clinic answer"}</DialogTitle>
            <DialogDescription>
              The Telegram assistant only answers clinic questions with text approved here.
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field data-invalid={!!errors.topic}>
              <FieldLabel htmlFor="faq-topic">Topic name</FieldLabel>
              <Input id="faq-topic" autoCapitalize="none" spellCheck={false} placeholder="parking_info" aria-invalid={!!errors.topic} {...form.register("topic")} />
              <FieldDescription>Lowercase letters, numbers and underscores, up to 40 characters.</FieldDescription>
              <FieldError errors={[errors.topic]} />
            </Field>
            <Field>
              <FieldLabel htmlFor="faq-aliases">Other ways patients ask (optional)</FieldLabel>
              <Input id="faq-aliases" placeholder="car park, where to park" {...form.register("aliasesText")} />
              <FieldDescription>Separate with commas.</FieldDescription>
            </Field>
            <Field data-invalid={!!errors.answer}>
              <FieldLabel htmlFor="faq-answer">Answer</FieldLabel>
              <Textarea id="faq-answer" rows={6} maxLength={FAQ_ANSWER_MAX} aria-invalid={!!errors.answer} {...form.register("answer")} />
              <FieldDescription>
                {answer.trim().length}/{FAQ_ANSWER_MAX} characters
              </FieldDescription>
              <FieldError errors={[errors.answer]} />
            </Field>
          </FieldGroup>
          <InlineError error={saveError} />
          <DialogFooter>
            <Button type="button" variant="outline" disabled={save.isPending} onClick={() => onOpenChange(false)}>
              Close without saving
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : null}
              {entry ? "Save answer" : "Add answer"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function FaqEditor() {
  const queryClient = useQueryClient();
  const notify = useToast();
  const entries = useQuery({ queryKey: queryKeys.faq, queryFn: ({ signal }) => getFaqEntries(signal) });
  const [editing, setEditing] = useState<FaqEntry | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [deleting, setDeleting] = useState<FaqEntry | null>(null);

  const remove = useMutation({
    mutationFn: (entry: FaqEntry) => deleteFaqEntry(entry.id),
    onSuccess: async () => {
      notify({ tone: "success", title: "Answer deleted" });
      setDeleting(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.faq });
    },
  });

  const open = (entry: FaqEntry | null) => {
    setEditing(entry);
    setFormOpen(true);
  };

  const items = [...(entries.data?.items ?? [])].sort((a, b) => a.topic.localeCompare(b.topic));

  return (
    <>
      <PageHeader
        title="Clinic answers"
        description="Approved answers the Telegram assistant gives about the clinic: hours, fees, parking and similar."
        actions={
          <Button onClick={() => open(null)}>
            <Plus aria-hidden />
            Add answer
          </Button>
        }
      />
      <RefetchNotice query={entries} what="clinic answers" />
      {entries.isPending ? (
        <LoadingState label="Loading clinic answers" />
      ) : entries.isLoadingError ? (
        <ErrorState what="clinic answers" error={entries.error} onRetry={() => entries.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={MessageSquareText}
          title="No clinic answers yet"
          description="Add answers so the assistant can reply to common questions about the clinic."
          action={<Button onClick={() => open(null)}>Add the first answer</Button>}
        />
      ) : (
        <ul className="space-y-3">
          {items.map((entry) => (
            <li key={entry.id} className="rounded-xl border bg-card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <h2 className="text-title font-bold break-all">{entry.topic}</h2>
                  {entry.aliases.length > 0 ? (
                    <p className="text-body-sm text-muted-foreground">Also matches: {entry.aliases.join(", ")}</p>
                  ) : null}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" aria-label={`Edit ${entry.topic}`} onClick={() => open(entry)}>
                    <Pencil aria-hidden />
                    Edit
                  </Button>
                  <Button variant="ghost" size="sm" aria-label={`Delete ${entry.topic}`} onClick={() => setDeleting(entry)}>
                    <Trash2 aria-hidden />
                    Delete
                  </Button>
                </div>
              </div>
              <p className="mt-3 line-clamp-4 max-w-prose whitespace-pre-line">{entry.answer}</p>
              <p className="mt-2 text-caption text-muted-foreground">
                <time dateTime={entry.updated_at} title={formatUtcTimestamp(entry.updated_at)}>
                  Updated {formatRelative(entry.updated_at)}
                </time>
              </p>
            </li>
          ))}
        </ul>
      )}

      <FaqDialog open={formOpen} onOpenChange={setFormOpen} entry={editing} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => {
          if (!o) {
            setDeleting(null);
            remove.reset();
          }
        }}
        title={`Delete "${deleting?.topic ?? ""}"?`}
        description={<p>The assistant will no longer give this answer. This can&apos;t be undone.</p>}
        confirmLabel="Delete answer"
        cancelLabel="Keep answer"
        destructive
        pending={remove.isPending}
        error={remove.error}
        onConfirm={() => (deleting ? remove.mutate(deleting) : undefined)}
      />
    </>
  );
}
