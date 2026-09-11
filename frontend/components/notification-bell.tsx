"use client";

import Link from "next/link";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/lib/api";
import { BellIcon } from "@/components/icons";

/** Phase 19: header-level entry point into the Notification Center —
 * only renders the unread count the backend already computed, never a
 * client-side recount. */
export function NotificationBell() {
  const query = useApiQuery(() => api.listNotifications());
  const unreadCount = query.status === "success" ? query.data.unread_count : 0;

  return (
    <Link
      href="/notifications"
      aria-label={unreadCount > 0 ? `الإشعارات — ${unreadCount} غير مقروء` : "الإشعارات"}
      className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <BellIcon width={18} height={18} aria-hidden="true" />
      {unreadCount > 0 ? (
        <span
          aria-hidden="true"
          className="absolute -end-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-bold leading-none text-danger-foreground"
        >
          {unreadCount > 9 ? "9+" : unreadCount}
        </span>
      ) : null}
    </Link>
  );
}
