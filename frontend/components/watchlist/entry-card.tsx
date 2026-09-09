"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { ErrorBlock } from "@/components/ui/query-boundary";
import { AlertRuleForm } from "@/components/watchlist/alert-rule-form";
import { TrashIcon } from "@/components/icons";
import { formatCurrency, formatDateTime } from "@/lib/format";
import type { WatchlistOut } from "@/types/api";

export function WatchlistEntryCard({
  entry,
  onChanged,
}: {
  entry: WatchlistOut;
  onChanged: (updated: WatchlistOut) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function toggleEnabled() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateWatchlistEntry(entry.id, { enabled: !entry.enabled });
      onChanged(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.removeWatchlistEntry(entry.id);
      onChanged(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  const rule = entry.alert_rule;

  return (
    <div className="rounded-2xl border border-border bg-card p-3.5">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-sm font-bold text-foreground">{entry.asset_symbol}</p>
          {entry.notes ? <p className="mt-0.5 text-xs text-muted-foreground">{entry.notes}</p> : null}
          <p className="mt-0.5 text-[11px] text-muted-foreground">أُضيف في {formatDateTime(entry.added_at)}</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input type="checkbox" checked={entry.enabled} disabled={busy} onChange={toggleEnabled} />
            مفعّل
          </label>
          <button
            type="button"
            onClick={remove}
            disabled={busy || !entry.enabled}
            aria-label={`إزالة ${entry.asset_symbol} من المتابعة`}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-danger-muted hover:text-danger disabled:opacity-40"
          >
            <TrashIcon width={16} height={16} />
          </button>
        </div>
      </div>

      {error ? (
        <div className="mt-2">
          <ErrorBlock error={error} />
        </div>
      ) : null}

      <div className="mt-3 border-t border-border pt-3">
        {rule ? <AlertRuleSummary rule={rule} /> : <p className="text-xs text-muted-foreground">لا توجد قاعدة تنبيه بعد.</p>}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-xs font-semibold text-primary"
        >
          {expanded ? "إخفاء إعدادات التنبيه" : rule ? "تعديل التنبيه" : "إضافة تنبيه"}
        </button>
        {expanded ? (
          <div className="mt-2">
            <AlertRuleForm
              watchlistId={entry.id}
              existing={rule}
              onSaved={(updatedRule) => {
                onChanged({ ...entry, alert_rule: updatedRule });
                setExpanded(false);
              }}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AlertRuleSummary({ rule }: { rule: NonNullable<WatchlistOut["alert_rule"]> }) {
  const parts: string[] = [];
  if (rule.allocation_alert_enabled && rule.allocation_max_percent) {
    parts.push(`تخصيص ≥ ${rule.allocation_max_percent}%`);
  }
  if (rule.price_target_enabled && rule.price_target) {
    parts.push(`سعر ≥ ${formatCurrency(rule.price_target)}`);
  }
  if (rule.dip_buy_enabled && rule.dip_buy_price) {
    parts.push(`انخفاض ≤ ${formatCurrency(rule.dip_buy_price)}`);
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className={`font-semibold ${rule.enabled ? "text-primary" : "text-muted-foreground"}`}>
        {rule.enabled ? "مفعّلة" : "موقوفة"}
      </span>
      {parts.length > 0 ? (
        <span className="text-muted-foreground">{parts.join(" · ")}</span>
      ) : (
        <span className="text-muted-foreground">بدون شروط مُفعّلة</span>
      )}
      {rule.last_triggered_at ? (
        <span className="rounded-full bg-warning-muted px-2 py-0.5 text-[10px] text-warning">
          آخر تنبيه: {formatDateTime(rule.last_triggered_at)}
        </span>
      ) : null}
    </div>
  );
}
