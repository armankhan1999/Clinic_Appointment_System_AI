"use client";

import "./globals.css";

export default function GlobalError({ retry }: { error: unknown; retry: () => void }) {
  return (
    <html lang="en">
      <body>
        <title>Something went wrong | Front Desk</title>
        <main role="alert" className="mx-auto flex max-w-xl flex-col items-start gap-4 p-8">
          <h1 className="text-heading font-bold">Front Desk hit a problem</h1>
          <p className="text-muted-foreground">Try again. If it keeps happening, reload the page or tell the clinic admin.</p>
          <button
            type="button"
            onClick={() => retry()}
            className="h-10 rounded-lg bg-primary px-4 font-medium text-primary-foreground"
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
