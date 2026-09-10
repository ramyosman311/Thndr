"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { QueryBoundary, EmptyBlock, ErrorBlock } from "@/components/ui/query-boundary";
import { StatusPill } from "@/components/ui/status-pill";
import { PlusIcon, TrashIcon } from "@/components/icons";
import type { AssetOut, AssetType } from "@/types/api";

const ASSET_TYPES: AssetType[] = ["STOCK", "ETF", "FUND", "GOLD", "SAVINGS", "CASH", "OTHER"];

const inputClass =
  "w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary";
const labelClass = "text-xs font-medium text-muted-foreground";

export function AssetsAdmin() {
  const assetsQuery = useApiQuery(() => api.listAssets(true));
  const bucketsQuery = useApiQuery(() => api.listStrategyBuckets(true));
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const buckets = bucketsQuery.status === "success" ? bucketsQuery.data : [];

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader
          title="الأصول"
          subtitle="إدارة الأصول القابلة للتتبع"
          action={
            <button
              type="button"
              onClick={() => setShowCreate((v) => !v)}
              className="inline-flex items-center gap-1 rounded-full bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
            >
              <PlusIcon width={14} height={14} />
              أصل جديد
            </button>
          }
        />
        <CardBody className="flex flex-col gap-3">
          {showCreate ? (
            <CreateAssetForm
              onCreated={() => {
                setShowCreate(false);
                assetsQuery.refetch();
              }}
              onCancel={() => setShowCreate(false)}
            />
          ) : null}
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="بحث بالرمز أو الاسم..."
            className={inputClass}
          />
          <QueryBoundary state={assetsQuery} onRetry={assetsQuery.refetch} loadingLabel="جارٍ تحميل الأصول...">
            {(assets) => (
              <AssetsList
                assets={assets}
                search={search}
                bucketNameById={Object.fromEntries(buckets.map((b) => [b.id, b.name]))}
                buckets={buckets.map((b) => ({ id: b.id, name: b.name }))}
                onChanged={assetsQuery.refetch}
              />
            )}
          </QueryBoundary>
        </CardBody>
      </Card>
    </div>
  );
}

function CreateAssetForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [symbol, setSymbol] = useState("");
  const [name, setName] = useState("");
  const [assetType, setAssetType] = useState<AssetType>("STOCK");
  const [currency, setCurrency] = useState("EGP");
  const [market, setMarket] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createAsset({
        symbol,
        name,
        asset_type: assetType,
        currency,
        market: market.trim() || null,
      });
      setSymbol("");
      setName("");
      setMarket("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2.5 rounded-xl border border-border bg-muted/40 p-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>الرمز</span>
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} required className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>الاسم</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>نوع الأصل</span>
          <select value={assetType} onChange={(e) => setAssetType(e.target.value as AssetType)} className={inputClass}>
            {ASSET_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>العملة</span>
          <input
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            required
            className={inputClass}
          />
        </label>
        <label className="col-span-2 flex flex-col gap-1">
          <span className={labelClass}>السوق (اختياري)</span>
          <input value={market} onChange={(e) => setMarket(e.target.value)} className={inputClass} />
        </label>
      </div>
      {error ? <ErrorBlock error={error} /> : null}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-50"
        >
          {submitting ? "..." : "إنشاء"}
        </button>
        <button type="button" onClick={onCancel} className="text-xs font-medium text-muted-foreground hover:text-foreground">
          إلغاء
        </button>
      </div>
    </form>
  );
}

function AssetsList({
  assets,
  search,
  bucketNameById,
  buckets,
  onChanged,
}: {
  assets: AssetOut[];
  search: string;
  bucketNameById: Record<string, string>;
  buckets: { id: string; name: string }[];
  onChanged: () => void;
}) {
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return assets;
    return assets.filter((a) => a.symbol.toLowerCase().includes(q) || a.name.toLowerCase().includes(q));
  }, [assets, search]);

  if (filtered.length === 0) {
    return <EmptyBlock title="لا توجد أصول مطابقة" body="جرّب كلمة بحث مختلفة أو أنشئ أصلًا جديدًا." />;
  }

  return (
    <ul className="flex flex-col divide-y divide-border">
      {filtered.map((asset) => (
        <AssetRow key={asset.id} asset={asset} bucketNameById={bucketNameById} buckets={buckets} onChanged={onChanged} />
      ))}
    </ul>
  );
}

function AssetRow({
  asset,
  bucketNameById,
  buckets,
  onChanged,
}: {
  asset: AssetOut;
  bucketNameById: Record<string, string>;
  buckets: { id: string; name: string }[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(asset.name);
  const [market, setMarket] = useState(asset.market ?? "");
  const [strategyBucketId, setStrategyBucketId] = useState(asset.strategy_bucket_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateAsset(asset.id, {
        name,
        market: market.trim() || null,
        ...(strategyBucketId ? { strategy_bucket_id: strategyBucketId } : { clear_strategy_bucket: true }),
      });
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleActive() {
    setBusy(true);
    setError(null);
    try {
      if (asset.is_active) await api.deactivateAsset(asset.id);
      else await api.activateAsset(asset.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteAsset(asset.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-foreground">{asset.symbol}</span>
            <StatusPill label={asset.is_active ? "نشط" : "معطّل"} tone={asset.is_active ? "success" : "neutral"} />
          </div>
          <p className="truncate text-xs text-muted-foreground">{asset.name}</p>
        </div>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium text-primary hover:bg-accent"
        >
          {editing ? "إغلاق" : "تعديل"}
        </button>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span>النوع: {asset.asset_type}</span>
        <span>العملة: {asset.currency}</span>
        <span>السوق: {asset.market ?? "—"}</span>
        <span>الفئة: {asset.strategy_bucket_id ? (bucketNameById[asset.strategy_bucket_id] ?? "—") : "بدون فئة"}</span>
      </div>

      {editing ? (
        <form onSubmit={handleSave} className="flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3">
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1">
              <span className={labelClass}>الاسم</span>
              <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
            </label>
            <label className="flex flex-col gap-1">
              <span className={labelClass}>السوق</span>
              <input value={market} onChange={(e) => setMarket(e.target.value)} className={inputClass} />
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              <span className={labelClass}>الفئة الاستراتيجية</span>
              <select
                value={strategyBucketId}
                onChange={(e) => setStrategyBucketId(e.target.value)}
                className={inputClass}
              >
                <option value="">بدون فئة</option>
                {buckets.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-[11px] text-muted-foreground">
            لا يمكن تغيير العملة من هنا إذا كانت هناك معاملات أو أسعار مسجّلة لهذا الأصل.
          </p>
          {error ? <ErrorBlock error={error} /> : null}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
            >
              {busy ? "..." : "حفظ"}
            </button>
            <button
              type="button"
              onClick={handleToggleActive}
              disabled={busy}
              className="rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-foreground disabled:opacity-50"
            >
              {asset.is_active ? "تعطيل" : "تفعيل"}
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={busy}
              className="mr-auto inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger-muted disabled:opacity-50"
            >
              <TrashIcon width={13} height={13} />
              حذف نهائي
            </button>
          </div>
        </form>
      ) : null}
    </li>
  );
}
