"use client";

import type { ReactNode } from "react";
import type { QueryState } from "@/hooks/use-api-query";
import { ApiError } from "@/lib/api";
import { AlertTriangleIcon, InboxIcon, RefreshIcon } from "@/components/icons";

function messageForError(error: ApiError): { title: string; body: string } {
  switch (error.kind) {
    case "not_configured":
      return {
        title: "لا توجد بيانات بعد",
        body: error.detail || "لم يتم إعداد المحفظة بعد. أضف إعدادات المحفظة أولًا.",
      };
    case "validation":
      return { title: "بيانات غير صالحة", body: error.detail };
    case "conflict":
      return { title: "تعارض في البيانات", body: error.detail };
    case "network":
      return { title: "تعذّر الاتصال بالخادم", body: error.detail };
    default:
      return { title: "حدث خطأ في الخادم", body: error.detail || "حاول مرة أخرى بعد قليل." };
  }
}

export function LoadingBlock({ label = "جارٍ التحميل..." }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBlock({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const { title, body } = messageForError(error);
  const isNotConfigured = error.kind === "not_configured";
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-2xl border border-border bg-card p-6 text-center"
    >
      {isNotConfigured ? (
        <InboxIcon className="text-muted-foreground" />
      ) : (
        <AlertTriangleIcon className="text-danger" />
      )}
      <div>
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-xs text-muted-foreground">{body}</p>
      </div>
      {onRetry && !isNotConfigured ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1.5 text-xs font-medium text-foreground hover:opacity-80"
        >
          <RefreshIcon width={14} height={14} />
          إعادة المحاولة
        </button>
      ) : null}
    </div>
  );
}

export function EmptyBlock({ title, body }: { title: string; body?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border p-6 text-center text-muted-foreground">
      <InboxIcon />
      <p className="text-sm font-medium text-foreground">{title}</p>
      {body ? <p className="text-xs">{body}</p> : null}
    </div>
  );
}

/** Renders loading/error/success uniformly for any `useApiQuery` result,
 * so every API-driven screen handles the same states consistently. */
export function QueryBoundary<T>({
  state,
  onRetry,
  loadingLabel,
  children,
}: {
  state: QueryState<T>;
  onRetry?: () => void;
  loadingLabel?: string;
  children: (data: T) => ReactNode;
}) {
  if (state.status === "loading") return <LoadingBlock label={loadingLabel} />;
  if (state.status === "error") return <ErrorBlock error={state.error} onRetry={onRetry} />;
  return <>{children(state.data)}</>;
}
