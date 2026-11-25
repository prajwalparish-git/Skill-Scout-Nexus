"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function FacultyRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/org-admin");
  }, [router]);

  return (
    <div className="grid min-h-[50vh] place-items-center p-8 text-center">
      <div className="space-y-2">
        <p className="text-lg font-semibold text-ink">Redirecting to Organization Admin...</p>
        <p className="text-sm text-muted">The faculty dashboard is now unified at /org-admin.</p>
      </div>
    </div>
  );
}
