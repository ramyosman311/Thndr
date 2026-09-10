"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { formatRelativeTime } from "@/lib/format";
import { priceStatusMeta } from "@/lib/status-labels";
import { StatusPill } from "@/components/ui/status-pill";
import { PencilIcon } from "@/components/icons";
import { ErrorBlock } from "@/components/ui/query-boundary";
import type { PriceStatus } from "@/types/api";

/** The price-state badge required everywhere a current price is shown
 * (Phase 11, FINANCIAL_RULES.md "Frontend Price States"): a live price
 * always reads differently from a stale/last-known one, and an
 * unavailable price is never rendered as if it were 0. This never
 * infers freshness itself — `status`/`isStale` are exactly what the
 * backend's Price Service already classified. */
export function PriceStateBadge({
  status,
  isStale,
  recordedAt,
}: {
  status: PriceStatus;
  isStale: boolean;
  recordedAt: string | null;
}) {
  const meta = priceStatusMeta(status);
  const showAge = recordedAt !== null && (status === "CURRENT_PRICE_AVAILABLE" || status === "LAST_KNOWN_PRICE");
  return (
    <div className="flex flex-col items-end gap-0.5">
      <StatusPill label={meta.label} tone={isStale && status === "CURRENT_PRICE_AVAILABLE" ? "warning" : meta.tone} />
      {showAge ? <span className="text-[10px] text-muted-foreground">تحديث {formatRelativeTime(recordedAt)}</span> : null}
    </div>
  );
}

/** The manual price edit affordance (pencil -> inline form -> submit),
 * enabled wherever a price can be shown at all. Submitting here NEVER
 * touches transactions, quantities, or average cost — it only records
 * a new observation via POST /api/assets/{id}/price/manual (see
 * FINANCIAL_RULES.md, "Manual Price Never Touches Transaction
 * History"). The price entered is always in the asset's OWN currency,
 * never the portfolio's base currency. */
export function ManualPriceEditor({
  assetId,
  assetCurrency,
  onSaved,
}: {
  assetId: string;
  assetCurrency: string;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [price, setPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = price.trim();
    if (!trimmed || Number.isNaN(Number(trimmed)) || Number(trimmed) <= 0) {
      setError(new ApiError("validation", null, "أدخل سعرًا صحيحًا أكبر من صفر."));
      return;
    }
    setSubmitting(true);
    try {
      await api.setManualPrice(assetId, { price: trimmed, currency: assetCurrency });
      setEditing(false);
      setPrice("");
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
    }
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        aria-label="تعديل السعر يدويًا"
        className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <PencilIcon width={13} height={13} />
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-1.5 rounded-xl border border-border bg-muted/40 p-2.5">
      <div className="flex items-center gap-1.5">
        <input
          autoFocus
          inputMode="decimal"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          placeholder={`السعر بعملة ${assetCurrency}`}
          className="tabular-nums w-28 rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground outline-none focus:border-primary"
        />
        <span className="text-[11px] text-muted-foreground">{assetCurrency}</span>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-primary px-2.5 py-1.5 text-[11px] font-semibold text-primary-foreground disabled:opacity-50"
        >
          {submitting ? "..." : "حفظ"}
        </button>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setError(null);
            setPrice("");
          }}
          className="rounded-lg px-2 py-1.5 text-[11px] font-medium text-muted-foreground hover:text-foreground"
        >
          إلغاء
        </button>
      </div>
      {error ? <ErrorBlock error={error} /> : null}
    </form>
  );
}
