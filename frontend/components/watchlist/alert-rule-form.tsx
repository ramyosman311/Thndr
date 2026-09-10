"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { ErrorBlock } from "@/components/ui/query-boundary";
import type { AlertRuleCreateRequest, AlertRuleOut } from "@/types/api";

interface Props {
  watchlistId: string;
  existing: AlertRuleOut | null;
  onSaved: (rule: AlertRuleOut) => void;
}

/** Create/edit form for the single alert rule a watchlist entry may
 * have (1:1 — see DATABASE.md). Only exposes the three DB-backed check
 * types (allocation breach + rebalance suggestion share one flag, price
 * target, dip buy) — never a client-invented alert type. */
export function AlertRuleForm({ watchlistId, existing, onSaved }: Props) {
  const [allocationEnabled, setAllocationEnabled] = useState(existing?.allocation_alert_enabled ?? false);
  const [allocationMax, setAllocationMax] = useState(existing?.allocation_max_percent ?? "");
  const [priceEnabled, setPriceEnabled] = useState(existing?.price_target_enabled ?? false);
  const [priceTarget, setPriceTarget] = useState(existing?.price_target ?? "");
  const [dipEnabled, setDipEnabled] = useState(existing?.dip_buy_enabled ?? false);
  const [dipPrice, setDipPrice] = useState(existing?.dip_buy_price ?? "");
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);
  const [telegramEnabled, setTelegramEnabled] = useState(existing?.telegram_enabled ?? false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (allocationEnabled && !allocationMax) {
      setError(new ApiError("validation", null, "أدخل نسبة تنبيه التخصيص."));
      return;
    }
    if (priceEnabled && !priceTarget) {
      setError(new ApiError("validation", null, "أدخل السعر المستهدف."));
      return;
    }
    if (dipEnabled && !dipPrice) {
      setError(new ApiError("validation", null, "أدخل سعر فرصة الشراء."));
      return;
    }

    const payload: AlertRuleCreateRequest = {
      enabled,
      allocation_alert_enabled: allocationEnabled,
      allocation_max_percent: allocationEnabled ? allocationMax : null,
      price_target_enabled: priceEnabled,
      price_target: priceEnabled ? priceTarget : null,
      dip_buy_enabled: dipEnabled,
      dip_buy_price: dipEnabled ? dipPrice : null,
      telegram_enabled: telegramEnabled,
    };

    setSaving(true);
    try {
      const rule = existing
        ? await api.updateAlertRule(existing.id, payload)
        : await api.createWatchlistAlertRule(watchlistId, payload);
      onSaved(rule);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-xl bg-muted p-3">
      <label className="flex items-center justify-between text-xs font-medium text-foreground">
        تفعيل القاعدة
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
      </label>

      <CheckField
        label="تنبيه عند تجاوز نسبة تخصيص"
        checked={allocationEnabled}
        onCheckedChange={setAllocationEnabled}
      >
        <input
          inputMode="decimal"
          placeholder="النسبة % مثال: 20"
          value={allocationMax}
          onChange={(e) => setAllocationMax(e.target.value)}
          className="tabular-nums w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary"
        />
      </CheckField>

      <CheckField label="تنبيه عند سعر مستهدف" checked={priceEnabled} onCheckedChange={setPriceEnabled}>
        <input
          inputMode="decimal"
          placeholder="السعر المستهدف"
          value={priceTarget}
          onChange={(e) => setPriceTarget(e.target.value)}
          className="tabular-nums w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary"
        />
      </CheckField>

      <CheckField label="فرصة شراء عند انخفاض السعر" checked={dipEnabled} onCheckedChange={setDipEnabled}>
        <input
          inputMode="decimal"
          placeholder="سعر الانخفاض المستهدف"
          value={dipPrice}
          onChange={(e) => setDipPrice(e.target.value)}
          className="tabular-nums w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary"
        />
      </CheckField>

      <div className="flex flex-col gap-1">
        <label className="flex items-center justify-between text-xs font-medium text-foreground">
          إرسال تنبيه عبر تيليجرام
          <input
            type="checkbox"
            checked={telegramEnabled}
            onChange={(e) => setTelegramEnabled(e.target.checked)}
          />
        </label>
        <p className="text-[11px] text-muted-foreground">
          يتطلب أيضًا تفعيل تيليجرام من إعدادات المحفظة، وضبط بيانات الاعتماد من الخادم.
        </p>
      </div>

      {error ? <ErrorBlock error={error} /> : null}

      <button
        type="submit"
        disabled={saving}
        className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-50"
      >
        {saving ? "..." : existing ? "حفظ التعديلات" : "إنشاء قاعدة التنبيه"}
      </button>
    </form>
  );
}

function CheckField({
  label,
  checked,
  onCheckedChange,
  children,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="flex items-center justify-between text-xs font-medium text-foreground">
        {label}
        <input type="checkbox" checked={checked} onChange={(e) => onCheckedChange(e.target.checked)} />
      </label>
      {checked ? children : null}
    </div>
  );
}
