import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 pb-6 md:flex-row md:items-end md:justify-between">
      <div className="space-y-1">
        <h1 className="text-display font-bold tracking-tight">{title}</h1>
        {description ? <div className="text-muted-foreground">{description}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
