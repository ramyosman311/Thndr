"use client";

import { useEffect, useState } from "react";
import { RefreshIcon } from "@/components/icons";
import { isNativeApp } from "@/lib/capacitor-env";

/** Registers the app-shell service worker and offers a manual, opt-in
 * reload when a new version is ready -- never an automatic reload, so an
 * update can't interrupt someone mid-transaction-entry.
 *
 * Skipped entirely inside the Capacitor native shell (Phase 22): the
 * native app already bundles the full static build on-disk, so there is
 * no "offline app shell" gap for a service worker to fill, and no
 * network-delivered JS update to watch for -- new versions ship through
 * the App/Play Store, not a service-worker swap. Registering one there
 * would add an extra, WebView-inconsistent cache layer for no benefit,
 * and risks a stale Cache Storage entry surviving a native app update.
 * See DECISIONS.md, "Phase 22 — Capacitor Native Wrappers". */
export function ServiceWorkerRegistration() {
  const [waitingWorker, setWaitingWorker] = useState<ServiceWorker | null>(null);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    if (isNativeApp()) return;

    navigator.serviceWorker.register("/sw.js").then((reg) => {
      if (reg.waiting && reg.active) {
        setWaitingWorker(reg.waiting);
      }

      reg.addEventListener("updatefound", () => {
        const installing = reg.installing;
        if (!installing) return;
        installing.addEventListener("statechange", () => {
          if (installing.state === "installed" && navigator.serviceWorker.controller) {
            setWaitingWorker(installing);
          }
        });
      });
    });

    let reloaded = false;
    const onControllerChange = () => {
      if (reloaded) return;
      reloaded = true;
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);

    return () => {
      navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
    };
  }, []);

  if (!waitingWorker) return null;

  return (
    <div
      role="status"
      className="safe-bottom safe-x fixed inset-x-0 bottom-16 z-50 flex justify-center px-4 md:bottom-4"
    >
      <div className="flex items-center gap-3 rounded-full border border-border bg-card px-4 py-2 shadow-lg">
        <span className="text-xs font-medium text-foreground">تحديث جديد متاح</span>
        <button
          type="button"
          onClick={() => waitingWorker.postMessage("SKIP_WAITING")}
          className="inline-flex items-center gap-1.5 rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90"
        >
          <RefreshIcon width={14} height={14} />
          تحديث
        </button>
      </div>
    </div>
  );
}
