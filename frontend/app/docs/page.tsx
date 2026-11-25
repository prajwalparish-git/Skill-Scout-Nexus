import { Suspense } from "react";
import { DocsHub } from "@/components/docs/DocsHub";

// The documentation hub. DocsHub reads ?tab= (useSearchParams), so it renders inside Suspense:
// the static export then ships the page shell and the guide appears once the query is read.
function DocsFallback() {
  return (
    <div className="mx-auto max-w-6xl px-4 pb-8 pt-28 sm:px-6 sm:pt-32" role="status">
      <span className="sr-only">Loading the documentation</span>
      <div className="h-4 w-32 animate-pulse rounded bg-surface" />
      <div className="mt-5 h-12 max-w-2xl animate-pulse rounded-xl bg-surface" />
      <div className="mt-10 grid gap-8 lg:grid-cols-[250px_minmax(0,1fr)]">
        <div className="hidden h-72 animate-pulse rounded-2xl bg-surface lg:block" />
        <div className="h-[28rem] animate-pulse rounded-2xl bg-surface" />
      </div>
    </div>
  );
}

export default function DocsPage() {
  return (
    <Suspense fallback={<DocsFallback />}>
      <DocsHub />
    </Suspense>
  );
}
