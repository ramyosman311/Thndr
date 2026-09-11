"use client";

import { useState } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api, ApiError } from "@/lib/api";
import { EmptyBlock, QueryBoundary } from "@/components/ui/query-boundary";
import { NotificationItem } from "@/components/notifications/notification-item";
import type { NotificationOut, NotificationsOut } from "@/types/api";

export default function NotificationsPage() {
  const query = useApiQuery(() => api.listNotifications());
  const [overrides, setOverrides] = useState<Record<string, NotificationOut>>({});
  const [markingAll, setMarkingAll] = useState(false);
  const [markAllError, setMarkAllError] = useState<ApiError | null>(null);

  function applyChange(notification: NotificationOut) {
    setOverrides((prev) => ({ ...prev, [notification.id]: notification }));
  }

  function merge(result: NotificationsOut): NotificationOut[] {
    return result.notifications.map((n) => overrides[n.id] ?? n);
  }

  async function markAllRead() {
    setMarkingAll(true);
    setMarkAllError(null);
    try {
      const result = await api.markAllNotificationsRead();
      setOverrides(Object.fromEntries(result.notifications.map((n) => [n.id, n])));
    } catch (err) {
      setMarkAllError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold text-foreground">الإشعارات</h1>

      <QueryBoundary state={query} onRetry={query.refetch} loadingLabel="جارٍ تحميل الإشعارات...">
        {(result) => {
          const merged = merge(result);
          const unread = merged.filter((n) => !n.read).length;

          if (merged.length === 0) {
            return <EmptyBlock title="لا توجد إشعارات جديدة" body="سيظهر هنا أي تنبيه أو توصية تحتاج انتباهك." />;
          }

          return (
            <>
              {unread > 0 ? (
                <div className="flex items-center justify-end">
                  <button
                    type="button"
                    onClick={markAllRead}
                    disabled={markingAll}
                    className="rounded-full bg-muted px-3 py-1.5 text-xs font-medium text-foreground hover:opacity-80 disabled:opacity-50"
                  >
                    {markingAll ? "..." : "تحديد الكل كمقروء"}
                  </button>
                </div>
              ) : null}
              {markAllError ? <p className="text-xs text-danger">{markAllError.detail}</p> : null}
              <div className="flex flex-col gap-3">
                {merged.map((notification) => (
                  <NotificationItem key={notification.id} notification={notification} onMarkedRead={applyChange} />
                ))}
              </div>
            </>
          );
        }}
      </QueryBoundary>
    </div>
  );
}
