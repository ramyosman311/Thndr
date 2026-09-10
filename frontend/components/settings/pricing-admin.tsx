"use client";

import { useState, type FormEvent } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { QueryBoundary, ErrorBlock } from "@/components/ui/query-boundary";
import { StatusPill } from "@/components/ui/status-pill";

const inputClass =
  "w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary";
const labelClass = "text-xs font-medium text-muted-foreground";

/** Registered providers this build actually implements (Phase 11:
 * Yahoo Finance). Never a free-text field -- the backend validates
 * against the real registry regardless, but offering only real choices
 * here avoids a round-trip just to discover a typo (see
 * FINANCIAL_RULES.md, "Provider Configuration Is Data, Not Code"). */
const KNOWN_PROVIDERS = ["mubasher", "yahoo"];

export function PricingAdmin() {
  const assetsQuery = useApiQuery(() => api.listAssets(true));
  const [selectedAssetId, setSelectedAssetId] = useState<string>("");

  return (
    <Card>
      <CardHeader title="إعداد مصادر الأسعار" subtitle="اختر أصلًا لضبط مزوّد السعر الخاص به" />
      <CardBody className="flex flex-col gap-3">
        <QueryBoundary state={assetsQuery} onRetry={assetsQuery.refetch} loadingLabel="جارٍ تحميل الأصول...">
          {(assets) => (
            <>
              <select
                value={selectedAssetId}
                onChange={(e) => setSelectedAssetId(e.target.value)}
                className={inputClass}
              >
                <option value="">اختر أصلًا...</option>
                {assets.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.symbol} — {asset.name} ({asset.currency})
                  </option>
                ))}
              </select>
              {selectedAssetId ? <PriceConfigEditor assetId={selectedAssetId} /> : null}
            </>
          )}
        </QueryBoundary>
      </CardBody>
    </Card>
  );
}

function PriceConfigEditor({ assetId }: { assetId: string }) {
  const configQuery = useApiQuery(() => api.getAssetPriceConfig(assetId), [assetId]);

  return (
    <QueryBoundary state={configQuery} onRetry={configQuery.refetch} loadingLabel="جارٍ تحميل إعداد السعر...">
      {(config) => <PriceConfigForm assetId={assetId} config={config} onSaved={configQuery.refetch} />}
    </QueryBoundary>
  );
}

function PriceConfigForm({
  assetId,
  config,
  onSaved,
}: {
  assetId: string;
  config: {
    configured: boolean;
    primary_provider: string | null;
    primary_provider_symbol: string | null;
    automated_fetching_enabled: boolean;
    manual_override_enabled: boolean;
    stale_threshold_minutes: number | null;
    lock_manual: boolean;
  };
  onSaved: () => void;
}) {
  const [primaryProvider, setPrimaryProvider] = useState(config.primary_provider ?? "");
  const [primaryProviderSymbol, setPrimaryProviderSymbol] = useState(config.primary_provider_symbol ?? "");
  const [automatedFetchingEnabled, setAutomatedFetchingEnabled] = useState(config.automated_fetching_enabled);
  const [manualOverrideEnabled, setManualOverrideEnabled] = useState(config.manual_override_enabled);
  const [staleThreshold, setStaleThreshold] = useState(
    config.stale_threshold_minutes !== null ? String(config.stale_threshold_minutes) : ""
  );
  const [lockManual, setLockManual] = useState(config.lock_manual);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setSaved(false);
    try {
      await api.putAssetPriceConfig(assetId, {
        primary_provider: primaryProvider.trim() || null,
        primary_provider_symbol: primaryProviderSymbol.trim() || null,
        automated_fetching_enabled: automatedFetchingEnabled,
        manual_override_enabled: manualOverrideEnabled,
        stale_threshold_minutes: staleThreshold.trim() ? Number(staleThreshold.trim()) : null,
        lock_manual: lockManual,
      });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-xl border border-border bg-muted/40 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-foreground">حالة الإعداد</span>
        <StatusPill
          label={config.configured ? "مُهيّأ" : "غير مُهيّأ (يدوي فقط)"}
          tone={config.configured ? "success" : "neutral"}
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>المزوّد الأساسي</span>
          <select value={primaryProvider} onChange={(e) => setPrimaryProvider(e.target.value)} className={inputClass}>
            <option value="">بدون (يدوي فقط)</option>
            {KNOWN_PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>رمز المزوّد</span>
          <input
            value={primaryProviderSymbol}
            onChange={(e) => setPrimaryProviderSymbol(e.target.value)}
            placeholder="مثال: TMGH.CA"
            className={inputClass}
          />
        </label>
        <label className="col-span-2 flex flex-col gap-1">
          <span className={labelClass}>حد التقادم (بالدقائق، اختياري)</span>
          <input
            inputMode="numeric"
            value={staleThreshold}
            onChange={(e) => setStaleThreshold(e.target.value)}
            placeholder="افتراضي حسب نوع الأصل"
            className={inputClass}
          />
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          checked={automatedFetchingEnabled}
          onChange={(e) => setAutomatedFetchingEnabled(e.target.checked)}
          className="h-4 w-4 rounded border-border"
        />
        تفعيل الجلب الآلي للسعر
      </label>
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          checked={manualOverrideEnabled}
          onChange={(e) => setManualOverrideEnabled(e.target.checked)}
          className="h-4 w-4 rounded border-border"
        />
        السماح بتعديل السعر يدويًا
      </label>
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          checked={lockManual}
          onChange={(e) => setLockManual(e.target.checked)}
          className="h-4 w-4 rounded border-border"
        />
        قفل السعر اليدوي (منع الجلب الآلي من تجاوزه)
      </label>

      {error ? <ErrorBlock error={error} /> : null}
      {saved && !error ? <p className="text-xs text-success">تم الحفظ بنجاح.</p> : null}

      <button
        type="submit"
        disabled={submitting}
        className="w-fit rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "..." : "حفظ إعداد السعر"}
      </button>
    </form>
  );
}
