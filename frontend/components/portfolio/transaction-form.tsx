"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api, ApiError } from "@/lib/api";
import { ErrorBlock, LoadingBlock } from "@/components/ui/query-boundary";
import { formatNumber } from "@/lib/format";
import type { TransactionKind, TransactionResultOut } from "@/types/api";

const DECIMAL_PATTERN = /^\d+(\.\d+)?$/;

function todayInputValue(): string {
  return new Date().toISOString().slice(0, 10);
}

interface Props {
  /** Current quantity per asset id, from the already-loaded portfolio
   * summary — used only as a client-side hint to help avoid an oversell
   * before submitting; the backend remains the sole source of truth and
   * validates this again regardless. */
  holdingQuantityByAssetId: Record<string, string>;
  onSuccess: (result: TransactionResultOut) => void;
}

export function TransactionForm({ holdingQuantityByAssetId, onSuccess }: Props) {
  const assetsQuery = useApiQuery(() => api.listAssets());

  const [transactionType, setTransactionType] = useState<TransactionKind>("BUY");
  const [assetId, setAssetId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [fees, setFees] = useState("");
  const [date, setDate] = useState(todayInputValue);
  const [notes, setNotes] = useState("");

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [lastResult, setLastResult] = useState<TransactionResultOut | null>(null);

  const selectedAsset = useMemo(
    () => (assetsQuery.status === "success" ? assetsQuery.data.find((a) => a.id === assetId) : undefined),
    [assetsQuery, assetId]
  );
  const availableQuantity = assetId ? holdingQuantityByAssetId[assetId] : undefined;

  function validate(): Record<string, string> {
    const errors: Record<string, string> = {};
    if (!assetId) errors.assetId = "اختر الأصل المعني بالمعاملة.";
    if (!DECIMAL_PATTERN.test(quantity.trim()) || Number(quantity) <= 0) {
      errors.quantity = "أدخل كمية صحيحة أكبر من صفر.";
    }
    if (!DECIMAL_PATTERN.test(price.trim())) {
      errors.price = "أدخل سعرًا صحيحًا (صفر أو أكبر).";
    }
    if (fees.trim() !== "" && !DECIMAL_PATTERN.test(fees.trim())) {
      errors.fees = "أدخل قيمة رسوم صحيحة (صفر أو أكبر).";
    }
    if (!date) errors.date = "اختر تاريخ المعاملة.";
    if (
      transactionType === "SELL" &&
      availableQuantity !== undefined &&
      DECIMAL_PATTERN.test(quantity.trim()) &&
      Number(quantity) > Number(availableQuantity)
    ) {
      errors.quantity = `الكمية المتاحة للبيع حاليًا: ${formatNumber(availableQuantity)} فقط.`;
    }
    return errors;
  }

  function handleReviewSubmit(e: FormEvent) {
    e.preventDefault();
    const errors = validate();
    setFieldErrors(errors);
    setError(null);
    if (Object.keys(errors).length === 0) {
      setConfirming(true);
    }
  }

  async function handleConfirm() {
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.createTransaction({
        asset_id: assetId,
        transaction_type: transactionType,
        quantity: quantity.trim(),
        price: price.trim(),
        fees: fees.trim() === "" ? "0" : fees.trim(),
        transaction_date: new Date(date).toISOString(),
        notes: notes.trim() || null,
      });
      setLastResult(result);
      onSuccess(result);
      setConfirming(false);
      setQuantity("");
      setPrice("");
      setFees("");
      setNotes("");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
      setConfirming(false);
    } finally {
      setSubmitting(false);
    }
  }

  if (assetsQuery.status === "loading") return <LoadingBlock label="جارٍ تحميل الأصول..." />;
  if (assetsQuery.status === "error") return <ErrorBlock error={assetsQuery.error} onRetry={assetsQuery.refetch} />;

  return (
    <div className="flex flex-col gap-3">
      <p className="rounded-lg bg-warning-muted px-3 py-2 text-[11px] font-medium text-warning">
        تسجيل هذه المعاملة يُحدِّث المحفظة فعليًا ويُضاف كسجل دائم — هذا ليس توصية (التوصية بشأن السيولة الجديدة
        متاحة من صفحة &quot;التوزيع الذكي&quot;).
      </p>

      {!confirming ? (
        <form onSubmit={handleReviewSubmit} className="flex flex-col gap-3" noValidate>
          <div className="flex overflow-hidden rounded-xl border border-border">
            <button
              type="button"
              onClick={() => setTransactionType("BUY")}
              aria-pressed={transactionType === "BUY"}
              className={`flex-1 py-2.5 text-sm font-bold transition-colors ${
                transactionType === "BUY" ? "bg-success text-success-foreground" : "bg-card text-muted-foreground"
              }`}
            >
              شراء
            </button>
            <button
              type="button"
              onClick={() => setTransactionType("SELL")}
              aria-pressed={transactionType === "SELL"}
              className={`flex-1 py-2.5 text-sm font-bold transition-colors ${
                transactionType === "SELL" ? "bg-danger text-danger-foreground" : "bg-card text-muted-foreground"
              }`}
            >
              بيع
            </button>
          </div>

          <Field label="الأصل" error={fieldErrors.assetId}>
            <select
              value={assetId}
              onChange={(e) => setAssetId(e.target.value)}
              className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm text-foreground outline-none focus:border-primary"
            >
              <option value="">اختر أصلًا...</option>
              {assetsQuery.data.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.symbol} — {asset.name}
                </option>
              ))}
            </select>
            {transactionType === "SELL" && selectedAsset ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                الكمية المتاحة حاليًا:{" "}
                <span className="tabular-nums">{availableQuantity ? formatNumber(availableQuantity) : "0"}</span>
              </p>
            ) : null}
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="الكمية" error={fieldErrors.quantity}>
              <input
                inputMode="decimal"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder="10"
                className="tabular-nums w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary"
              />
            </Field>
            <Field label="السعر" error={fieldErrors.price}>
              <input
                inputMode="decimal"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="100.00"
                className="tabular-nums w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary"
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="الرسوم (اختياري)" error={fieldErrors.fees}>
              <input
                inputMode="decimal"
                value={fees}
                onChange={(e) => setFees(e.target.value)}
                placeholder="0.00"
                className="tabular-nums w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary"
              />
            </Field>
            <Field label="التاريخ" error={fieldErrors.date}>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="tabular-nums w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary"
              />
            </Field>
          </div>

          <Field label="ملاحظات (اختياري)">
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full rounded-xl border border-border bg-background px-3 py-2 text-xs text-foreground outline-none focus:border-primary"
            />
          </Field>

          <button
            type="submit"
            className="rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground"
          >
            مراجعة المعاملة
          </button>
        </form>
      ) : (
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-muted p-3">
          <p className="text-sm font-semibold text-foreground">تأكيد تسجيل المعاملة</p>
          <p className="text-xs text-muted-foreground">
            {transactionType === "BUY" ? "شراء" : "بيع"} <span className="tabular-nums">{quantity}</span> من{" "}
            {selectedAsset?.symbol} بسعر <span className="tabular-nums">{price}</span>
            {fees.trim() !== "" && fees.trim() !== "0" ? (
              <>
                {" "}
                ورسوم <span className="tabular-nums">{fees}</span>
              </>
            ) : null}{" "}
            بتاريخ <span className="tabular-nums">{date}</span>.
          </p>
          <p className="text-[11px] font-medium text-danger">
            بمجرد التأكيد سيتم تسجيل هذه المعاملة كسجل دائم في المحفظة.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleConfirm}
              disabled={submitting}
              className="flex-1 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
            >
              {submitting ? "جارٍ التسجيل..." : "تأكيد التسجيل"}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              disabled={submitting}
              className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground"
            >
              تعديل
            </button>
          </div>
        </div>
      )}

      {error ? <ErrorBlock error={error} /> : null}

      {lastResult && !confirming ? (
        <p className="rounded-lg bg-success-muted px-3 py-2 text-xs font-medium text-success">
          تم تسجيل المعاملة بنجاح. الكمية الحالية بعدها:{" "}
          <span className="tabular-nums">{formatNumber(lastResult.holding.quantity)}</span>
          {lastResult.realized_pnl !== null ? (
            <>
              {" "}
              — الربح/الخسارة المحققة من هذا البيع:{" "}
              <span className="tabular-nums">{lastResult.realized_pnl}</span>
            </>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">
      {label}
      {children}
      {error ? (
        <span role="alert" className="text-[11px] font-normal text-danger">
          {error}
        </span>
      ) : null}
    </label>
  );
}
