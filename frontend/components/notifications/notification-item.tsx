"use client";

import Link from "next/link";
import { useState } from "react";
import { StatusPill } from "@/components/ui/status-pill";
import { CheckCircleIcon } from "@/components/icons";
import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import {
  notificationActionHref,
  notificationActionLabel,
  notificationCategoryLabel,
  recommendationSeverityTone,
} from "@/lib/status-labels";
import type { NotificationOut } from "@/types/api";

/** One notification row — renders the backend's own Arabic title/
 * message/severity/category verbatim (see ARCHITECTURE.md, "Frontend
 * Layering"). `action` is a navigation hint only — following it never
 * executes a trade or any financial action. */
export function NotificationItem({
  notification,
  onMarkedRead,
}: {
  notification: NotificationOut;
  onMarkedRead: (updated: NotificationOut) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const tone = recommendationSeverityTone(notification.severity);
  const href = notificationActionHref(notification.action);

  async function markRead() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.markNotificationRead(notification.id);
      onMarkedRead(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={`rounded-2xl border p-3.5 transition-opacity ${
        notification.read ? "border-border bg-card opacity-70" : "border-border bg-card"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <StatusPill label={notification.severity} tone={tone} />
          <span className="text-[11px] text-muted-foreground">{notificationCategoryLabel(notification.category)}</span>
        </div>
        {!notification.read ? (
          <button
            type="button"
            onClick={markRead}
            disabled={busy}
            aria-label="تحديد كمقروء"
            className="rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            <CheckCircleIcon width={16} height={16} />
          </button>
        ) : null}
      </div>

      <p className="mt-2 text-sm font-bold text-foreground">{notification.title}</p>
      <p className="mt-1 text-xs leading-relaxed text-foreground/80">{notification.message}</p>

      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">{formatDateTime(notification.created_at)}</p>
        {href ? (
          <Link href={href} className="text-xs font-semibold text-primary hover:underline">
            {notificationActionLabel(notification.action as string)} ←
          </Link>
        ) : null}
      </div>

      {error ? <p className="mt-2 text-[11px] text-danger">{error.detail}</p> : null}
    </div>
  );
}
