"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { ErrorBlock, LoadingBlock } from "@/components/ui/query-boundary";
import { alertTypeLabel } from "@/lib/status-labels";
import type { AlertEvaluationOut } from "@/types/api";

/** Triggers POST /api/alerts/evaluate on demand and renders the raw
 * backend result. Purely a display of "condition triggered or not" —
 * never a trade, never a Telegram send (Phase 8/9 scope). */
export function EvaluatePanel() {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<AlertEvaluationOut | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const data = await api.evaluateAlerts();
      setResult(data);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        onClick={run}
        disabled={running}
        className="rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
      >
        {running ? "جارٍ التقييم..." : "تقييم التنبيهات الآن"}
      </button>

      {running ? <LoadingBlock label="جارٍ تقييم كل قواعد التنبيه المفعّلة..." /> : null}
      {error ? <ErrorBlock error={error} onRetry={run} /> : null}

      {result && !running ? (
        result.results.length === 0 ? (
          <p className="text-xs text-muted-foreground">لا توجد قواعد تنبيه مفعّلة لتقييمها حاليًا.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {result.results.map((entry, i) => (
              <li
                key={`${entry.alert_rule_id}-${entry.alert_type}-${i}`}
                className={`rounded-xl border p-3 text-xs ${
                  entry.condition_met ? "border-warning/40 bg-warning-muted" : "border-border bg-muted"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-foreground">
                    {entry.asset_symbol} — {alertTypeLabel(entry.alert_type)}
                  </span>
                  {entry.is_new_trigger ? (
                    <span className="rounded-full bg-danger px-2 py-0.5 text-[10px] font-bold text-danger-foreground">
                      جديد
                    </span>
                  ) : entry.should_clear ? (
                    <span className="rounded-full bg-success px-2 py-0.5 text-[10px] font-bold text-success-foreground">
                      زال الشرط
                    </span>
                  ) : entry.condition_met ? (
                    <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                      مستمر
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-muted-foreground">{entry.reason}</p>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}
