import Link from "next/link";
import { ArrowLeft, Compass } from "lucide-react";

export const metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <div className="surface-light flex flex-col items-center gap-5 rounded-[1.5rem] border border-hair px-6 py-20 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-full border border-hair bg-bg shadow-sm" aria-hidden>
        <Compass size={24} />
      </span>
      <p className="eyebrow">Error 404</p>
      <h1 className="h1">This page does not exist</h1>
      <p className="max-w-md text-muted">The link may be old or mistyped. Everything else is one click away.</p>
      <div className="flex flex-wrap justify-center gap-2">
        <Link href="/" className="btn-primary">
          <ArrowLeft size={16} aria-hidden /> Back to the home page
        </Link>
        <Link href="/dashboard" className="btn-ghost">
          Open your dashboard
        </Link>
      </div>
    </div>
  );
}
