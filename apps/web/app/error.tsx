"use client";

import { CircleAlert, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function RouteError({ retry }: { error: unknown; retry: () => void }) {
  return (
    <div role="alert" className="mx-auto flex max-w-xl flex-col items-start gap-4 p-8">
      <CircleAlert aria-hidden className="size-8 text-destructive" />
      <div className="space-y-1">
        <h1 className="text-heading font-bold">This screen hit a problem</h1>
        <p className="text-muted-foreground">
          Try again. If it keeps happening, reload the page or tell the clinic admin.
        </p>
      </div>
      <Button onClick={() => retry()}>
        <RefreshCw aria-hidden />
        Try again
      </Button>
    </div>
  );
}
