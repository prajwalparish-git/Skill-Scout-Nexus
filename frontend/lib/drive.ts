"use client";

// Google Drive (server_drive.py): whether the server offers it and whether this student has
// connected it. Everything Drive-related stays hidden while `enabled` is false.

import { useEffect, useState } from "react";
import { get, type DriveStatus } from "@/lib/api";

const OFF: DriveStatus = { enabled: false, connected: false, folder_link: "" };

/** The student's Drive status, fetched once per student; `set` replaces it after an action. */
export function useDrive(studentId: string | undefined): [DriveStatus, (s: DriveStatus) => void] {
  const [status, setStatus] = useState<DriveStatus>(OFF);
  useEffect(() => {
    setStatus(OFF);
    if (!studentId) return;
    let live = true;
    get<DriveStatus>("/api/drive").then(
      (s) => live && setStatus(s),
      () => live && setStatus(OFF), // no Drive is the quiet default
    );
    return () => {
      live = false;
    };
  }, [studentId]);
  return [status, setStatus];
}
