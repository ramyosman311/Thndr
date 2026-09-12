"use client";

import { useEffect, useState } from "react";
import { AlertTriangleIcon } from "@/components/icons";

/** Global offline notice. Additive to per-request error handling
 * (ErrorBlock/QueryBoundary) -- this is a standing banner so it's clear
 * at a glance that any financial figures on screen cannot be refreshed
 * right now, not just that one request failed. */
export function OfflineBanner() {
  const [isOffline, setIsOffline] = useState(false);

  useEffect(() => {
    // One-time read of the browser's current connectivity state on mount
    // (server-rendered with isOffline=false, since navigator isn't
    // available server-side) -- not state derived from props.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time mount sync, not a cascading update
    setIsOffline(!navigator.onLine);
    const onOffline = () => setIsOffline(true);
    const onOnline = () => setIsOffline(false);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, []);

  if (!isOffline) return null;

  return (
    <div
      role="alert"
      className="safe-x flex items-center justify-center gap-2 bg-warning-muted px-4 py-2 text-xs font-medium text-warning"
    >
      <AlertTriangleIcon width={14} height={14} />
      <span>لا يوجد اتصال حاليًا. لا يمكن تحديث بيانات المحفظة.</span>
    </div>
  );
}
