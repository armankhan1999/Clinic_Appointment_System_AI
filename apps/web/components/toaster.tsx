"use client";

import { CircleCheck, CircleAlert, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Tone = "success" | "error";
type Toast = { id: number; tone: Tone; title: string; description?: string; requestId?: string | null };
type Notify = (toast: Omit<Toast, "id">) => void;

const ToastContext = createContext<Notify | null>(null);

const DISMISS_MS: Record<Tone, number> = { success: 6_000, error: 12_000 };

/** Small, dependency-free toast stack with polite/assertive live regions for screen readers. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);

  const notify = useCallback<Notify>(
    (toast) => {
      const id = nextId.current++;
      setToasts((all) => [...all.slice(-3), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), DISMISS_MS[toast.tone]);
    },
    [dismiss],
  );

  const regions = useMemo(
    () => ({
      success: toasts.filter((t) => t.tone === "success"),
      error: toasts.filter((t) => t.tone === "error"),
    }),
    [toasts],
  );

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] flex flex-col items-end gap-2 sm:inset-x-auto sm:right-6 sm:bottom-6 sm:w-96">
        <div role="status" aria-live="polite" className="flex w-full flex-col items-end gap-2">
          {regions.success.map((t) => (
            <ToastCard key={t.id} toast={t} onDismiss={dismiss} />
          ))}
        </div>
        <div role="alert" aria-live="assertive" className="flex w-full flex-col items-end gap-2">
          {regions.error.map((t) => (
            <ToastCard key={t.id} toast={t} onDismiss={dismiss} />
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const Icon = toast.tone === "success" ? CircleCheck : CircleAlert;
  return (
    <div
      className={cn(
        "pointer-events-auto flex w-full items-start gap-3 rounded-lg border border-l-4 bg-card p-3 text-sm shadow-[var(--shadow-overlay)]",
        toast.tone === "success" ? "border-l-status-booked-edge" : "border-l-destructive",
      )}
    >
      <Icon
        aria-hidden
        className={cn("mt-0.5 size-5 shrink-0", toast.tone === "success" ? "text-status-booked" : "text-destructive")}
      />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-foreground">{toast.title}</p>
        {toast.description ? <p className="mt-0.5 text-muted-foreground">{toast.description}</p> : null}
        {toast.requestId ? (
          <p className="mt-1 text-caption text-muted-foreground">
            Support reference: <span className="tabular select-all">{toast.requestId}</span>
          </p>
        ) : null}
      </div>
      <Button variant="ghost" size="icon-sm" aria-label="Dismiss message" onClick={() => onDismiss(toast.id)}>
        <X aria-hidden />
      </Button>
    </div>
  );
}

export function useToast(): Notify {
  const notify = useContext(ToastContext);
  if (!notify) throw new Error("useToast must be used inside <ToastProvider>");
  return notify;
}
