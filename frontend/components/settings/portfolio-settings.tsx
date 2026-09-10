"use client";

import { useState, type FormEvent } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { LoadingBlock, ErrorBlock } from "@/components/ui/query-boundary";
import { AlertTriangleIcon } from "@/components/icons";
import type { AssetOut, PortfolioConfigOut } from "@/types/api";

const inputClass =
  "w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm text-foreground outline-none focus:border-primary";
const labelClass = "text-xs font-medium text-muted-foreground";

/** Portfolio configuration administration (Phase 12). Base currency is
 * financially critical -- see FINANCIAL_RULES.md, "Base Currency Change
 * Policy" -- so a change is confirmed explicitly and the backend (not
 * this component) is the one that ultimately rejects it once any
 * transaction exists; this UI only makes that risk visible up front. */
export function PortfolioSettings() {
  const configQuery = useApiQuery(() => api.getPortfolioConfig());
  const assetsQuery = useApiQuery(() => api.listAssets(true));

  if (configQuery.status === "loading" || assetsQuery.status === "loading") {
    return <LoadingBlock label="جارٍ تحميل إعدادات المحفظة..." />;
  }
  if (configQuery.status === "error" && configQuery.error.kind !== "not_configured") {
    return <ErrorBlock error={configQuery.error} onRetry={configQuery.refetch} />;
  }
  if (assetsQuery.status === "error") {
    return <ErrorBlock error={assetsQuery.error} onRetry={assetsQuery.refetch} />;
  }

  const assets = assetsQuery.data;
  if (configQuery.status === "success") {
    return <PortfolioConfigForm config={configQuery.data} assets={assets} onSaved={configQuery.refetch} />;
  }
  return <PortfolioConfigCreateForm assets={assets} onCreated={configQuery.refetch} />;
}

function PortfolioConfigCreateForm({ assets, onCreated }: { assets: AssetOut[]; onCreated: () => void }) {
  const [name, setName] = useState("محفظتي");
  const [baseCurrency, setBaseCurrency] = useState("EGP");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createPortfolioConfig({ name, base_currency: baseCurrency });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader title="إعداد المحفظة" subtitle="لم يتم إنشاء إعدادات المحفظة بعد" />
      <CardBody>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>اسم المحفظة</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>عملة الأساس</span>
            <input
              value={baseCurrency}
              onChange={(e) => setBaseCurrency(e.target.value.toUpperCase())}
              placeholder="EGP"
              className={inputClass}
            />
          </label>
          {assets.length === 0 ? null : (
            <p className="text-[11px] text-muted-foreground">يمكن ضبط الأصل الاحتياطي بعد إنشاء المحفظة.</p>
          )}
          {error ? <ErrorBlock error={error} /> : null}
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "..." : "إنشاء المحفظة"}
          </button>
        </form>
      </CardBody>
    </Card>
  );
}

function PortfolioConfigForm({
  config,
  assets,
  onSaved,
}: {
  config: PortfolioConfigOut;
  assets: AssetOut[];
  onSaved: () => void;
}) {
  const [name, setName] = useState(config.name);
  const [baseCurrency, setBaseCurrency] = useState(config.base_currency);
  const [emergencyAssetId, setEmergencyAssetId] = useState(config.emergency_asset_id ?? "");
  const [emergencyExcluded, setEmergencyExcluded] = useState(config.emergency_excluded);
  const [confirmingCurrencyChange, setConfirmingCurrencyChange] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [savedMessage, setSavedMessage] = useState(false);

  const currencyChanged = baseCurrency.trim().toUpperCase() !== config.base_currency;

  async function submitChanges() {
    setSubmitting(true);
    setError(null);
    setSavedMessage(false);
    try {
      await api.updatePortfolioConfig({
        name,
        base_currency: baseCurrency.trim().toUpperCase(),
        ...(emergencyAssetId ? { emergency_asset_id: emergencyAssetId } : { clear_emergency_asset: true }),
        emergency_excluded: emergencyExcluded,
      });
      setSavedMessage(true);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
      setConfirmingCurrencyChange(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (currencyChanged && !confirmingCurrencyChange) {
      setConfirmingCurrencyChange(true);
      return;
    }
    await submitChanges();
  }

  return (
    <Card>
      <CardHeader title="إعدادات المحفظة" subtitle={`العملة الحالية: ${config.base_currency}`} />
      <CardBody>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>اسم المحفظة</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
          </label>

          <label className="flex flex-col gap-1">
            <span className={labelClass}>عملة الأساس</span>
            <input
              value={baseCurrency}
              onChange={(e) => {
                setBaseCurrency(e.target.value.toUpperCase());
                setConfirmingCurrencyChange(false);
              }}
              className={inputClass}
            />
          </label>
          {currencyChanged ? (
            <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-muted p-2.5 text-xs text-warning">
              <AlertTriangleIcon width={15} height={15} className="mt-0.5 shrink-0" />
              <p>
                تغيير عملة الأساس يؤثر على كل التقييمات المستقبلية. إذا كانت هناك معاملات مسجّلة بالفعل، سيرفض
                الخادم هذا التغيير للحفاظ على سلامة البيانات المالية التاريخية.
              </p>
            </div>
          ) : null}

          <label className="flex flex-col gap-1">
            <span className={labelClass}>الأصل الاحتياطي (النقد الاحتياطي)</span>
            <select
              value={emergencyAssetId}
              onChange={(e) => setEmergencyAssetId(e.target.value)}
              className={inputClass}
            >
              <option value="">بدون أصل احتياطي</option>
              {assets.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.symbol} — {asset.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={emergencyExcluded}
              onChange={(e) => setEmergencyExcluded(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            استبعاد النقد الاحتياطي من حسابات التوزيع
          </label>

          {error ? <ErrorBlock error={error} /> : null}
          {savedMessage && !error ? <p className="text-xs text-success">تم الحفظ بنجاح.</p> : null}

          <button
            type="submit"
            disabled={submitting}
            className={`rounded-xl px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-50 ${
              confirmingCurrencyChange ? "bg-warning" : "bg-primary"
            }`}
          >
            {submitting
              ? "..."
              : confirmingCurrencyChange
                ? "تأكيد تغيير العملة والحفظ"
                : "حفظ الإعدادات"}
          </button>
          {confirmingCurrencyChange ? (
            <button
              type="button"
              onClick={() => setConfirmingCurrencyChange(false)}
              className="text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              إلغاء
            </button>
          ) : null}
        </form>
      </CardBody>
    </Card>
  );
}
