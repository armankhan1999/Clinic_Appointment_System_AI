import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="mx-auto flex max-w-xl flex-col items-start gap-4 p-8">
      <h1 className="text-heading font-bold">This page doesn&apos;t exist</h1>
      <p className="text-muted-foreground">The link may be old or mistyped.</p>
      <Button asChild>
        <Link href="/">Go to today&apos;s schedule</Link>
      </Button>
    </main>
  );
}
